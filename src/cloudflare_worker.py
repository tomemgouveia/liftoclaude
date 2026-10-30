import json
import logging
import time
from datetime import datetime, timedelta

import requests
from workers import Request, Response, WorkerEntrypoint

from liftostrava.sources.api import LiftosaurApiSource
from liftostrava.strava.client import poll_upload, set_muted, upload_activity

logger = logging.getLogger(__name__)
STRAVA_TOKEN_KEY = "strava-token-state"
STRAVA_REFRESH_THRESHOLD_SECONDS = 3600


class Default(WorkerEntrypoint):
    async def fetch(self, request: Request) -> Response:
        match request.method:
            case "POST":
                return await self.handle_post(request)
            case "GET":
                return await self.handle_get(request)
            case _:
                return Response("Method Not Allowed", status=405)

    async def handle_post(self, request: Request) -> Response:
        try:
            # 1. Fetch latest workout session using LiftosaurSource
            liftosaur_source = LiftosaurApiSource(api_key=self.env.LIFTOSAUR_API_KEY)

            body = await request.json()
            workout_id = body.get("workout_id")

            workout_entry = liftosaur_source.get_workout(workout_id=workout_id)

            # 2. Reuse a still-valid token or refresh and persist the rotated pair.
            access_token = await self.get_strava_access_token()

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

    async def get_strava_access_token(self) -> str:
        token_json = await self.env.STRAVA_TOKEN_STORE.get(STRAVA_TOKEN_KEY)
        if token_json is None:
            refresh_token = self.env.STRAVA_REFRESH_TOKEN
        else:
            token_state = json.loads(token_json)
            refresh_token = token_state["refresh_token"]
            if (
                token_state["expires_at"]
                > time.time() + STRAVA_REFRESH_THRESHOLD_SECONDS
            ):
                return token_state["access_token"]

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
        token_state = {
            "access_token": refreshed["access_token"],
            "refresh_token": refreshed["refresh_token"],
            "expires_at": refreshed["expires_at"],
        }
        await self.env.STRAVA_TOKEN_STORE.put(STRAVA_TOKEN_KEY, json.dumps(token_state))
        return token_state["access_token"]

    async def handle_get(self, request: Request) -> Response:
        api_source = LiftosaurApiSource(api_key=self.env.LIFTOSAUR_API_KEY)
        workout_history = api_source.list_history(
            start_date=datetime.today() - timedelta(days=5)
        )
        workout_history = [
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
        return Response(json.dumps(workout_history), status=200)
