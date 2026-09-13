"""
Upload a strength workout (in the JSON shape below) to Strava as a
WeightTraining activity with structured per-set data.

Usage:
    python sync_to_strava.py workouts/2026-08-24T165602Z-fierce-5-workout-a.json
    python sync_to_strava.py workouts/2026-08-24T165602Z-fierce-5-workout-a.json --public
    python sync_to_strava.py workouts/2026-08-24T165602Z-fierce-5-workout-a.json --dry-run

Input JSON shape (see sample_workout.json):
{
  "name": "Fierce 5 - Workout A",
  "start_time": "2026-08-24T16:56:02Z",   // ISO 8601, UTC
  "elapsed_time": 1868,                    // seconds
  "utc_offset": 3600,                      // optional, seconds; defaults to
                                            // ATHLETE_TIMEZONE's offset at
                                            // start_time (see below) if omitted
  "description": "optional free text",
  "exercises": [
    {"name": "Squat", "sets": [{"reps": 5, "weight_kg": 60}, ...]},
    ...
  ]
}

--- Important caveats (read before relying on this) ---

1. Strava does publish a "Supported Exercises" list of accepted
   `exercise_type` values by category, at
   developers.strava.com/docs/uploads/ — that's the source for entries
   in EXERCISE_TYPE_MAP marked "docs" below. Check that live page
   before guessing at a new mapping. If you're editing this from a
   sandboxed Claude Code environment, make sure it's configured to
   allow outbound access to developers.strava.com (and www.strava.com,
   which this script itself calls) — see "Network access" in
   README.md. It's still not a formal machine-readable schema for the
   upload JSON format itself. Unrecognised exercise names commonly
   show up as "Unknown" in the app rather than causing an error — see
   EXERCISE_TYPE_MAP below.

2. Privacy: the Strava API has not supported setting an activity's
   visibility (Everyone / Followers / Only You) since ~2018 — this is
   a known, long-standing API limitation, not something this script
   can work around. The only related control the API exposes is
   `hide_from_home`, which mutes an activity from feeds but does NOT
   make it "Only You" private. This script sets hide_from_home=True
   by default (pass --public to skip that). For activities to
   actually default to "Only You", set that as your account-wide
   default in the Strava app: Settings > Privacy Controls > Activities.
"""

import argparse
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv, set_key

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")

# The athlete's home timezone — confirmed via Strava's get_athlete_profile
# (location: London, UK). Used to compute utc_offset for Strava's
# start_date_local display when a workout JSON doesn't specify one
# explicitly (see default_utc_offset below). A zoneinfo name, not a fixed
# offset in seconds, so it stays correct across BST/GMT transitions —
# Liftosaur's history records report start times in UTC (see the "+00:00"
# in e.g. "2026-09-09 06:37:54 +00:00"), and without a correct utc_offset
# Strava displays that raw UTC instant as if it were already local time,
# which is off by an hour whenever the athlete isn't literally in UTC+0
# (confirmed: a 06:37:54 UTC workout upload without utc_offset rendered as
# "6:37" on Strava instead of the true local 07:37 BST — activity
# 20098878269). Update this if the athlete's home location changes.
ATHLETE_TIMEZONE = ZoneInfo("Europe/London")


def default_utc_offset(start_time_iso: str) -> int:
    """Seconds to add to a UTC start_time to get ATHLETE_TIMEZONE's local
    time, computed at that specific instant so DST transitions (BST vs GMT)
    are handled correctly rather than baking in a fixed offset."""
    dt = datetime.fromisoformat(start_time_iso.replace("Z", "+00:00"))
    offset = dt.astimezone(ATHLETE_TIMEZONE).utcoffset()
    # utcoffset() is typed as returning Optional[timedelta] since tzinfo is
    # a general interface, but a zoneinfo-backed datetime always has one.
    assert offset is not None
    return int(offset.total_seconds())


# Mapping from Liftosaur exercise names to Strava's exercise_type values.
# Extend this as new exercises show up in your program. Anything not in
# this map falls back to an automatic upper-snake-case of the name, which
# frequently works for simple single-word lifts but not for everything
# (see caveat above) — check the docs list there before guessing.
#
# IMPORTANT: Strava's exercise_type isn't the exercise *category* (e.g.
# "SQUAT", "BENCH_PRESS") — it's a specific leaf value from the FIT SDK's
# per-category exercise_name enum (e.g. category "squat" contains leaf
# values like BARBELL_BACK_SQUAT, FRONT_SQUAT, GOBLET_SQUAT, ...). Sending
# the bare category name doesn't error, it just silently renders as
# "Unknown" in the app AND breaks per-exercise grouping of sets (each set
# shows up as its own single-set "Unknown" entry instead of being merged).
# Entries below marked "docs" were checked against Strava's own published
# list of supported exercise_type values at
# developers.strava.com/docs/uploads/ (see caveat 1 above). That list is
# the actual ground truth; treat it as authoritative over guesses or the
# general FIT SDK enum. Entries also marked "+ upload" were additionally
# confirmed by checking a real uploaded activity's rendered name.
# "unverified" entries are still just guesses — if one comes back
# "Unknown", check the live docs page before guessing again.
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
    "Triceps Extension, Cable": "CABLE_TRICEPS_PUSHDOWN",  # docs — closest generic cable option in Strava's Triceps Extension list; unverified by upload, distinct from "Triceps Pushdown" above (Liftosaur models them as separate exercises)
    "Skullcrusher": "SKULL_CRUSHER",  # docs + upload (activity 20011321395) — old value LYING_TRICEPS_EXTENSION wasn't in Strava's Triceps Extension list at all
    "Leg Press": "LEG_PRESS",  # docs
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
    return re.sub(r"[^A-Za-z0-9]+", "_", name.strip()).strip("_").upper()


