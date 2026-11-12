"""The normalized shape of a workout: what the Liftosaur side
(liftosaur/) produces and the Strava side (strava/) consumes, independent
of how the data arrived — parsed from a REST API record or loaded from
the JSON file written after an MCP call."""

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class Set:
    reps: int
    weight: float
    unit: Literal["kg", "lb"] = "kg"


@dataclass(frozen=True)
class HeartRateSample:
    offset_s: int  # seconds since the workout's start_time
    bpm: int


@dataclass(frozen=True)
class Exercise:
    name: str
    sets: list[Set]


@dataclass(frozen=True)
class Workout:
    start_time: str  # ISO 8601, UTC, e.g. "2026-08-24T16:56:02Z"
    elapsed_time: int  # seconds
    exercises: list[Exercise]
    name: str | None = None
    description: str | None = None
    # Explicit seconds to add to start_time for Strava's local-time
    # display. Normally left unset so SyncService derives it from the
    # athlete's timezone.
    utc_offset: int | None = None
    # Samples inside the workout window, oldest first. Empty means "no
    # heart-rate data was supplied" and keeps the plain JSON upload.
    heart_rate: list[HeartRateSample] = field(default_factory=list)


@dataclass(frozen=True)
class WorkoutRecord:
    """A workout paired with the id it can be fetched by again."""

    id: str
    workout: Workout
