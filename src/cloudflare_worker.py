import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Any, cast
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from workers import Request, Response, WorkerEntrypoint

from cloudflare import AccessIDKey, User, process_jwt
from cloudflare.credential_crypto import (
    AES_LABEL,
    STATE_LABEL,
    decrypt,
    derive_key,
    encrypt,
)
from cloudflare.history_range import HistoryRangeError, parse_history_range
from cloudflare.oauth_state import sign_state, verify_state
from liftostrava.sources.api import LiftosaurApiSource
from liftostrava.strava.auth import (
    StravaTokens,
    build_authorize_url,
    exchange_authorization_code,
    refresh_strava_tokens,
)
from liftostrava.strava.client import (
    StravaUploadError,
    fetch_upload_status,
    set_muted,
    upload_activity,
    upload_timeout_error,
)
from liftostrava.strava.payload import default_utc_offset

UPLOAD_POLL_TIMEOUT_S = 30


def _to_python(value: Any) -> Any:
    """D1 rows arrive as JsProxy objects under Pyodide; plain dicts
    (e.g. in tests) pass through."""
    return value.to_py() if hasattr(value, "to_py") else value


async def poll_upload_async(access_token: str, upload_id: int) -> dict:
    """poll_upload with asyncio.sleep, so the worker's event loop isn't
    blocked while Strava processes the upload."""
    status = None
    deadline = time.time() + UPLOAD_POLL_TIMEOUT_S
    while time.time() < deadline:
        status = fetch_upload_status(access_token, upload_id)
        if status.get("activity_id"):
            return status
        await asyncio.sleep(1)
    raise upload_timeout_error(status)


logger = logging.getLogger(__name__)


def _origin(url: str) -> str:
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc}"


