"""The JSON bridge for workouts pulled over the Liftosaur MCP server.

MCP tools are only reachable from inside the agent, not from this Python
code, so the agent (see the sync-to-strava skill) transcribes a record
into a small JSON file — shape in tests/fixtures/sample_workout.json —
and the CLI loads it from here. This is the route for when no
LIFTOSAUR_API_KEY is configured; with a key, liftosaur/client.py reads
the same data directly.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from liftostrava.domain import Exercise, Set, Workout, WorkoutRecord


def _parse_utc(iso: str) -> datetime:
    """A naive result (no time-of-day given, e.g. "2026-09-01") is
    assumed UTC, matching every workout's start_time being UTC — so it
    can always be compared against an aware datetime."""
    dt = datetime.fromisoformat(iso)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def load_workout(path: str | Path) -> Workout:
    with open(path) as f:
        data = json.load(f)

    exercises = [
        Exercise(
            name=exercise["name"],
            sets=[Set(reps=s["reps"], weight=s["weight_kg"]) for s in exercise["sets"]],
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


def list_exported(
    directory: str | Path,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[WorkoutRecord]:
    """List the `.json` workouts in `directory` (the skill's `workouts/`
    scratch space), newest first, optionally restricted to a
    `[start_date, end_date]` range (inclusive; either end may be omitted).
    A record's `id` is its file path, which `load_workout` takes.

    `start_date`/`end_date` must be ISO 8601 date or datetime strings
    (`datetime.fromisoformat`-compatible). A date with no time-of-day
    (e.g. "2026-09-01") is treated as UTC midnight, matching every
    workout's start_time being UTC.
    """
    lo = _parse_utc(start_date) if start_date else None
    hi = _parse_utc(end_date) if end_date else None

    records = []
    for path in Path(directory).glob("*.json"):
        workout = load_workout(path)
        when = _parse_utc(workout.start_time)
        if lo is not None and when < lo:
            continue
        if hi is not None and when > hi:
            continue
        records.append(WorkoutRecord(id=str(path), workout=workout))

    records.sort(key=lambda r: r.workout.start_time, reverse=True)
    return records
