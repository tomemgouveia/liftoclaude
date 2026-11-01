import logging
from datetime import datetime, timedelta
from typing import cast

import requests
from workers import Request, Response, WorkerEntrypoint

from cloudflare import AccessIDKey, User, process_jwt
from liftostrava.sources.api import LiftosaurApiSource
from liftostrava.strava.auth import StravaTokens, refresh_strava_tokens
from liftostrava.strava.client import poll_upload, set_muted, upload_activity

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
        return User(**query.results[0])

    async def handle_post(self, request: Request, id_key: AccessIDKey) -> Response:
        try:
            credentials = await self.get_user(id_key)
            if credentials is None or not credentials.has_credentials:
                return Response("User or credentials not found", status=404)

            if not credentials.liftosaur_api_key:
                return Response(
                    "Liftosaur API key is not configured for this user", status=400
                )

            # 1. Fetch latest workout session using LiftosaurSource
            liftosaur_source = LiftosaurApiSource(api_key=credentials.liftosaur_api_key)

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
            start_date=datetime.today() - timedelta(days=5)
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
