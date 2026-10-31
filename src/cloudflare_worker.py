import json
import logging
import time

# from datetime import datetime, timedelta
from typing import Any

import requests
from workers import Request, Response, WorkerEntrypoint, fetch

from liftostrava.sources.api import LiftosaurApiSource
from liftostrava.strava.client import poll_upload, set_muted, upload_activity

logger = logging.getLogger(__name__)
STRAVA_REFRESH_THRESHOLD_SECONDS = 3600


class Default(WorkerEntrypoint):
    async def fetch(self, request: Request) -> Response:
        email = await self.get_authenticated_email(request)
        if email is None:
            return Response("Cloudflare Access authentication required", status=401)

        match request.method:
            case "POST":
                return await self.handle_post(request, email)
            case "GET":
                return await self.handle_get_2(email)
            case _:
                return Response("Method Not Allowed", status=405)

    async def get_authenticated_email(self, request: Request) -> str | None:
        cookie_header = request.headers.get("cookie", "")
        access_cookie = None
        for cookie in cookie_header.split(";"):
            name, separator, value = cookie.strip().partition("=")
            if name == "CF_Authorization" and separator and value.strip():
                access_cookie = value.strip()
                break

        if access_cookie is None:
            logger.warning("No CF_Authorization cookie found in request headers")
            return None

        try:
            response = await fetch(
                f"https://{self.env.CF_ACCESS_TEAM_DOMAIN.rstrip('/')}/cdn-cgi/access/get-identity",
                headers={"Cookie": f"CF_Authorization={access_cookie}"},
            )
            response.raise_for_status()
            identity = json.loads(await response.text())
        except (OSError, ValueError, requests.RequestException):
            logger.warning("Cloudflare Access identity lookup failed")
            return None

        if not isinstance(identity, dict):
            logger.warning("Cloudflare Access returned an invalid identity response")
            return None

        email = identity.get("email")
        if not isinstance(email, str) or not email.strip():
            logger.warning("Cloudflare Access identity did not contain an email")
            return None
        return email.strip().lower()

    async def get_user_credentials(self, email: str) -> dict[str, Any] | None:
        query = (
            await self.env.liftostrava_users_db.prepare("""
            SELECT
                u.id AS user_id,
                u.email,
                u.name,
                c.liftosaur_api_key,
                c.strava_refresh_token,
                c.strava_access_token,
                c.strava_expires_at
            FROM users AS u
            JOIN credentials AS c ON c.user_id = u.id
            WHERE lower(u.email) = ?
            """)
            .bind(email)
            .run()
        )

        if not query.results:
            return None
        return query.results[0]

    async def handle_post(self, request: Request, email: str) -> Response:
        try:
            credentials = await self.get_user_credentials(email)
            if credentials is None:
                return Response("User or credentials not found", status=404)

            # 1. Fetch latest workout session using LiftosaurSource
            liftosaur_source = LiftosaurApiSource(
                api_key=credentials["liftosaur_api_key"]
            )

            body = await request.json()
            workout_id = body.get("workout_id")

            workout_entry = liftosaur_source.get_workout(workout_id=workout_id)

            # 2. Reuse a still-valid token or refresh and persist the rotated pair.
            access_token = await self.get_strava_access_token(credentials)

            # 4. Upload to Strava API
            upload = upload_activity(
                access_token, workout_entry.workout, "WeightTraining"
            )
            upload_id = upload["id"]

            print(
                f"Upload accepted (id={upload_id}), waiting for Strava to process it..."
            )
            status = poll_upload(access_token, upload_id)
            activity_id = status["activity_id"]

            print("Muting activity from home feed (hide_from_home=true)...")
            set_muted(access_token, activity_id, True)

            # return Response(f"Successfully uploaded '{workout.title}' to Strava!")
            return Response(f"Uploaded to Strava: {workout_entry.workout.name}!")

        except Exception as e:
            if isinstance(e, requests.HTTPError) and e.response is not None:
                logger.exception(
                    "Workout sync failed; upstream returned HTTP %s: %s",
                    e.response.status_code,
                    e.response.text,
                )
            else:
                logger.exception("Workout sync failed")
            return Response(
                f"Sync failed ({type(e).__name__}): {e!s}",
                status=500,
            )

    async def get_strava_access_token(self, credentials: dict[str, Any]) -> str:
        access_token = credentials["strava_access_token"]
        refresh_token = credentials["strava_refresh_token"]
        expires_at = credentials["strava_expires_at"]
        if not refresh_token:
            raise RuntimeError("Strava is not connected for this user")
        if (
            access_token
            and expires_at
            and expires_at > time.time() + STRAVA_REFRESH_THRESHOLD_SECONDS
        ):
            return access_token

        # Match the synchronous requests client used by the other API calls.
        response = requests.post(  # noqa: ASYNC210
            "https://www.strava.com/oauth/token",
            data={
                "client_id": self.env.STRAVA_CLIENT_ID,
                "client_secret": self.env.STRAVA_CLIENT_SECRET,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        response.raise_for_status()
        refreshed = response.json()
        await (
            self.env.liftostrava_users_db.prepare("""
                UPDATE credentials
                SET strava_access_token = ?,
                    strava_refresh_token = ?,
                    strava_expires_at = ?,
                    updated_at = unixepoch()
                WHERE user_id = ?
                """)
            .bind(
                refreshed["access_token"],
                refreshed["refresh_token"],
                refreshed["expires_at"],
                credentials["user_id"],
            )
            .run()
        )
        return refreshed["access_token"]

    # async def handle_get(self, _request: Request, email: str) -> Response:
    #     credentials = await self.get_user_credentials(email)
    #     if credentials is None:
    #         return Response("User or credentials not found", status=404)

    #     api_source = LiftosaurApiSource(api_key=credentials["liftosaur_api_key"])
    #     workout_history = api_source.list_history(
    #         start_date=datetime.today() - timedelta(days=5)
    #     )
    #     workout_history = [
    #         {
    #             "id": workout.id,
    #             "name": workout.workout.name,
    #             "date": datetime.fromisoformat(workout.workout.start_time).strftime(
    #                 "%Y-%m-%d"
    #             ),
    #         }
    #         for workout in sorted(
    #             workout_history, key=lambda w: w.workout.start_time, reverse=True
    #         )
    #     ]
    #     return Response.from_json(workout_history)

    async def handle_get_2(self, email: str) -> Response:
        query = (
            await self.env.liftostrava_users_db.prepare("""
            SELECT
                u.id AS user_id,
                u.email,
                u.name,
                c.liftosaur_api_key IS NOT NULL AS has_liftosaur_key,
                c.strava_refresh_token IS NOT NULL AS has_strava_refresh_token,
                c.strava_access_token IS NOT NULL AS has_strava_access_token
            FROM users AS u
            LEFT JOIN credentials AS c ON c.user_id = u.id
            WHERE lower(u.email) = ?
            """)
            .bind(email)
            .run()
        )

        if not query.results:
            return Response.from_json({"error": "User not found"}, status=404)

        user = query.results[0]
        return Response.from_json(
            {
                "user_id": user["user_id"],
                "email": user["email"],
                "name": user["name"],
                "has_liftosaur_key": bool(user["has_liftosaur_key"]),
                "has_strava_refresh_token": bool(user["has_strava_refresh_token"]),
                "has_strava_access_token": bool(user["has_strava_access_token"]),
            }
        )