def build_strava_payload(workout: dict) -> dict:
    """Build the JSON file content that gets uploaded to /uploads."""
    sets = []
    for exercise in workout["exercises"]:
        ex_type = exercise_type_for(exercise["name"])
        for s in exercise["sets"]:
            sets.append(
                {
                    "exercise_type": ex_type,
                    "repetitions": s["reps"],
                    "weight": s["weight_kg"],
                    "start_time": workout["start_time"],
                }
            )
    return {
        "version": "1.0",
        "start_time": workout["start_time"],
        "utc_offset": workout.get(
            "utc_offset", default_utc_offset(workout["start_time"])
        ),
        "elapsed_time": workout["elapsed_time"],
        "sets": sets,
    }


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    resp = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    resp.raise_for_status()
    data = resp.json()
    # Strava rotates refresh tokens on some accounts; persist the latest.
    if data.get("refresh_token") and data["refresh_token"] != refresh_token:
        set_key(ENV_PATH, "STRAVA_REFRESH_TOKEN", data["refresh_token"])
    return data["access_token"]


def upload_activity(access_token: str, workout: dict, sport_type: str) -> dict:
    payload = build_strava_payload(workout)
    # Strava dedupes uploads by external_id (derived from the filename here):
    # a fixed name like "workout.json" makes a retry return the *cached*
    # result of a previous attempt instead of reprocessing new content —
    # and that includes a since-deleted activity, whose upload record
    # permanently reports no error and no activity_id (poll_upload just
    # times out against it). Deriving external_id from start_time alone
    # isn't enough since a retry of the same workout hits this too — use
    # a random component so every upload attempt gets its own record.
    filename = (
        f"liftosaur-{workout['start_time'].replace(':', '')}"
        f"-{uuid.uuid4().hex[:8]}.json"
    )
    files = {
        "file": (filename, json.dumps(payload), "application/json"),
    }
    data = {
        "data_type": "json",
        "sport_type": sport_type,
        "name": workout.get("name", "Strength Workout"),
        "description": workout.get("description", ""),
    }
    resp = requests.post(
        "https://www.strava.com/api/v3/uploads",
        headers={"Authorization": f"Bearer {access_token}"},
        data=data,
        files=files,
    )
    resp.raise_for_status()
    return resp.json()


def poll_upload(access_token: str, upload_id: int, timeout_s: float = 30) -> dict:
    # Starts unset rather than only being assigned inside the loop: with a
    # very small timeout_s the loop body can run zero times, and the
    # TimeoutError below used to reference this while still unbound,
    # raising a bare NameError instead of the intended TimeoutError.
    status = None
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = requests.get(
            f"https://www.strava.com/api/v3/uploads/{upload_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        status = resp.json()
        if status.get("error"):
            raise RuntimeError(f"Strava upload failed: {status['error']}")
        if status.get("activity_id"):
            return status
        time.sleep(1)
    last_status = status.get("status") if status else None
    raise TimeoutError(
        f"Upload didn't finish processing in time (last status: "
        f"{last_status!r}) — check strava.com manually, it may "
        f"still complete."
    )


def set_muted(access_token: str, activity_id: int, muted: bool) -> None:
    resp = requests.put(
        f"https://www.strava.com/api/v3/activities/{activity_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        data={"hide_from_home": str(muted).lower()},
    )
    resp.raise_for_status()


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("workout_file", help="Path to a workout JSON file")
    parser.add_argument(
        "--sport-type",
        default="WeightTraining",
        help="Strava sport_type (default: WeightTraining)",
    )
    parser.add_argument(
        "--public",
        action="store_true",
        help="Don't mute the activity from home feed "
        "(default: muted). This does NOT make it "
        "fully public — see module docstring.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and print the payload without "
        "calling Strava or requiring credentials.",
    )
    args = parser.parse_args()

    with open(args.workout_file) as f:
        workout = json.load(f)

    payload = build_strava_payload(workout)

    if args.dry_run:
        print("Would upload the following to Strava (--dry-run, nothing sent):\n")
        print(
            json.dumps(
                {
                    "form_fields": {
                        "data_type": "json",
                        "sport_type": args.sport_type,
                        "name": workout.get("name", "Strength Workout"),
                        "description": workout.get("description", ""),
                    },
                    "file_content": payload,
                    "hide_from_home_after_upload": not args.public,
                },
                indent=2,
            )
        )
        return

    load_dotenv(ENV_PATH)
    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")
    refresh_token = os.getenv("STRAVA_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        print("Missing Strava credentials in .env. Run strava_auth.py first.")
        sys.exit(1)
    # The all([...]) check above guarantees none of these are None, but the
    # type checker can't narrow through a dynamically-built list — spell it
    # out so the str | None from os.getenv() doesn't propagate further.
    assert client_id is not None
    assert client_secret is not None
    assert refresh_token is not None

    print("Refreshing access token...")
    access_token = refresh_access_token(client_id, client_secret, refresh_token)

    print("Uploading workout...")
    upload = upload_activity(access_token, workout, args.sport_type)
    upload_id = upload["id"]

    print(f"Upload accepted (id={upload_id}), waiting for Strava to process it...")
    status = poll_upload(access_token, upload_id)
    activity_id = status["activity_id"]

    if not args.public:
        print("Muting activity from home feed (hide_from_home=true)...")
        set_muted(access_token, activity_id, True)

    print(f"\nDone: https://www.strava.com/activities/{activity_id}")
    if not args.public:
        print(
            "Note: hide_from_home only mutes it from feeds — it is not "
            "the same as 'Only You' visibility. Set your account's "
            "default activity privacy to 'Only You' in Strava's app "
            "settings if you want that guarantee (see README)."
        )


if __name__ == "__main__":
    main()
