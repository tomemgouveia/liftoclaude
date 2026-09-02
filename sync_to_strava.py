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
  "description": "optional free text",
  "exercises": [
    {"name": "Squat", "sets": [{"reps": 5, "weight_kg": 60}, ...]},
    ...
  ]
}

--- Important caveats (read before relying on this) ---

1. Strava has not published an official schema for the JSON upload
   format or the `exercise_type` enum values it expects. Everything
   here is based on third-party developer reports (as of the May 2026
   strength-training rollout) of what currently works, not Strava's
   own docs. Field names or accepted values may drift over time.
   Unrecognised exercise names commonly show up as "Unknown" in the
   app rather than causing an error — see EXERCISE_TYPE_MAP below.

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

import requests
from dotenv import load_dotenv, set_key

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")

# Best-effort mapping from common exercise names to what the uploads API
# seems to expect (upper snake case, loosely following the FIT SDK
# exercise_name enum). Extend this as you find exercises that map wrong
# or come back "Unknown" in the app. Anything not in this map falls back
# to an automatic upper-snake-case of the name, which frequently works
# for simple single-word lifts but not for everything (see caveat above).
#
# IMPORTANT: Strava's exercise_type isn't the exercise *category* (e.g.
# "SQUAT", "BENCH_PRESS") — it's a specific leaf value from the FIT SDK's
# per-category exercise_name enum (e.g. category "squat" contains leaf
# values like BARBELL_BACK_SQUAT, FRONT_SQUAT, GOBLET_SQUAT, ...). Sending
# the bare category name doesn't error, it just silently renders as
# "Unknown" in the app AND breaks per-exercise grouping of sets (each set
# shows up as its own single-set "Unknown" entry instead of being merged).
# Entries below marked "verified" were checked against the FIT SDK's
# published exercise_name enum (github.com/dtcooper/python-fitparse
# fitparse/profile.py); "unverified" entries are still just guesses like
# the original map — if one comes back "Unknown", look up the real leaf
# value for that category before assuming the guess is right.
EXERCISE_TYPE_MAP = {
    "Squat": "BARBELL_BACK_SQUAT",  # verified
    "Front Squat": "BARBELL_FRONT_SQUAT",  # verified
    "Bench Press": "BARBELL_BENCH_PRESS",  # verified
    "Incline Bench Press": "INCLINE_BARBELL_BENCH_PRESS",  # verified
    "Overhead Press": "OVERHEAD_BARBELL_PRESS",  # verified
    "Shoulder Press": "SMITH_MACHINE_OVERHEAD_PRESS",  # verified (BARBELL_SHOULDER_PRESS renders Unknown despite being in the FIT SDK enum)
    "Shoulder Press, Leverage Machine": "SEATED_MACHINE_SHOULDER_PRESS",  # unverified — SMITH_MACHINE_OVERHEAD_PRESS was wrong (user reported it rendered incorrectly on activity 20009445714 and fixed it in-app to "Machine Seated Shoulder Press"); this is a naming-convention guess (posture_equipment_movement, matching e.g. SEATED_CABLE_ROW), not yet confirmed via upload
    "Deadlift": "BARBELL_DEADLIFT",  # verified
    "Romanian Deadlift": "ROMANIAN_DEADLIFT",  # unverified
    "Pendlay Row": "BENT_OVER_ROW",  # confirmed working via a real upload
    "Bent Over Row": "BENT_OVER_ROW",  # confirmed working via a real upload
    "Seated Row": "SEATED_CABLE_ROW",  # verified
    "Lat Pulldown": "LAT_PULLDOWN",  # verified
    "Bicep Curl": "STANDING_DUMBBELL_BICEPS_CURL",  # verified
    "Hammer Curl": "DUMBBELL_HAMMER_CURL",  # verified
    "Triceps Pushdown": "TRICEPS_PRESSDOWN",  # verified (Strava/FIT calls it "pressdown", not "pushdown")
    "Skullcrusher": "LYING_TRICEPS_EXTENSION",  # unverified
    "Leg Press": "LEG_PRESS",  # verified
    "Standing Calf Raise": "STANDING_CALF_RAISE",  # unverified
    "Standing Calf Raise, Cable": "STANDING_CALF_RAISE",  # confirmed via a real upload (activity 19977181952) — the untrimmed ", Cable" equipment suffix isn't in this map and the old fallback left a comma in the enum value, which rendered "Unknown"; user fixed it in-app to "Standing Calf Raise"
    "Cable Crunch": "CABLE_CRUNCH",  # unverified
    "Hanging Leg Raise": "HANGING_LEG_RAISE",  # unverified
    "Side Bend": "DUMBBELL_SIDE_BEND",  # confirmed via a real upload (activity 19939855283) — WEIGHTED_SIDE_BEND rendered "Unknown"; user fixed it in-app to "Dumbbell Side Bend"
    "Face Pull": "FACE_PULL",  # verified
    "Lateral Raise": "LATERAL_RAISE",  # unverified
    "Hip Thrust, Leverage Machine": "MACHINE_HIP_THRUST",  # confirmed via a real upload (activity 20011184163)
    "Pallof Press": "PALLOF_PRESS",  # confirmed via a real upload (activity 20011184163)
    "Seated Leg Curl": "SEATED_MACHINE_LEG_CURL",  # WRONG — rendered "Unknown" on a real upload (activity 20011184163); needs another guess
    "Leg Extension": "MACHINE_LEG_EXTENSION",  # confirmed via a real upload (activity 20011184163)
    "Hip Abductor - Machine": "MACHINE_HIP_ABDUCTION",  # confirmed via a real upload (activity 20011184163); user's custom exercise
    "Hip Adductor - Machine": "MACHINE_HIP_ADDUCTION",  # confirmed via a real upload (activity 20011184163); user's custom exercise
    "Incline Row": "CHEST_SUPPORTED_ROW",  # confirmed via a real upload (activity 20011184163); replaces Pendlay Row in the L/S/U program
    "Scapular Pull Up": "NEGATIVE_PULL_UP",  # placeholder — no dedicated Strava exercise type for this exists; user asked to map it to Negative Pull Up until Strava adds one
    "Negative Pull Up": "NEGATIVE_PULL_UP",  # confirmed via a real upload (activity 20011184163)
    "Pull Up": "PULL_UP",  # WRONG — rendered "Unknown" on a real upload (activity 20011184163); needs another guess
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
        "utc_offset": workout.get("utc_offset", 0),
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


def poll_upload(access_token: str, upload_id: int, timeout_s: int = 30) -> dict:
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
    raise TimeoutError(
        f"Upload didn't finish processing in time (last status: "
        f"{status.get('status')!r}) — check strava.com manually, it may "
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
