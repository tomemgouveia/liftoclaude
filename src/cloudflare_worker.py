import json
from datetime import datetime, timedelta

from workers import Request, Response, WorkerEntrypoint

from liftostrava.sources.api import LiftosaurApiSource
from liftostrava.strava.payload import build_strava_payload

# from strava.client import StravaClient


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

            # # 2. Get a fresh Strava access token
            # strava_client = StravaClient(
            #     client_id=self.env.STRAVA_CLIENT_ID,
            #     client_secret=self.env.STRAVA_CLIENT_SECRET,
            #     refresh_token=self.env.STRAVA_REFRESH_TOKEN,
            # )
            # access_token = strava_client.get_access_token()

            # 3. Transform Liftosaur workout into Strava payload model
            payload = build_strava_payload(workout_entry.workout)

            # # 4. Upload to Strava API
            # activity_result = strava_client.upload_activity(payload, access_token)

            # return Response(f"Successfully uploaded '{workout.title}' to Strava!")
            return Response(f"Fake uploaded to Strava: {payload}!")

        except Exception as e:
            return Response(f"Sync failed: {e!s}", status=500)

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
