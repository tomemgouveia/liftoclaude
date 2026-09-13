"""The normalized shape every WorkoutSource produces and everything in
strava/ consumes, independent of how the data arrived (today: a JSON file
written after an MCP call — see sources/mcp_export.py; later: a direct
Liftosaur REST API call)."""

from dataclasses import dataclass


@dataclass
class Set:
    reps: int
    weight_kg: float


@dataclass
class Exercise:
    name: str
    sets: list[Set]


@dataclass
class Workout:
    start_time: str  # ISO 8601, UTC, e.g. "2026-08-24T16:56:02Z"
    elapsed_time: int  # seconds
    exercises: list[Exercise]
    name: str | None = None
    description: str | None = None
    # Seconds to add to start_time for Strava's local-time display. Left
    # unset by default so strava/payload.py can compute it from
    # ATHLETE_TIMEZONE instead.
    utc_offset: int | None = None
