"""The HTTP-calling half of the Strava upload flow: send the payload,
wait for Strava to finish processing it, and optionally mute it from the
home feed."""

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable

import requests

from liftostrava.domain import Workout
from liftostrava.errors import StravaUploadError
from liftostrava.strava.payload import build_payload, upload_form_fields

API_BASE = "https://www.strava.com/api/v3"
REQUEST_TIMEOUT_S = 30
UPLOAD_POLL_TIMEOUT_S = 30


class StravaClient:
    def __init__(self, access_token: str):
        self.access_token = access_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def upload(self, workout: Workout, utc_offset: int) -> int:
        """Send the workout; returns the upload id to wait on."""
        payload = build_payload(workout, utc_offset)
        # Strava dedupes uploads by external_id (derived from the filename
        # here): a fixed name like "workout.json" makes a retry return the
        # *cached* result of a previous attempt instead of reprocessing new
        # content — and that includes a since-deleted activity, whose
        # upload record permanently reports no error and no activity_id
        # (wait_for_upload just times out against it). Deriving external_id
        # from start_time alone isn't enough since a retry of the same
        # workout hits this too — use a random component so every upload
        # attempt gets its own record.
        filename = (
            f"liftosaur-{workout.start_time.replace(':', '')}"
            f"-{uuid.uuid4().hex[:8]}.json"
        )
        resp = requests.post(
            f"{API_BASE}/uploads",
            headers=self._headers(),
            data=upload_form_fields(workout),
            files={"file": (filename, json.dumps(payload), "application/json")},
            timeout=REQUEST_TIMEOUT_S,
        )
        resp.raise_for_status()
        return resp.json()["id"]

    def upload_status(self, upload_id: int) -> dict:
        """One status check. Raises if Strava reports a processing error;
        the upload is finished once the result has an `activity_id`."""
        resp = requests.get(
            f"{API_BASE}/uploads/{upload_id}",
            headers=self._headers(),
            timeout=REQUEST_TIMEOUT_S,
        )
        resp.raise_for_status()
        status = resp.json()
        if status.get("error"):
            raise StravaUploadError(f"Strava upload failed: {status['error']}")
        return status

    async def wait_for_upload(
        self,
        upload_id: int,
        timeout_s: float = UPLOAD_POLL_TIMEOUT_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> int:
        """Poll until Strava has processed the upload; returns the new
        activity id. Async so the worker's event loop isn't blocked."""
        # Starts unset rather than only being assigned inside the loop:
        # with a very small timeout_s the loop body can run zero times.
        status = None
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            status = self.upload_status(upload_id)
            if status.get("activity_id"):
                return status["activity_id"]
            await sleep(1)
        last_status = status.get("status") if status else None
        raise TimeoutError(
            f"Upload didn't finish processing in time (last status: "
            f"{last_status!r}) — check strava.com manually, it may "
            f"still complete."
        )

    def get_activity(self, activity_id: int) -> dict:
        """Fetch an activity as Strava's JSON (GET /activities/{id}).
        Needs the `activity:read_all` scope to see activities that are
        private or hidden from the home feed."""
        resp = requests.get(
            f"{API_BASE}/activities/{activity_id}",
            headers=self._headers(),
            timeout=REQUEST_TIMEOUT_S,
        )
        resp.raise_for_status()
        return resp.json()

    def set_hide_from_home(self, activity_id: int, hidden: bool) -> None:
        resp = requests.put(
            f"{API_BASE}/activities/{activity_id}",
            headers=self._headers(),
            data={"hide_from_home": str(hidden).lower()},
            timeout=REQUEST_TIMEOUT_S,
        )
        resp.raise_for_status()
