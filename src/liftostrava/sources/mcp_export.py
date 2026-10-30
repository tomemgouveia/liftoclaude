"""Today's only WorkoutSource: the JSON file written into workouts/ after
fetching a record over the Liftosaur MCP server (see CLAUDE.md in the repo
root, which drives that fetch-and-write step — this module only parses the
result).

Expected shape (already filtered to completed/actual sets only — CLAUDE.md
is responsible for dropping `warmup:`/`target:` sets before this file is
written, not this module):

    {
      "name": "Fierce 5 - Workout A",
      "start_time": "2026-08-24T16:56:02Z",
      "elapsed_time": 1868,
      "utc_offset": 3600,               // optional
      "description": "optional free text",
      "exercises": [
        {"name": "Squat", "sets": [{"reps": 5, "weight_kg": 60}, ...]},
        ...
      ]
    }
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from liftostrava.config import WORKOUTS_DIR
from liftostrava.models import Exercise, Set, Workout
from liftostrava.sources.base import WorkoutEntry


def _parse_utc(iso: str) -> datetime:
    """A naive result (no time-of-day given, e.g. "2026-09-01") is
    assumed UTC, matching every workout's start_time being UTC — so it
    can always be compared against an aware datetime."""
    dt = datetime.fromisoformat(iso)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class McpExportSource:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> Workout:
        with open(self.path) as f:
            data = json.load(f)

        exercises = [
            Exercise(
                name=exercise["name"],
                sets=[
                    Set(reps=s["reps"], weight=s["weight_kg"]) for s in exercise["sets"]
                ],
            )
            for exercise in data["exercises"]
        ]
        return Workout(
            start_time=data["start_time"],
            elapsed_time=data["elapsed_time"],
            exercises=exercises,
            name=data.get("name"),
            description=data.get("description"),
            utc_offset=data.get("utc_offset"),
        )

    @staticmethod
    def list_history(
        start_date: str | None = None,
        end_date: str | None = None,
        directory: str | Path = WORKOUTS_DIR,
    ) -> list[WorkoutEntry]:
        """List the workouts already sitting in `directory` (by default
        CLAUDE.md's `workouts/` scratch space) as `.json` files, newest
        first, optionally restricted to a `[start_date, end_date]` range
        (inclusive; either end may be omitted).

        There's no Liftosaur MCP client in this codebase to query for a
        broader/live list — MCP tools are only reachable from inside the
        agent, not from this Python code — so this is the closest
        equivalent for this source: the workouts CLAUDE.md has already
        pulled from Liftosaur and written to disk, not yet deleted after
        a successful sync (see cli/sync.py's docstring and CLAUDE.md).

        `start_date`/`end_date` must be ISO 8601 date or datetime strings
        (`datetime.fromisoformat`-compatible) — unlike
        LiftosaurApiSource.list_history, unix timestamps aren't accepted,
        since filtering happens locally here rather than server-side. A
        date with no time-of-day (e.g. "2026-09-01") is treated as UTC
        midnight, matching every workout's start_time being UTC.
        """
        lo = _parse_utc(start_date) if start_date else None
        hi = _parse_utc(end_date) if end_date else None

        entries = []
        for path in Path(directory).glob("*.json"):
            workout = McpExportSource(path).load()
            when = _parse_utc(workout.start_time)
            if lo is not None and when < lo:
                continue
            if hi is not None and when > hi:
                continue
            entries.append(WorkoutEntry(identifier=str(path), workout=workout))

        entries.sort(key=lambda e: e.workout.start_time, reverse=True)
        return entries
