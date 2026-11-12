"""The pure transformation from a Workout into what Strava's /uploads
endpoint expects — form fields, JSON file content, and the exercise-name
mapping that goes into it. No I/O, so it's the easiest half of the
Strava-uploading logic to unit-test (and what --dry-run previews).

--- Exercise mapping ---
Mapping from Liftosaur exercise names to Strava's exercise_type values.
Extend this as new exercises show up in your program. Anything not in
this map falls back to an automatic upper-snake-case of the name, which
frequently works for simple single-word lifts but not for everything
(see caveat below) — check the docs list there before guessing.

IMPORTANT: Strava's exercise_type isn't the exercise *category* (e.g.
"SQUAT", "BENCH_PRESS") — it's a specific leaf value from the FIT SDK's
per-category exercise_name enum (e.g. category "squat" contains leaf
values like BARBELL_BACK_SQUAT, FRONT_SQUAT, GOBLET_SQUAT, ...). Sending
the bare category name doesn't error, it just silently renders as
"Unknown" in the app AND breaks per-exercise grouping of sets (each set
shows up as its own single-set "Unknown" entry instead of being merged).
Entries below marked "docs" were checked against Strava's own published
list of supported exercise_type values at
developers.strava.com/docs/uploads/. That list is the actual ground
truth; treat it as authoritative over guesses or the general FIT SDK
enum. Entries also marked "+ upload" were additionally confirmed by
checking a real uploaded activity's rendered name. "unverified" entries
are still just guesses — if one comes back "Unknown", check the live
docs page before guessing again.
"""

import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from liftostrava.domain import Workout

logger = logging.getLogger(__name__)

# Strava's upload format has always expected weight in kg here, regardless
# of what unit the source recorded a set in.
LB_TO_KG = 0.45359237

SPORT_TYPE = "WeightTraining"
DEFAULT_ACTIVITY_NAME = "Strength Workout"

