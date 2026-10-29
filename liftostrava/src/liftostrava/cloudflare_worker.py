from workers import WorkerEntrypoint, Response

from liftostrava.sources.liftosaur import LiftosaurSource
from liftostrava.strava.client import StravaClient
from liftostrava.strava.payload import build_strava_payload


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        if request.method != "POST":
            return Response("Method Not Allowed", status=405)

        try:
            # 1. Fetch latest workout session using LiftosaurSource
            liftosaur_source = LiftosaurSource(api_key=self.env.LIFTOSAUR_API_KEY)
            workout = liftosaur_source.get_latest_workout()

            # 2. Get a fresh Strava access token
            strava_client = StravaClient(
                client_id=self.env.STRAVA_CLIENT_ID,
                client_secret=self.env.STRAVA_CLIENT_SECRET,
                refresh_token=self.env.STRAVA_REFRESH_TOKEN,
            )
            access_token = strava_client.get_access_token()

            # 3. Transform Liftosaur workout into Strava payload model
            payload = build_strava_payload(workout)

            # 4. Upload to Strava API
            activity_result = strava_client.upload_activity(payload, access_token)

            return Response(f"Successfully uploaded '{workout.title}' to Strava!")

        except Exception as e:
            return Response(f"Sync failed: {str(e)}", status=500)
