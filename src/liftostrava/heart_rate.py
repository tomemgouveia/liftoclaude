"""Turning raw heart-rate samples (from the Shortcut's Health query) into
the samples a Workout carries, and checking they cover the workout. Pure
functions: no I/O, so the CLI and the Worker share them."""

import re
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


_LEADING_NUMBER = re.compile(r"\s*(\d+(?:\.\d+)?)")


def _number(value: object) -> float | None:
    """A bpm as a number. Shortcuts may send it as text, possibly with its
    unit ("72 count/min"), so take the leading number of a string."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = _LEADING_NUMBER.match(value)
        return float(match.group(1)) if match else None
    return None


def _parse_sample(raw: object) -> tuple[datetime, int] | None:
    """One raw `{"time": ..., "bpm": ...}` item, or None if it's unusable."""
    if not isinstance(raw, dict):
        return None
    time_value, bpm_value = raw.get("time"), _number(raw.get("bpm"))
    if not isinstance(time_value, str) or bpm_value is None:
        return None
    try:
        moment = parse_iso(time_value)
    except ValueError:
        return None
    bpm = round(bpm_value)
    if not MIN_BPM <= bpm <= MAX_BPM:
        return None
    return moment, bpm


def _as_list(value: object) -> list | None:
    """A list, or text holding one item per line (what Shortcuts sends when
    a list is coerced to text)."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    return None


def raw_items(raw_samples: object) -> list:
    """The samples as a list of `{"time", "bpm"}` items. Accepts that list
    directly, or parallel `{"time": ..., "bpm": ...}` lists of equal length
    (what a Shortcut can build without a loop); each may also be text with
    one value per line. Anything else is empty."""
    if isinstance(raw_samples, list):
        return raw_samples
    if isinstance(raw_samples, dict):
        times = _as_list(raw_samples.get("time"))
        bpms = _as_list(raw_samples.get("bpm"))
        if times is not None and bpms is not None and len(times) == len(bpms):
            return [{"time": t, "bpm": b} for t, b in zip(times, bpms, strict=True)]
    return []


def describe_shape(raw_samples: object) -> object:
    """The structure of what was sent, without its values, to explain a
    request that yielded no samples (for example unequal list lengths)."""

    def one(value: object) -> str:
        if isinstance(value, (list, str)):
            return f"{type(value).__name__}[{len(value)}]"
        return type(value).__name__

    if isinstance(raw_samples, dict):
        return {key: one(value) for key, value in raw_samples.items()}
    return one(raw_samples)


def workout_end(start_time: str, elapsed_time: int) -> datetime:
    return parse_iso(start_time) + timedelta(seconds=elapsed_time)


def window_samples(
    raw_samples: object, start_time: str, elapsed_time: int
) -> list[HeartRateSample]:
    """Valid samples inside [start, start + elapsed], oldest first, as
    offsets from the start. Invalid items are dropped, not errors."""
    start = parse_iso(start_time)
    end = workout_end(start_time, elapsed_time)
    parsed = [p for p in map(_parse_sample, raw_items(raw_samples)) if p is not None]
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
    items = raw_items(raw_samples)
    unusable = [item for item in items if _parse_sample(item) is None]
    return {
        "received": len(items),
        "shape": describe_shape(raw_samples),
        # Items we couldn't read (bad time or bpm), with a few examples to
        # show what the sender is actually producing.
        "unreadable": len(unusable),
        "unreadable_examples": [repr(item)[:80] for item in unusable[:3]],
        "samples_in_window": len(samples),
        "first_sample": format_utc(first) if first else None,
        "last_sample": format_utc(last) if last else None,
        "workout_start": format_utc(start),
        "workout_end": format_utc(end),
        "covers_workout": last is not None and last >= end - SYNC_TOLERANCE,
    }


def format_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
