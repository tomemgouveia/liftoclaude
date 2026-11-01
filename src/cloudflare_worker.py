import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

import requests
from workers import Request, Response, WorkerEntrypoint

from cloudflare import AccessIDKey, User, process_jwt
from liftostrava.sources.api import LiftosaurApiSource
from liftostrava.strava.auth import StravaTokens, refresh_strava_tokens
from liftostrava.strava.client import (
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


class Default(WorkerEntrypoint):
    async def fetch(self, request: Request) -> Response:
        id_key = await self.get_access_id_key(request)
        if id_key is None:
            return Response("Cloudflare Access authentication required", status=401)

        match request.method:
            case "POST":
                return await self.handle_post(request, id_key)
            case "GET":
                return await self.handle_get(id_key)
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
        return User(**row)

    async def handle_post(self, request: Request, id_key: AccessIDKey) -> Response:
        try:
            body = await request.json()
        except Exception:
            return Response("Request body must be valid JSON", status=400)
        workout_id = body.get("workout_id") if isinstance(body, dict) else None
        if not isinstance(workout_id, (str, int)) or isinstance(workout_id, bool):
            return Response("'workout_id' is required", status=400)
        workout_id = str(workout_id)
        force = isinstance(body, dict) and body.get("force") is True

        try:
            user = await self.get_user(id_key)
            if user is None or not user.has_credentials:
                return Response("User or credentials not found", status=404)

            if not user.liftosaur_api_key:
                return Response(
                    "Liftosaur API key is not configured for this user", status=400
                )

            if not force and await self.is_already_synced(user.user_id, workout_id):
                return Response(
                    "Workout was already synced; pass force=true to upload it again",
                    status=409,
                )

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

            await self.record_synced(user.user_id, workout_id, activity_id)

            return Response(f"Uploaded to Strava: {workout.name}!")

        except LookupError as e:
            return Response(str(e), status=404)
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

    async def is_already_synced(self, user_id: str, liftosaur_id: str) -> bool:
        query = (
            await self.env.liftostrava_users_db.prepare(
                "SELECT 1 FROM synced_workouts WHERE user_id = ? AND liftosaur_id = ?"
            )
            .bind(user_id, liftosaur_id)
            .run()
        )
        return bool(query.results)

    async def record_synced(
        self, user_id: str, liftosaur_id: str, activity_id: int
    ) -> None:
        await (
            self.env.liftostrava_users_db.prepare(
                """
                INSERT OR REPLACE INTO synced_workouts
                    (user_id, liftosaur_id, strava_activity_id)
                VALUES (?, ?, ?)
                """
            )
            .bind(user_id, liftosaur_id, activity_id)
            .run()
        )

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

    async def handle_get(self, id_key: AccessIDKey) -> Response:
        user = await self.get_user(id_key)
        if user is None:
            return Response.from_json({"error": "User not found"}, status=404)

        if not user.has_credentials or not user.liftosaur_api_key:
            return Response.from_json(
                {"error": "User does not have credentials"}, status=404
            )
        api_source = LiftosaurApiSource(api_key=user.liftosaur_api_key)

        workout_history = api_source.list_history(
            start_date=datetime.now(UTC) - timedelta(days=5)
        )
        serialised_workout_history = [
            {
                "id": workout.id,
                "name": workout.workout.name,
                "date": datetime.fromisoformat(workout.workout.start_time).strftime(
                    "%Y-%m-%d"
                ),
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
            UPDATE credentials
            SET strava_access_token = ?,
                strava_refresh_token = ?,
                strava_expires_at = ?,
                updated_at = unixepoch()
            WHERE user_id = ?
            """
        await (
            self.env.liftostrava_users_db.prepare(sql)
            .bind(tokens.access_token, tokens.refresh_token, tokens.expires_at, user_id)
            .run()
        )
