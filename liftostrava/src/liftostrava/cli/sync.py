"""
Upload a strength workout to Strava as a WeightTraining activity with
structured per-set data.

Usage:
    sync-to-strava workouts/2026-08-24T165602Z-fierce-5-workout-a.json
    sync-to-strava workouts/2026-08-24T165602Z-fierce-5-workout-a.json --public
    sync-to-strava workouts/2026-08-24T165602Z-fierce-5-workout-a.json --dry-run
    sync-to-strava --from-api 1789147805585
    sync-to-strava --from-api 1789147805585 --dry-run

Two input routes:

  - A JSON file (see liftostrava.sources.mcp_export and the sample at
    liftostrava/tests/fixtures/sample_workout.json for its shape) — the
    one CLAUDE.md in the repo root instructs Claude to write after
    pulling a record from the Liftosaur MCP server, for when no
    LIFTOSAUR_API_KEY is configured.
  - `--from-api RECORD_ID`, which fetches and parses the record directly
    from Liftosaur's REST API (see liftostrava.sources.api) — requires
    Premium and LIFTOSAUR_API_KEY in .env. No JSON file involved.

--- Important caveats (read before relying on this) ---

1. Strava does publish a "Supported Exercises" list of accepted
   `exercise_type` values by category, at
   developers.strava.com/docs/uploads/ — that's the source for entries
   in EXERCISE_TYPE_MAP (liftostrava/strava/exercise_map.py) marked
   "docs" below. Check that live page before guessing at a new mapping.
   It's still not a formal machine-readable schema for the upload JSON
   format itself. Unrecognised exercise names commonly show up as
   "Unknown" in the app rather than causing an error.

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
import sys

from dotenv import load_dotenv

from liftostrava.config import ENV_PATH
from liftostrava.sources.api import LiftosaurApiSource
from liftostrava.sources.mcp_export import McpExportSource
from liftostrava.strava.auth import refresh_access_token
from liftostrava.strava.client import (
    poll_upload,
    set_muted,
    strava_form_fields,
    upload_activity,
)
from liftostrava.strava.payload import build_strava_payload


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("workout_file", nargs="?", help="Path to a workout JSON file")
    parser.add_argument(
        "--from-api",
        metavar="RECORD_ID",
        help="Fetch and parse the workout directly from Liftosaur's REST "
        "API instead of a JSON file (requires Premium and "
        "LIFTOSAUR_API_KEY in .env). Alternative to workout_file.",
    )
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

    if bool(args.workout_file) == bool(args.from_api):
        parser.error("Provide exactly one of workout_file or --from-api")

    # Needed before loading the workout: --from-api reads LIFTOSAUR_API_KEY
    # from .env at load time, dry-run or not. Harmless no-op for the
    # workout_file route, which doesn't consume any env vars.
    load_dotenv(ENV_PATH)

    if args.from_api:
        workout = LiftosaurApiSource(args.from_api).load()
    else:
        workout = McpExportSource(args.workout_file).load()

    if args.dry_run:
        print("Would upload the following to Strava (--dry-run, nothing sent):\n")
        print(
            json.dumps(
                {
                    "form_fields": strava_form_fields(workout, args.sport_type),
                    "file_content": build_strava_payload(workout),
                    "hide_from_home_after_upload": not args.public,
                },
                indent=2,
            )
        )
        return

    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")
    refresh_token = os.getenv("STRAVA_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        print("Missing Strava credentials in .env. Run strava-auth first.")
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
