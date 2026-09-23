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

import os

import requests

from liftostrava.models import Workout
from liftostrava.sources.base import WorkoutEntry
from liftostrava.sources.liftohistory import parse_liftohistory

API_BASE = "https://www.liftosaur.com/api/v1"


def _require_api_key() -> str:
    api_key = os.getenv("LIFTOSAUR_API_KEY")
    if not api_key:
        raise RuntimeError(
            "LIFTOSAUR_API_KEY is not set. Generate one at "
            "Settings -> API Keys in the Liftosaur app (requires "
            "Premium), then add it to .env — see .env.example."
        )
    return api_key


class LiftosaurApiSource:
    def __init__(self, record_id: str):
        self.record_id = record_id

    def load(self) -> Workout:
        api_key = _require_api_key()
        resp = requests.get(
            f"{API_BASE}/history/{self.record_id}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        text = resp.json()["data"]["text"]
        return parse_liftohistory(text)

    @staticmethod
    def list_history(
        start_date: str | None = None, end_date: str | None = None
    ) -> list[WorkoutEntry]:
        """List every workout in Liftosaur's history, newest first,
        optionally restricted to a `[start_date, end_date]` range (either
        end may be omitted) — following the API's `cursor`/`hasMore`
        pagination (up to 200 records/page) internally so the caller
        always gets the complete, already-parsed range in one call.

        `start_date`/`end_date` are passed straight through to the API
        as its `startDate`/`endDate` query params — an ISO date/datetime
        string or a unix timestamp, per its own docs; unlike
        McpExportSource.list_history, no local date parsing happens here.
        """
        api_key = _require_api_key()
        headers = {"Authorization": f"Bearer {api_key}"}
        params = {}
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date

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
                    identifier=str(record["id"]),
                    workout=parse_liftohistory(record["text"]),
                )
                for record in data["records"]
            )
            if not data.get("hasMore"):
                break
            cursor = str(data["nextCursor"])
        return entries