EXERCISE_TYPE_MAP = {
    "Squat": "BARBELL_BACK_SQUAT",  # docs
    "Front Squat": "BARBELL_FRONT_SQUAT",  # docs
    "Bench Press": "BARBELL_BENCH_PRESS",  # docs
    "Incline Bench Press": "INCLINE_BARBELL_BENCH_PRESS",  # docs
    "Overhead Press": "OVERHEAD_BARBELL_PRESS",  # docs
    "Shoulder Press": "SMITH_MACHINE_OVERHEAD_PRESS",  # docs (BARBELL_SHOULDER_PRESS isn't in Strava's documented Shoulder Press list at all, consistent with it rendering Unknown)
    "Shoulder Press, Leverage Machine": "MACHINE_SEATED_SHOULDER_PRESS",  # docs + upload (activity 20011321395) — the old value SEATED_MACHINE_SHOULDER_PRESS (wrong word order, not in Strava's docs) had also rendered correctly on 2 earlier uploads, so Strava may alias it, but this is the documented spelling.
    "Deadlift": "BARBELL_DEADLIFT",  # docs
    "Romanian Deadlift": "BARBELL_ROMANIAN_DEADLIFT",  # docs + upload (activity 20011321395) — old value ROMANIAN_DEADLIFT wasn't in Strava's list at all
    "Single Leg Deadlift": "SINGLE_LEG_DUMBBELL_ROMANIAN_DEADLIFTS",  # docs — Liftosaur's "Single Leg Deadlift" has no ", Dumbbell" variant (like "Bicep Curl", the bare name is the dumbbell version); unverified by upload
    "Pendlay Row": "BENT_OVER_ROW",  # docs + upload
    "Bent Over Row": "BENT_OVER_ROW",  # docs + upload
    "Seated Row": "SEATED_CABLE_ROW",  # docs
    "Lat Pulldown": "LAT_PULLDOWN",  # docs
    "Bicep Curl": "STANDING_DUMBBELL_BICEPS_CURL",  # docs
    "Bicep Curl, Cable": "CABLE_BICEPS_CURL",  # docs — unverified by upload
    "Hammer Curl": "DUMBBELL_HAMMER_CURL",  # docs
    "Triceps Pushdown": "TRICEPS_PRESSDOWN",  # docs (Strava calls it "pressdown", not "pushdown")
    "Triceps Extension, Cable": "CABLE_OVERHEAD_TRICEPS_EXTENSION",  # docs + upload (activity 20295834556) — previous value CABLE_TRICEPS_PUSHDOWN rendered as "Triceps Push Down", which the user confirmed was wrong: their movement is an overhead extension, not a pushdown (that's "Triceps Pushdown" above, a distinct Liftosaur exercise)
    "Skullcrusher": "SKULL_CRUSHER",  # docs + upload (activity 20011321395) — old value LYING_TRICEPS_EXTENSION wasn't in Strava's Triceps Extension list at all
    "Skullcrusher, Dumbbell": "DUMBBELL_SKULLCRUSHER",  # docs + upload (activity 20705460781) — distinct Liftosaur exercise from the bare "Skullcrusher" above (barbell); was previously unmapped and falling back to SKULLCRUSHER_DUMBBELL (wrong token order, not in Strava's docs), which happened to still render correctly via Strava's apparent order-tolerant matching, but that's not guaranteed — mapped explicitly to the documented value instead of relying on it
    "Leg Press": "LEG_PRESS",  # docs
    "Seated Leg Press": "LEG_PRESS",  # docs — Strava's Leg Press category has only one exercise_type; the unmapped "Seated" prefix previously fell through to the fallback and rendered "Unknown" (activity 20295834556), user fixed it in-app to "Leg Press"
    "Standing Calf Raise": "STANDING_CALF_RAISE",  # docs
    "Standing Calf Raise, Cable": "STANDING_CALF_RAISE",  # docs + upload (activity 19977181952) — the untrimmed ", Cable" equipment suffix isn't in this map and the old fallback left a comma in the enum value, which rendered "Unknown"; user fixed it in-app to "Standing Calf Raise"
    "Standing Calf Raise, Leverage Machine": "STANDING_CALF_RAISE",  # docs + upload (activity 20070453899) — same untrimmed-suffix issue as the Cable variant above; rendered "Unknown", user confirmed it's the same machine as the plain "Standing Calf Raise" entry
    "Single Leg Standing Calf Raise, Dumbbell": "SINGLE_LEG_DUMBBELL_STANDING_CALF_RAISE",  # docs — matches the L/S/U program's exercise name exactly; unverified by upload
    "Cable Crunch": "CABLE_CRUNCH",  # docs
    "Incline Crunch": "DECLINE_CRUNCH",  # docs + upload (activity 20133759746) — Strava has no "Incline Crunch" enum; rendered "Unknown", user confirmed their incline-bench crunch is the same movement as Strava's "Decline Crunch" and fixed it in-app to that
    "Hanging Leg Raise": "HANGING_LEG_RAISE",  # docs
    "Side Bend": "DUMBBELL_SIDE_BEND",  # docs + upload (activity 19939855283) — WEIGHTED_SIDE_BEND rendered "Unknown"; user fixed it in-app to "Dumbbell Side Bend"
    "Face Pull": "FACE_PULL",  # docs
    "Lateral Raise": "LATERAL_RAISE_GENERIC",  # docs + upload (activity 20011321395) — old value LATERAL_RAISE (no _GENERIC) wasn't in Strava's Lateral Raise list at all
    "Hip Thrust, Leverage Machine": "MACHINE_HIP_THRUST",  # docs + upload (activity 20011184163)
    "Pallof Press": "PALLOF_PRESS",  # docs + upload (activity 20011184163)
    "Seated Leg Curl": "MACHINE_LEG_CURL_SEATED",  # docs + upload (activity 20011321395) — old value LEG_CURL had confirmed "Unknown" on an isolated real upload (activity 20011260255)
    "Leg Extension": "MACHINE_LEG_EXTENSION",  # docs + upload (activity 20011184163)
    "Hip Abductor - Machine": "MACHINE_HIP_ABDUCTION",  # docs + upload (activity 20011184163); user's custom exercise
    "Hip Adductor - Machine": "MACHINE_HIP_ADDUCTION",  # docs + upload (activity 20011184163); user's custom exercise
    "Incline Row": "CHEST_SUPPORTED_ROW",  # docs + upload (activity 20011184163); replaces Pendlay Row in the L/S/U program
    "Seated Row - Leverage Machine": "MACHINE_CHEST_SUPPORTED_ROW",  # docs + upload (activity 20517932538) — old fallback value SEATED_ROW_LEVERAGE_MACHINE wasn't in Strava's list; user fixed it in-app to "Machine Chest-Supported Row". Distinct from the plain CHEST_SUPPORTED_ROW used for Incline Row above (non-machine) — a test sync with CHEST_SUPPORTED_ROW rendered just "Chest-Supported Row", confirmed wrong for this machine exercise.
    "Scapular Pull Up": "NEGATIVE_PULL_UP",  # placeholder — no dedicated Strava exercise type for this exists; user asked to map it to Negative Pull Up (itself a documented, confirmed value) until Strava adds one
    "Negative Pull Up": "NEGATIVE_PULL_UP",  # docs + upload (activity 20011184163)
    "Pull Up": "PULL_UP_GENERIC",  # docs + upload (activity 20011321395) — old value STANDARD_PULL_UP had confirmed "Unknown" on an isolated real upload (activity 20011260255); rendered exactly as "Pull Up", matching the user's own reference activity
}