class Default(WorkerEntrypoint):
    async def fetch(self, request: Request) -> Response:
        id_key = await self.get_access_id_key(request)
        if id_key is None:
            return Response("Cloudflare Access authentication required", status=401)

        path = urlparse(request.url).path.rstrip("/") or "/"
        if path.startswith("/connect") or path == "/api/settings":
            return await self.handle_connect(request, id_key, path)

        match (request.method, path):
            case ("POST", "/" | "/api/sync"):
                # Browsers always send Origin on POSTs; reject cross-site
                # ones. Service-token clients send none.
                origin = request.headers.get("origin")
                if origin is not None and origin != _origin(request.url):
                    return Response("Forbidden", status=403)
                return await self.handle_post(request, id_key)
            case ("GET", "/api/workouts"):
                return await self.handle_get(id_key, request)
            case ("GET", "/"):
                # Browsers get the app; API clients keep the JSON list.
                if "text/html" not in (request.headers.get("accept") or ""):
                    return await self.handle_get(id_key, request)
                return await self.env.ASSETS.fetch(request)
            case ("GET" | "HEAD", _):
                # Built frontend files (JS, CSS, icons).
                return await self.env.ASSETS.fetch(request)
            case _:
                return Response("Method Not Allowed", status=405)

    async def get_access_id_key(self, request: Request) -> AccessIDKey | None:
        assertion = request.headers.get("cf-access-jwt-assertion")
        if assertion:
            team_domain = self.env.CF_ACCESS_TEAM_DOMAIN
            expected_audience = self.env.CF_ACCESS_AUD
            if not isinstance(team_domain, str) or not isinstance(
                expected_audience, str
            ):
                logger.error(
                    "Cloudflare Access team domain or audience is not configured"
                )
                return None
            return await process_jwt(assertion, team_domain, expected_audience)

        access = self.ctx.access
        if access is None:
            logger.warning("Cloudflare Access identity and JWT assertion are missing")
            return None
        identity = await access.getIdentity()
        email = identity.email if identity is not None else None
        if not isinstance(email, str) or not email.strip():
            logger.warning("Cloudflare Access identity did not contain an email")
            return None
        return AccessIDKey(email=email.strip().lower())

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
                await self.env.liftostrava_users_db.prepare(
                    sql.format("u.access_service_token_id = ?")
                )
                .bind(id_key.service_token_id)
                .run()
            )
        elif id_key.email is not None:
            query = (
                await self.env.liftostrava_users_db.prepare(
                    sql.format("lower(u.email) = ?")
                )
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
        for field in (
            "liftosaur_api_key",
            "strava_access_token",
            "strava_refresh_token",
        ):
            if row.get(field):
                row[field] = await decrypt(row[field], self.aes_key())
        return User(**row)

    def secret_key(self, label: bytes) -> bytes:
        master = self.env.CREDENTIALS_SECRET
        if not isinstance(master, str) or not master:
            raise RuntimeError("CREDENTIALS_SECRET is not configured")
        return derive_key(master, label)

    def aes_key(self) -> bytes:
        return self.secret_key(AES_LABEL)

    async def get_or_create_user(self, email: str) -> User:
        id_key = AccessIDKey(email=email)
        user = await self.get_user(id_key)
        if user is None:
            await (
                self.env.liftostrava_users_db.prepare(
                    "INSERT OR IGNORE INTO users (id, email, name) VALUES (?, ?, ?)"
                )
                .bind(str(uuid.uuid4()), email, email.split("@")[0])
                .run()
            )
            user = await self.get_user(id_key)
        if user is None:
            raise RuntimeError("Could not create user")
        return user

    async def handle_connect(
        self, request: Request, id_key: AccessIDKey, path: str
    ) -> Response:
        """Self-service onboarding: a signed-in (email) user saves their
        Liftosaur key and timezone and connects Strava via OAuth. The UI is
        the React app; this serves it plus the settings API and the OAuth
        redirects."""
        if id_key.email is None:
            return Response("Sign in with your email to use this page", status=403)
        base = _origin(request.url)
        try:
            match (request.method, path):
                case ("GET", "/connect"):
                    return await self.env.ASSETS.fetch(request)
                case ("GET", "/api/settings"):
                    user = await self.get_or_create_user(id_key.email)
                    return Response.from_json(
                        {
                            "email": user.email,
                            "liftosaur_set": bool(user.liftosaur_api_key),
                            "strava_connected": bool(user.strava_refresh_token),
                            "timezone": user.timezone,
                        }
                    )
                case ("POST", "/api/settings"):
                    user = await self.get_or_create_user(id_key.email)
                    return await self.handle_connect_settings(request, user, base)
                case ("GET", "/connect/strava"):
                    user = await self.get_or_create_user(id_key.email)
                    return self.handle_strava_start(user, base)
                case ("GET", "/connect/strava/callback"):
                    user = await self.get_or_create_user(id_key.email)
                    return await self.handle_strava_callback(request, user, base)
                case _:
                    return Response("Not Found", status=404)
        except Exception:
            logger.exception("Connect flow failed")
            return Response("Something went wrong", status=500)

    async def handle_connect_settings(
        self, request: Request, user: User, base: str
    ) -> Response:
        """Saves settings from JSON. Answers {"status": <code>} where the
        code is one the frontend maps to a message (saved, bad_key,
        bad_timezone)."""
        # Browsers always send Origin on POSTs; reject anything else
        # so another site can't submit this form with the user's session.
        if request.headers.get("origin") != base:
            return Response("Forbidden", status=403)
        try:
            body = await request.json()
        except Exception:
            return Response("Request body must be valid JSON", status=400)
        if not isinstance(body, dict):
            return Response("Request body must be a JSON object", status=400)
        liftosaur_api_key = str(body.get("liftosaur_api_key") or "").strip()
        timezone = str(body.get("timezone") or "").strip()

        def result(status: str, http: int = 200) -> Response:
            return Response.from_json({"status": status}, status=http)

        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            return result("bad_timezone", 422)
        if (
            liftosaur_api_key
            and not LiftosaurApiSource(liftosaur_api_key).health_check()
        ):
            return result("bad_key", 422)

        db = self.env.liftostrava_users_db
        await (
            db.prepare("UPDATE users SET timezone = ? WHERE id = ?")
            .bind(timezone, user.user_id)
            .run()
        )
        if liftosaur_api_key:
            await (
                db.prepare(
                    """
                    INSERT INTO credentials (user_id, liftosaur_api_key)
                    VALUES (?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        liftosaur_api_key = excluded.liftosaur_api_key,
                        updated_at = unixepoch()
                    """
                )
                .bind(user.user_id, await encrypt(liftosaur_api_key, self.aes_key()))
                .run()
            )
        return result("saved")

    def handle_strava_start(self, user: User, base: str) -> Response:
        client_id = self.env.STRAVA_CLIENT_ID
        if not isinstance(client_id, str):
            raise TypeError("STRAVA_CLIENT_ID is not configured")
        state = sign_state(user.user_id, self.secret_key(STATE_LABEL))
        return Response.redirect(
            build_authorize_url(client_id, f"{base}/connect/strava/callback", state)
        )

    async def handle_strava_callback(
        self, request: Request, user: User, base: str
    ) -> Response:
        params = parse_qs(urlparse(request.url).query)

        def back(status: str) -> Response:
            return Response.redirect(f"{base}/connect?status={status}", 303)

        if "error" in params:
            return back("strava_denied")
        state_user = verify_state(
            params.get("state", [""])[0], self.secret_key(STATE_LABEL)
        )
        if state_user != user.user_id:
            return back("bad_state")
        code = params.get("code", [""])[0]
        if not code:
            return back("strava_failed")
        if "activity:write" not in params.get("scope", [""])[0].split(","):
            return back("strava_scope")

        try:
            data = exchange_authorization_code(
                self.env.STRAVA_CLIENT_ID, self.env.STRAVA_CLIENT_SECRET, code
            )
            tokens = StravaTokens(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                expires_at=data["expires_at"],
            )
        except (requests.RequestException, KeyError):
            logger.exception("Strava token exchange failed")
            return back("strava_failed")
        await self.update_user_strava_tokens(user.user_id, tokens)
        return back("strava_connected")

    async def handle_post(self, request: Request, id_key: AccessIDKey) -> Response:
        try:
            body = await request.json()
        except Exception:
            return Response("Request body must be valid JSON", status=400)
        workout_id = body.get("workout_id") if isinstance(body, dict) else None
        if not isinstance(workout_id, (str, int)) or isinstance(workout_id, bool):
            return Response("'workout_id' is required", status=400)
        workout_id = str(workout_id)

        try:
            user = await self.get_user(id_key)
            if user is None or not user.has_credentials:
                return Response("User or credentials not found", status=404)

            if not user.liftosaur_api_key:
                return Response(
                    "Liftosaur API key is not configured; visit /connect", status=400
                )
            if not user.strava_refresh_token:
                return Response("Strava is not connected; visit /connect", status=400)

            workout_entry = LiftosaurApiSource(
                api_key=user.liftosaur_api_key
            ).get_workout(workout_id=workout_id)
            workout = workout_entry.workout

            # Strava's local-time display needs the user's own timezone.
            if user.timezone:
                workout.utc_offset = default_utc_offset(
                    workout.start_time, ZoneInfo(user.timezone)
                )

            # Reuse a still-valid token or refresh and persist the rotated pair.
            access_token = await self.get_strava_access_token(user)

            upload = upload_activity(access_token, workout, "WeightTraining")
            upload_id = upload["id"]

            logger.info("Upload accepted (id=%s), waiting for processing", upload_id)
            status = await poll_upload_async(access_token, upload_id)
            activity_id = status["activity_id"]

            logger.info("Muting activity %s (hide_from_home=true)", activity_id)
            set_muted(access_token, activity_id, True)

            return Response(f"Uploaded to Strava: {workout.name}!")

        except LookupError as e:
            return Response(str(e), status=404)
        except StravaUploadError as e:
            if "duplicate" in str(e).lower():
                return Response("Strava already has this workout", status=409)
            logger.exception("Strava rejected the upload")
            return Response("Sync failed (StravaUploadError)", status=500)
        except Exception as e:
            if isinstance(e, requests.HTTPError) and e.response is not None:
                logger.exception(
                    "Workout sync failed; upstream returned HTTP %s: %s",
                    e.response.status_code,
                    e.response.text,
                )
            else:
                logger.exception("Workout sync failed")
            # Details stay in the logs; callers only get the error class.
            return Response(f"Sync failed ({type(e).__name__})", status=500)

    async def get_strava_access_token(self, credentials: User) -> str:
        if not credentials.strava_refresh_token:
            raise RuntimeError("Strava is not connected for this user")

        if credentials.is_strava_access_token_valid():
            return cast(str, credentials.strava_access_token)

        refreshed_tokens = refresh_strava_tokens(
            self.env.STRAVA_CLIENT_ID,
            self.env.STRAVA_CLIENT_SECRET,
            credentials.strava_refresh_token,
        )

        await self.update_user_strava_tokens(credentials.user_id, refreshed_tokens)

        return refreshed_tokens.access_token

    async def handle_get(self, id_key: AccessIDKey, request: Request) -> Response:
        user = await self.get_user(id_key)
        if user is None:
            return Response.from_json({"error": "User not found"}, status=404)

        if not user.has_credentials or not user.liftosaur_api_key:
            return Response.from_json(
                {"error": "User does not have credentials"}, status=404
            )
        try:
            start, end = parse_history_range(
                parse_qs(urlparse(request.url).query), user.timezone
            )
        except HistoryRangeError as e:
            return Response.from_json({"error": str(e)}, status=400)

        try:
            workout_history = LiftosaurApiSource(
                api_key=user.liftosaur_api_key
            ).list_history(start_date=start, end_date=end)
        except requests.RequestException:
            logger.exception("Listing Liftosaur history failed")
            return Response.from_json(
                {"error": "Could not reach Liftosaur"}, status=502
            )
        serialised_workout_history = [
            {
                "id": workout.id,
                "name": workout.workout.name,
                "date": datetime.fromisoformat(workout.workout.start_time).strftime(
                    "%Y-%m-%d"
                ),
                "start_time": workout.workout.start_time,
                "duration_s": workout.workout.elapsed_time,
                "exercises": [
                    {"name": e.name, "sets": len(e.sets)}
                    for e in workout.workout.exercises
                ],
            }
            for workout in sorted(
                workout_history, key=lambda w: w.workout.start_time, reverse=True
            )
        ]
        return Response.from_json(serialised_workout_history)

    async def update_user_strava_tokens(
        self, user_id: str, tokens: StravaTokens
    ) -> None:
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
        key = self.aes_key()
        await (
            self.env.liftostrava_users_db.prepare(sql)
            .bind(
                user_id,
                await encrypt(tokens.access_token, key),
                await encrypt(tokens.refresh_token, key),
                tokens.expires_at,
            )
            .run()
        )
