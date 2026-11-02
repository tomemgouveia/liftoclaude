"""All D1 access: users, their encrypted credentials, and the Strava
tokens SyncService reads and writes through D1TokenStore."""

import logging
import uuid
from typing import Any

from liftostrava.tokens import StravaTokens
from liftostrava_worker.security.crypto import decrypt, encrypt
from liftostrava_worker.storage.models import AccessIDKey, User

logger = logging.getLogger(__name__)

ENCRYPTED_FIELDS = ("liftosaur_api_key", "strava_access_token", "strava_refresh_token")


def _to_python(value: Any) -> Any:
    """D1 rows arrive as JsProxy objects under Pyodide; plain dicts
    (e.g. in tests) pass through."""
    return value.to_py() if hasattr(value, "to_py") else value


class UserRepository:
    def __init__(self, db: Any, aes_key: bytes):
        self.db = db
        self.aes_key = aes_key

    async def get_user(self, id_key: AccessIDKey) -> User | None:
        sql = """
            SELECT
                u.id AS user_id,
                u.email,
                u.name,
                c.user_id IS NOT NULL AS has_credentials,
                u.timezone,
                c.liftosaur_api_key,
                c.strava_refresh_token,
                c.strava_access_token,
                c.strava_expires_at
            FROM users AS u
            LEFT JOIN credentials AS c ON c.user_id = u.id
            WHERE {}
            """
        if id_key.service_token_id is not None:
            query = (
                await self.db.prepare(sql.format("u.access_service_token_id = ?"))
                .bind(id_key.service_token_id)
                .run()
            )
        elif id_key.email is not None:
            query = (
                await self.db.prepare(sql.format("lower(u.email) = ?"))
                .bind(id_key.email)
                .run()
            )
        else:
            logger.error("Authenticated Access id_key has no identity")
            return None

        if not query.results:
            return None
        row = _to_python(query.results[0])
        row["has_credentials"] = bool(row["has_credentials"])
        for field in ENCRYPTED_FIELDS:
            if row.get(field):
                row[field] = await decrypt(row[field], self.aes_key)
        return User(**row)

    async def get_or_create_user(self, email: str) -> User:
        id_key = AccessIDKey(email=email)
        user = await self.get_user(id_key)
        if user is None:
            await (
                self.db.prepare(
                    "INSERT OR IGNORE INTO users (id, email, name) VALUES (?, ?, ?)"
                )
                .bind(str(uuid.uuid4()), email, email.split("@")[0])
                .run()
            )
            user = await self.get_user(id_key)
        if user is None:
            raise RuntimeError("Could not create user")
        return user

    async def save_settings(
        self, user_id: str, timezone: str, liftosaur_api_key: str
    ) -> None:
        """Always updates the timezone; the Liftosaur key only when one
        was supplied."""
        await (
            self.db.prepare("UPDATE users SET timezone = ? WHERE id = ?")
            .bind(timezone, user_id)
            .run()
        )
        if liftosaur_api_key:
            await (
                self.db.prepare(
                    """
                    INSERT INTO credentials (user_id, liftosaur_api_key)
                    VALUES (?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        liftosaur_api_key = excluded.liftosaur_api_key,
                        updated_at = unixepoch()
                    """
                )
                .bind(user_id, await encrypt(liftosaur_api_key, self.aes_key))
                .run()
            )

    async def save_strava_tokens(self, user_id: str, tokens: StravaTokens) -> None:
        sql = """
            INSERT INTO credentials
                (user_id, strava_access_token, strava_refresh_token, strava_expires_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                strava_access_token = excluded.strava_access_token,
                strava_refresh_token = excluded.strava_refresh_token,
                strava_expires_at = excluded.strava_expires_at,
                updated_at = unixepoch()
            """
        await (
            self.db.prepare(sql)
            .bind(
                user_id,
                await encrypt(tokens.access_token, self.aes_key),
                await encrypt(tokens.refresh_token, self.aes_key),
                tokens.expires_at,
            )
            .run()
        )


class D1TokenStore:
    """TokenStore for one user's Strava tokens, kept encrypted in D1."""

    def __init__(self, repo: UserRepository, user: User):
        self.repo = repo
        self.user = user

    async def load(self) -> StravaTokens | None:
        return self.user.strava_tokens()

    async def save(self, tokens: StravaTokens) -> None:
        await self.repo.save_strava_tokens(self.user.user_id, tokens)
