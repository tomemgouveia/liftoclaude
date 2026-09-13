"""Pure parser for Liftohistory — the human-readable text format Liftosaur
uses for workout history records, returned as-is by the MCP `get_history`/
`get_history_record` tools' `text` field *and* by the REST API's
`GET /api/v1/history(/:id)` (see sources/api.py, the only caller of this
module). No I/O here, so it's unit-testable directly against real records.

Example record (from `get_liftohistory_reference`):

    2026-02-28T10:45:30Z / program: "5/3/1 For Beginners" / dayName: "Push Day" / week: 1 / dayInWeek: 5 / duration: 1235s / exercises: {
      // Optional exercise note
      Bench Press, Barbell / 3x8 185lb @7, 1x6 185lb @9 / warmup: 1x10 95lb, 1x5 135lb / target: 3x8-12 185lb @8 90s
      OHP / 3x10 95lb / target: 3x10 95lb 60s
      Pull Ups / 3x8|7 0lb / target: 3x10 0lb 60s
    }

Real records from `get_history` use a slightly different (but equally
`datetime.fromisoformat`-parseable) date form: "2026-09-11 17:30:05 +00:00"
instead of "2026-02-28T10:45:30Z" — both are handled.

Known, documented limitation: the header is split on " / " (space-slash-
space), which is safe because no real program/dayName value seen so far
contains that exact substring (bare slashes like "5/3/1" or "L/S/U" are
fine, since they aren't surrounded by spaces) — but a program or dayName
that *did* contain literal " / " would break the header split. Not worth
guarding against given real data never hits it.
"""

import re
from datetime import UTC, datetime
from typing import Literal

from liftostrava.models import Exercise, Set, Workout

# "2x8 42.5kg", "3x8|7 0lb", "1x5+ 185lb", "3x8 185lb @7" — count x reps,
# optional "+" (AMRAP, ignored), optional "|N" (unilateral second-side
# count, ignored per the decision to only take the first number), weight,
# unit, optional trailing "@RPE" (ignored).
SET_GROUP_RE = re.compile(
    r"^(?P<count>\d+)x(?P<reps>\d+)\+?(?:\|\d+)?\s+"
    r"(?P<weight>\d+(?:\.\d+)?)(?P<unit>kg|lb)(?:\s*@\S+)?$"
)


def _parse_header_fields(segments: list[str]) -> dict[str, str]:
    fields = {}
    for segment in segments:
        key, _, value = segment.partition(":")
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        fields[key.strip()] = value
    return fields


def _parse_set_groups(segment: str) -> list[Set]:
    sets = []
    for group in segment.split(", "):
        match = SET_GROUP_RE.match(group.strip())
        if not match:
            raise ValueError(f"Unrecognized set group: {group!r}")
        count = int(match.group("count"))
        reps = int(match.group("reps"))
        weight = float(match.group("weight"))
        # The regex's (kg|lb) alternation guarantees this, but the match
        # group's static type is plain str.
        unit: Literal["kg", "lb"] = "kg" if match.group("unit") == "kg" else "lb"
        sets.extend(Set(reps=reps, weight=weight, unit=unit) for _ in range(count))
    return sets


def parse_liftohistory(text: str) -> Workout:
    lines = text.strip().splitlines()

    # Skip any leading "// note" or blank lines before the header.
    idx = 0
    while idx < len(lines) and (
        not lines[idx].strip() or lines[idx].strip().startswith("//")
    ):
        idx += 1
    header_line = lines[idx].strip()
    body_lines = lines[idx + 1 :]

    header_segments = header_line.split(" / ")
    date_str = header_segments[0]
    # Last segment is "exercises: {" — everything about the exercises
    # themselves comes from body_lines, scanned below.
    fields = _parse_header_fields(header_segments[1:-1])

    dt = datetime.fromisoformat(date_str).astimezone(UTC)
    start_time = dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    duration = fields.get("duration")
    elapsed_time = int(duration.rstrip("s")) if duration else 0

    program = fields.get("program")
    day_name = fields.get("dayName")
    if program and day_name:
        name = f"{program} - {day_name}"
    else:
        name = program or day_name or None

    exercises = []
    for line in body_lines:
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        if line == "}":
            break

        segments = line.split(" / ")
        exercise_name = segments[0].strip()
        completed_segment = next(
            (
                s
                for s in segments[1:]
                if not s.startswith("warmup:") and not s.startswith("target:")
            ),
            None,
        )
        sets = _parse_set_groups(completed_segment) if completed_segment else []
        exercises.append(Exercise(name=exercise_name, sets=sets))

    return Workout(
        start_time=start_time,
        elapsed_time=elapsed_time,
        exercises=exercises,
        name=name,
        description=None,
        utc_offset=None,
    )
