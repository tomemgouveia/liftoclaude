"""A WorkoutSource backed directly by Liftosaur's REST API — no MCP tool,
no agent-transcribed JSON file, no `workouts/` scratch file. Requires
Liftosaur Premium and an API key generated at Settings -> API Keys,
supplied via the LIFTOSAUR_API_KEY environment variable.

`GET /api/v1/history/:id` returns the workout as a "text" field containing
the exact same Liftohistory text format the MCP `get_history`/
`get_history_record` tools return — see sources/liftohistory.py, the
actual parser, which this module just feeds.

There is no `GET /api/v1/history/:id` endpoint, so a single record is
found by scanning `GET /api/v1/history`, which returns the full list, paged
via `cursor`/`hasMore`/`nextCursor` and optionally restricted to a
`startDate`/`endDate` range — see list_history() below. Response shapes
confirmed against https://www.liftosaur.com/doc/api on 2026-09-13.
"""

from collections.abc import Iterator
from datetime import datetime

import requests

from liftostrava.sources.base import WorkoutEntry
from liftostrava.sources.liftohistory import parse_liftohistory

API_BASE = "https://www.liftosaur.com/api/v1"
REQUEST_TIMEOUT_S = 30


class LiftosaurApiSource:
    def __init__(self, api_key: str):
        self.api_key = api_key
        if not self.api_key:
            raise RuntimeError(
                "LIFTOSAUR_API_KEY is not set. Generate one at "
                "Settings -> API Keys in the Liftosaur app (requires "
                "Premium), then add it to .env — see .env.example."
            )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def health_check(self) -> bool:
        """True if the API key is accepted. A rejected key (401/403)
        returns False; network failures and other errors propagate so
        they aren't mistaken for a bad key."""
        response = requests.get(
            f"{API_BASE}/history", headers=self._headers(), timeout=REQUEST_TIMEOUT_S
        )
        if response.status_code in (401, 403):
            return False
        response.raise_for_status()
        return True

    def _iter_records(
        self,
        start_date: datetime | str | None = None,
        end_date: datetime | str | None = None,
    ) -> Iterator[dict]:
        """Yield raw history records, lazily following the API's
        `cursor`/`hasMore` pagination so callers can stop early."""

        def _parse_date(date: datetime | str) -> str:
            if isinstance(date, datetime):
                return date.isoformat()
            return date

        params = {}
        if start_date:
            params["startDate"] = _parse_date(start_date)
        if end_date:
            params["endDate"] = _parse_date(end_date)

        cursor: str | None = None
        while True:
            page_params = dict(params)
            if cursor:
                page_params["cursor"] = cursor
            resp = requests.get(
                f"{API_BASE}/history",
                headers=self._headers(),
                params=page_params,
                timeout=REQUEST_TIMEOUT_S,
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            yield from data["records"]
            if not data.get("hasMore"):
                return
            cursor = str(data["nextCursor"])

    def list_history(
        self,
        start_date: datetime | str | None = None,
        end_date: datetime | str | None = None,
    ) -> list[WorkoutEntry]:
        """List every workout in Liftosaur's history, newest first,
        optionally restricted to a `[start_date, end_date]` range (either
        end may be omitted). Returns a list of WorkoutEntry objects.
        """
        return [
            WorkoutEntry(
                id=str(record["id"]), workout=parse_liftohistory(record["text"])
            )
            for record in self._iter_records(start_date, end_date)
        ]

    def get_workout(self, workout_id: str) -> WorkoutEntry:
        """The API has no get-by-id endpoint, so scan the (newest-first)
        history and stop at the match — only that record is parsed."""
        for record in self._iter_records():
            if str(record["id"]) == str(workout_id):
                return WorkoutEntry(
                    id=str(record["id"]),
                    workout=parse_liftohistory(record["text"]),
                )
        raise LookupError(f"Workout {workout_id!r} was not found in history")
