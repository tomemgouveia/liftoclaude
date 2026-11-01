"""The HTTP-calling half of the Strava upload flow: send the payload,
wait for Strava to finish processing it, and optionally mute it from the
home feed."""

import json
import time
import uuid

import requests

from liftostrava.models import Workout
from liftostrava.strava.payload import build_strava_payload

REQUEST_TIMEOUT_S = 30


class StravaUploadError(RuntimeError):
    """Strava processed the upload and reported an error (e.g. it is a
    duplicate of an existing activity)."""


def strava_form_fields(workout: Workout, sport_type: str) -> dict:
    """The non-file form fields sent with an upload — also used by
    cli/sync.py's --dry-run preview, so the two can't silently diverge.

    Falls back to a default name/description only when the workout truly
    has none (`None`), not merely an empty string — matching how a plain
    dict's `.get(key, default)` used to behave before Workout became a
    dataclass, which `x or default` would silently *not* preserve for an
    explicitly empty value."""
    return {
        "data_type": "json",
        "sport_type": sport_type,
        "name": workout.name if workout.name is not None else "Strength Workout",
        "description": workout.description if workout.description is not None else "",
    }


def upload_activity(access_token: str, workout: Workout, sport_type: str) -> dict:
    payload = build_strava_payload(workout)
    # Strava dedupes uploads by external_id (derived from the filename here):
    # a fixed name like "workout.json" makes a retry return the *cached*
    # result of a previous attempt instead of reprocessing new content —
    # and that includes a since-deleted activity, whose upload record
    # permanently reports no error and no activity_id (poll_upload just
    # times out against it). Deriving external_id from start_time alone
    # isn't enough since a retry of the same workout hits this too — use
    # a random component so every upload attempt gets its own record.
    filename = (
        f"liftosaur-{workout.start_time.replace(':', '')}-{uuid.uuid4().hex[:8]}.json"
    )
    files = {
        "file": (filename, json.dumps(payload), "application/json"),
    }
    data = strava_form_fields(workout, sport_type)
    resp = requests.post(
        "https://www.strava.com/api/v3/uploads",
        headers={"Authorization": f"Bearer {access_token}"},
        data=data,
        files=files,
        timeout=REQUEST_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_upload_status(access_token: str, upload_id: int) -> dict:
    """One status check. Raises if Strava reports a processing error;
    the upload is finished once the result has an `activity_id`. Split
    out so async callers (the worker) can drive their own non-blocking
    poll loop instead of poll_upload's time.sleep."""
    resp = requests.get(
        f"https://www.strava.com/api/v3/uploads/{upload_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=REQUEST_TIMEOUT_S,
    )
    resp.raise_for_status()
    status = resp.json()
    if status.get("error"):
        raise StravaUploadError(f"Strava upload failed: {status['error']}")
    return status


def upload_timeout_error(status: dict | None) -> TimeoutError:
    last_status = status.get("status") if status else None
    return TimeoutError(
        f"Upload didn't finish processing in time (last status: "
        f"{last_status!r}) — check strava.com manually, it may "
        f"still complete."
    )


def poll_upload(access_token: str, upload_id: int, timeout_s: float = 30) -> dict:
    # Starts unset rather than only being assigned inside the loop: with a
    # very small timeout_s the loop body can run zero times.
    status = None
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = fetch_upload_status(access_token, upload_id)
        if status.get("activity_id"):
            return status
        time.sleep(1)
    raise upload_timeout_error(status)


def set_muted(access_token: str, activity_id: int, muted: bool) -> None:
    resp = requests.put(
        f"https://www.strava.com/api/v3/activities/{activity_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        data={"hide_from_home": str(muted).lower()},
        timeout=REQUEST_TIMEOUT_S,
    )
    resp.raise_for_status()
