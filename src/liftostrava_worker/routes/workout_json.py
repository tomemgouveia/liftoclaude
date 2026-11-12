"""JSON shapes for the workout list. Pure, so they're unit-testable
outside the Workers runtime."""

from datetime import datetime

from liftostrava.domain import WorkoutRecord
from liftostrava.heart_rate import format_utc, parse_iso, workout_end


def workout_json(entry: WorkoutRecord, brief: bool) -> dict:
    """`brief` is the compact id/name/date/start/end shape Shortcuts pick from; the
    full shape is what the web app renders."""
    workout = entry.workout
    summary = {
        "id": entry.id,
        "name": workout.name,
        "date": datetime.fromisoformat(workout.start_time).strftime("%Y-%m-%d"),
        # The exact window, for querying heart rate from Apple Health.
        "start": format_utc(parse_iso(workout.start_time)),
        "end": format_utc(workout_end(workout.start_time, workout.elapsed_time)),
    }
    if brief:
        return summary
    return {
        **summary,
        "start_time": workout.start_time,
        "duration_s": workout.elapsed_time,
        "exercises": [{"name": e.name, "sets": len(e.sets)} for e in workout.exercises],
    }