def exercise_type_for(name: str) -> str:
    if name in EXERCISE_TYPE_MAP:
        return EXERCISE_TYPE_MAP[name]
    # Fallback: normalise any run of non-alphanumeric characters (spaces,
    # hyphens, commas, etc.) to a single underscore. Exercise names with
    # punctuation Strava doesn't expect (e.g. "Standing Calf Raise, Cable")
    # previously left stray characters like commas in the enum value here,
    # which rendered as "Unknown" in the app.
    guess = re.sub(r"[^A-Za-z0-9]+", "_", name.strip()).strip("_").upper()
    logger.warning(
        "No Strava exercise_type mapping for %r; guessing %s (may render as "
        "'Unknown'). Add it to EXERCISE_TYPE_MAP.",
        name,
        guess,
    )
    return guess


def utc_offset_at(start_time_iso: str, tz: ZoneInfo) -> int:
    """Seconds to add to a UTC start_time to get `tz`'s local time,
    computed at that specific instant so DST transitions (BST vs GMT) are
    handled correctly rather than baking in a fixed offset. Strava
    displays start_time as local time using this offset: without it a
    06:37:54 UTC workout renders as "6:37" instead of the true 07:37 BST."""
    # fromisoformat() has accepted a trailing "Z" natively since Python 3.11.
    dt = datetime.fromisoformat(start_time_iso)
    offset = dt.astimezone(tz).utcoffset()
    # utcoffset() is typed as returning Optional[timedelta] since tzinfo is
    # a general interface, but a zoneinfo-backed datetime always has one.
    assert offset is not None
    return int(offset.total_seconds())


def upload_form_fields(workout: Workout) -> dict:
    """The non-file form fields sent with an upload.

    Falls back to a default name/description only when the workout truly
    has none (`None`), not merely an empty string — `x or default` would
    silently discard an explicitly empty value."""
    return {
        "data_type": "json",
        "sport_type": SPORT_TYPE,
        "name": workout.name if workout.name is not None else DEFAULT_ACTIVITY_NAME,
        "description": workout.description if workout.description is not None else "",
    }


def build_payload(workout: Workout, utc_offset: int) -> dict:
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
    payload = {
        "version": "1.0",
        "start_time": workout.start_time,
        "utc_offset": utc_offset,
        "elapsed_time": workout.elapsed_time,
        "sets": sets,
    }
    streams = build_streams(workout)
    if streams:
        payload["streams"] = streams
    return payload


def build_streams(workout: Workout) -> dict | None:
    """Strava's `streams` object: `time` (seconds from start_time) and a
    same-length `heartrate` array. None when the workout has no heart rate.
    Sorted by time; a repeated offset keeps its last sample, since Strava
    wants one value per time point."""
    if not workout.heart_rate:
        return None
    by_offset = {sample.offset_s: sample.bpm for sample in workout.heart_rate}
    times = sorted(by_offset)
    return {"time": times, "heartrate": [by_offset[t] for t in times]}
