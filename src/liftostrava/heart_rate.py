"""Turning raw heart-rate samples (from the Shortcut's Health query) into
the samples a Workout carries, and checking they cover the workout. Pure
functions: no I/O, so the CLI and the Worker share them."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from liftostrava.domain import HeartRateSample, Workout
from liftostrava.errors import NotSyncedYet

# The latest sample may fall this long before the workout's end (the watch
# doesn't sample at the exact last second) without counting as "not synced".
SYNC_TOLERANCE = timedelta(seconds=60)

MIN_BPM = 30
MAX_BPM = 240


def parse_iso(value: str) -> datetime:
    """ISO 8601 -> aware UTC datetime. Raises ValueError for naive times:
    without an offset we can't tell which instant is meant."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"time has no UTC offset: {value!r}")
    return parsed.astimezone(UTC)


def _parse_sample(raw: object) -> tuple[datetime, int] | None:
    """One raw `{"time": ..., "bpm": ...}` item, or None if it's unusable."""
    if not isinstance(raw, dict):
        return None
    time_value, bpm_value = raw.get("time"), raw.get("bpm")
    if not isinstance(time_value, str) or isinstance(bpm_value, bool):
        return None
    try:
        moment = parse_iso(time_value)
        bpm = round(float(bpm_value))  # Shortcuts may send numbers as text
    except (TypeError, ValueError):
        return None
    if not MIN_BPM <= bpm <= MAX_BPM:
        return None
    return moment, bpm


def workout_end(start_time: str, elapsed_time: int) -> datetime:
    return parse_iso(start_time) + timedelta(seconds=elapsed_time)


def window_samples(
    raw_samples: object, start_time: str, elapsed_time: int
) -> list[HeartRateSample]:
    """Valid samples inside [start, start + elapsed], oldest first, as
    offsets from the start. Invalid items are dropped, not errors."""
    if not isinstance(raw_samples, list):
        return []
    start = parse_iso(start_time)
    end = workout_end(start_time, elapsed_time)
    parsed = [p for p in map(_parse_sample, raw_samples) if p is not None]
    inside = sorted((t, bpm) for t, bpm in parsed if start <= t <= end)
    return [HeartRateSample(int((t - start).total_seconds()), bpm) for t, bpm in inside]


def samples_for_workout(
    raw_samples: object, start_time: str, elapsed_time: int
) -> list[HeartRateSample]:
    """The samples to upload, or NotSyncedYet if they stop more than
    SYNC_TOLERANCE before the workout's end (or there are none)."""
    samples = window_samples(raw_samples, start_time, elapsed_time)
    end = workout_end(start_time, elapsed_time)
    if not samples:
        raise NotSyncedYet(
            f"No heart-rate samples found for the workout, which ended at "
            f"{end:%H:%M} UTC. Wait for the watch to sync and try again."
        )
    last = parse_iso(start_time) + timedelta(seconds=samples[-1].offset_s)
    if last < end - SYNC_TOLERANCE:
        raise NotSyncedYet(
            f"Heart-rate data only runs to {last:%H:%M} UTC, but the workout "
            f"ended at {end:%H:%M} UTC. Wait for the watch to sync and try again."
        )
    return samples


def with_heart_rate(workout: Workout, raw_samples: object) -> Workout:
    """The workout with its heart-rate samples attached, or NotSyncedYet."""
    return replace(
        workout,
        heart_rate=samples_for_workout(
            raw_samples, workout.start_time, workout.elapsed_time
        ),
    )


def coverage_report(raw_samples: object, start_time: str, elapsed_time: int) -> dict:
    """What the coverage check sees, without raising: for dry runs and for
    explaining a NotSyncedYet."""
    samples = window_samples(raw_samples, start_time, elapsed_time)
    start = parse_iso(start_time)
    end = workout_end(start_time, elapsed_time)
    first = start + timedelta(seconds=samples[0].offset_s) if samples else None
    last = start + timedelta(seconds=samples[-1].offset_s) if samples else None
    return {
        "samples_in_window": len(samples),
        "first_sample": format_utc(first) if first else None,
        "last_sample": format_utc(last) if last else None,
        "workout_start": format_utc(start),
        "workout_end": format_utc(end),
        "covers_workout": last is not None and last >= end - SYNC_TOLERANCE,
    }


def format_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
