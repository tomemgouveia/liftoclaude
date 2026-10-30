"""A WorkoutSource backed directly by Liftosaur's REST API — no MCP tool,
no agent-transcribed JSON file, no `workouts/` scratch file. Requires
Liftosaur Premium and an API key generated at Settings -> API Keys,
supplied via the LIFTOSAUR_API_KEY environment variable.

`GET /api/v1/history/:id` returns the workout as a "text" field containing
the exact same Liftohistory text format the MCP `get_history`/
`get_history_record` tools return — see sources/liftohistory.py, the
actual parser, which this module just feeds.

`GET /api/v1/history` (no id) is the same, but for the full list, paged
via `cursor`/`hasMore`/`nextCursor` and optionally restricted to a
`startDate`/`endDate` range — see list_history() below. Response shapes
confirmed against https://www.liftosaur.com/doc/api on 2026-09-13.
"""

from datetime import datetime

import requests

from liftostrava.sources.base import WorkoutEntry
from liftostrava.sources.liftohistory import parse_liftohistory

API_BASE = "https://www.liftosaur.com/api/v1"


class LiftosaurApiSource:
    def __init__(self, api_key: str):
        self.api_key = api_key
        if not self.api_key:
            raise RuntimeError(
                "LIFTOSAUR_API_KEY is not set. Generate one at "
                "Settings -> API Keys in the Liftosaur app (requires "
                "Premium), then add it to .env — see .env.example."
            )

    def health_check(self) -> bool:
        """Check if the API key is valid by making a simple request."""
        try:
            response = requests.get(
                f"{API_BASE}/history",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
            return True
        except requests.RequestException:
            return False

    def list_history(
        self,
        start_date: datetime | str | None = None,
        end_date: datetime | str | None = None,
    ) -> list[WorkoutEntry]:
        """List every workout in Liftosaur's history, newest first,
        optionally restricted to a `[start_date, end_date]` range (either
        end may be omitted) — following the API's `cursor`/`hasMore`
        pagination. Returns a list of WorkoutEntry objects.
        """

        def _parse_date(date: datetime | str) -> str:
            if isinstance(date, datetime):
                return date.isoformat()
            return date

        params = {}
        if start_date:
            params["startDate"] = _parse_date(start_date)
        if end_date:
            params["endDate"] = _parse_date(end_date)

        headers = {"Authorization": f"Bearer {self.api_key}"}

        entries = []
        cursor: str | None = None
        while True:
            page_params = dict(params)
            if cursor:
                page_params["cursor"] = cursor
            resp = requests.get(
                f"{API_BASE}/history", headers=headers, params=page_params
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            entries.extend(
                WorkoutEntry(
                    id=str(record["id"]),
                    workout=parse_liftohistory(record["text"]),
                )
                for record in data["records"]
            )
            if not data.get("hasMore"):
                break
            cursor = str(data["nextCursor"])
        return entries

    def get_workout(self, workout_id: str) -> WorkoutEntry:
        response = requests.get(
            f"{API_BASE}/history/",
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30,
        )
        response.raise_for_status()
        record = next(
            (
                record
                for record in response.json()["data"]["records"]
                if str(record["id"]) == str(workout_id)
            ),
            None,
        )
        if record is None:
            entry = next(
                (entry for entry in self.list_history() if entry.id == str(workout_id)),
                None,
            )
            if entry is None:
                raise LookupError(f"Workout {workout_id!r} was not found in history")
            return entry

        return WorkoutEntry(
            id=str(record["id"]),
            workout=parse_liftohistory(record["text"]),
        )
