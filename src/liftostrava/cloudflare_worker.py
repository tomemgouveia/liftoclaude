import requests
from workers import Response, WorkerEntrypoint

# from sources.liftosaur import LiftosaurSource
# from strava.client import StravaClient
# from strava.payload import build_strava_payload


class Default(WorkerEntrypoint):
    async def fetch(self, request: requests.Request) -> Response:
        match request.method:
            case "POST":
                return await self.handle_post(request)
            case "GET":
                return await self.handle_get(request)
            case _:
                return Response("Method Not Allowed", status=405)

    async def handle_post(self, request: requests.Request) -> Response:
        try:
            # # 1. Fetch latest workout session using LiftosaurSource
            # liftosaur_source = LiftosaurSource(api_key=self.env.LIFTOSAUR_API_KEY)
            # workout = liftosaur_source.get_latest_workout()

            # # 2. Get a fresh Strava access token
            # strava_client = StravaClient(
            #     client_id=self.env.STRAVA_CLIENT_ID,
            #     client_secret=self.env.STRAVA_CLIENT_SECRET,
            #     refresh_token=self.env.STRAVA_REFRESH_TOKEN,
            # )
            # access_token = strava_client.get_access_token()

            # # 3. Transform Liftosaur workout into Strava payload model
            # payload = build_strava_payload(workout)

            # # 4. Upload to Strava API
            # activity_result = strava_client.upload_activity(payload, access_token)

            # return Response(f"Successfully uploaded '{workout.title}' to Strava!")
            return Response("Fake uploaded to Strava!")

        except Exception as e:
            return Response(f"Sync failed: {e!s}", status=500)

    async def handle_get(self, request: requests.Request) -> Response:

        return Response("Liftosaur -> Strava sync worker is alive!")
