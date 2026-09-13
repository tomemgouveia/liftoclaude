"""The HTTP-calling half of the Strava upload flow: send the payload,
wait for Strava to finish processing it, and optionally mute it from the
home feed."""

import json
import time
import uuid

import requests

from liftostrava.models import Workout
from liftostrava.strava.payload import build_strava_payload


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
    data = {
        "data_type": "json",
        "sport_type": sport_type,
        "name": workout.name or "Strength Workout",
        "description": workout.description or "",
    }
    resp = requests.post(
        "https://www.strava.com/api/v3/uploads",
        headers={"Authorization": f"Bearer {access_token}"},
        data=data,
        files=files,
    )
    resp.raise_for_status()
    return resp.json()


def poll_upload(access_token: str, upload_id: int, timeout_s: float = 30) -> dict:
    # Starts unset rather than only being assigned inside the loop: with a
    # very small timeout_s the loop body can run zero times, and the
    # TimeoutError below used to reference this while still unbound,
    # raising a bare NameError instead of the intended TimeoutError.
    status = None
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = requests.get(
            f"https://www.strava.com/api/v3/uploads/{upload_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        status = resp.json()
        if status.get("error"):
            raise RuntimeError(f"Strava upload failed: {status['error']}")
        if status.get("activity_id"):
            return status
        time.sleep(1)
    last_status = status.get("status") if status else None
    raise TimeoutError(
        f"Upload didn't finish processing in time (last status: "
        f"{last_status!r}) — check strava.com manually, it may "
        f"still complete."
    )


def set_muted(access_token: str, activity_id: int, muted: bool) -> None:
    resp = requests.put(
        f"https://www.strava.com/api/v3/activities/{activity_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        data={"hide_from_home": str(muted).lower()},
    )
    resp.raise_for_status()
