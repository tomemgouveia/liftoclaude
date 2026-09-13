"""The pure transformation from a Workout into the JSON Strava's
/uploads endpoint expects — no I/O, so it's the easiest half of the
Strava-uploading logic to unit-test."""

from datetime import datetime
from zoneinfo import ZoneInfo

from liftostrava.models import Workout
from liftostrava.strava.exercise_map import exercise_type_for

# The athlete's home timezone — confirmed via Strava's get_athlete_profile
# (location: London, UK). Used to compute utc_offset for Strava's
# start_date_local display when a workout doesn't specify one explicitly
# (see default_utc_offset below). A zoneinfo name, not a fixed offset in
# seconds, so it stays correct across BST/GMT transitions — Liftosaur's
# history records report start times in UTC, and without a correct
# utc_offset Strava displays that raw UTC instant as if it were already
# local time, which is off by an hour whenever the athlete isn't literally
# in UTC+0 (confirmed: a 06:37:54 UTC workout upload without utc_offset
# rendered as "6:37" on Strava instead of the true local 07:37 BST —
# activity 20098878269). Update this if the athlete's home location
# changes.
ATHLETE_TIMEZONE = ZoneInfo("Europe/London")

# Strava's upload format has always expected weight in kg here, regardless
# of what unit the source recorded a set in.
LB_TO_KG = 0.45359237


def default_utc_offset(start_time_iso: str) -> int:
    """Seconds to add to a UTC start_time to get ATHLETE_TIMEZONE's local
    time, computed at that specific instant so DST transitions (BST vs GMT)
    are handled correctly rather than baking in a fixed offset."""
    # fromisoformat() has accepted a trailing "Z" natively since Python 3.11.
    dt = datetime.fromisoformat(start_time_iso)
    offset = dt.astimezone(ATHLETE_TIMEZONE).utcoffset()
    # utcoffset() is typed as returning Optional[timedelta] since tzinfo is
    # a general interface, but a zoneinfo-backed datetime always has one.
    assert offset is not None
    return int(offset.total_seconds())


def build_strava_payload(workout: Workout) -> dict:
    """Build the JSON file content that gets uploaded to /uploads."""
    sets = []
    for exercise in workout.exercises:
        ex_type = exercise_type_for(exercise.name)
        for s in exercise.sets:
            weight_kg = s.weight * LB_TO_KG if s.unit == "lb" else s.weight
            sets.append(
                {
                    "exercise_type": ex_type,
                    "repetitions": s.reps,
                    "weight": weight_kg,
                    "start_time": workout.start_time,
                }
            )
    return {
        "version": "1.0",
        "start_time": workout.start_time,
        "utc_offset": (
            workout.utc_offset
            if workout.utc_offset is not None
            else default_utc_offset(workout.start_time)
        ),
        "elapsed_time": workout.elapsed_time,
        "sets": sets,
    }
