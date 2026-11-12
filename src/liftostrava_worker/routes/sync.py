import logging
from zoneinfo import ZoneInfo

import requests
from workers import Request, Response

from liftostrava.errors import NotSyncedYet, StravaUploadError
from liftostrava.heart_rate import coverage_report, with_heart_rate
from liftostrava.liftosaur.client import LiftosaurClient
from liftostrava.service import DEFAULT_TIMEZONE, SyncService
from liftostrava_worker.context import AppContext
from liftostrava_worker.storage.models import AccessIDKey
from liftostrava_worker.storage.repository import D1TokenStore

logger = logging.getLogger(__name__)


async def handle_sync(
    request: Request, id_key: AccessIDKey, app: AppContext
) -> Response:
    try:
        body = await request.json()
    except Exception:
        return Response("Request body must be valid JSON", status=400)
    workout_id = body.get("workout_id") if isinstance(body, dict) else None
    if not isinstance(workout_id, (str, int)) or isinstance(workout_id, bool):
        return Response("'workout_id' is required", status=400)
    workout_id = str(workout_id)
    # Absent: today's upload without heart rate. Present: the heart-rate
    # path, which never silently falls back to uploading without it.
    has_heart_rate = "heart_rate" in body
    if has_heart_rate and not isinstance(body["heart_rate"], (list, dict)):
        return Response(
            "'heart_rate' must be a list of {time, bpm} or {time: [...], bpm: [...]}",
            status=400,
        )
    dry_run = body.get("dry_run") is True
    if dry_run and not has_heart_rate:
        return Response("'dry_run' needs 'heart_rate'", status=400)

    try:
        repo = app.repo
        user = await repo.get_user(id_key)
        if user is None or not user.has_credentials:
            return Response("User or credentials not found", status=404)

        if not user.liftosaur_api_key:
            return Response(
                "Liftosaur API key is not configured; visit /connect", status=400
            )
        if not user.strava_refresh_token:
            return Response("Strava is not connected; visit /connect", status=400)

        workout = LiftosaurClient(user.liftosaur_api_key).get_workout(workout_id)

        if dry_run:
            return Response.from_json(
                coverage_report(
                    body["heart_rate"], workout.start_time, workout.elapsed_time
                )
            )
        if has_heart_rate:
            workout = with_heart_rate(workout, body["heart_rate"])

        # Strava's local-time display needs the user's own timezone.
        tz = ZoneInfo(user.timezone) if user.timezone else DEFAULT_TIMEZONE
        service = SyncService(
            app.strava_oauth, D1TokenStore(repo, user), tz, progress=logger.info
        )
        await service.sync(workout)

        note = (
            " (no heart-rate samples in the workout window, so none attached)"
            if has_heart_rate and not workout.heart_rate
            else ""
        )
        return Response(f"Uploaded to Strava: {workout.name}!{note}")

    except NotSyncedYet as e:
        # 425, not 409: 409 means Strava already has the workout.
        return Response(str(e), status=425)
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
