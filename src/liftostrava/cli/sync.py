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

  - A JSON file (see liftostrava.liftosaur.mcp_export and the sample at
    tests/fixtures/sample_workout.json for its shape) — the one the
    sync-to-strava skill has Claude write after pulling a record from the
    Liftosaur MCP server, for when no LIFTOSAUR_API_KEY is configured.
  - `--from-api RECORD_ID`, which fetches and parses the record directly
    from Liftosaur's REST API (see liftostrava.liftosaur.client) —
    requires Premium and LIFTOSAUR_API_KEY in .env. No JSON file involved.

Privacy: the Strava API cannot set an activity's visibility (Everyone /
Followers / Only You). By default this mutes the activity from feeds
(`hide_from_home`), which is NOT the same as "Only You"; pass --public to
skip even that. For a true default, set it in the Strava app (Settings >
Privacy Controls > Activities). Strava's exercise-name mapping caveats
are documented in liftostrava/strava/payload.py; see docs/usage.md for
the rest.
"""

import argparse
import asyncio
import json
import os
import sys

from dotenv import load_dotenv

from liftostrava.cli import config
from liftostrava.cli.env_store import EnvFileTokenStore
from liftostrava.domain import Workout
from liftostrava.errors import MissingCredentials
from liftostrava.liftosaur.client import LiftosaurClient
from liftostrava.liftosaur.mcp_export import load_workout
from liftostrava.service import SyncService, preview_upload
from liftostrava.strava.oauth import StravaOAuth


def build_parser() -> argparse.ArgumentParser:
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
    return parser


def load_input(args: argparse.Namespace) -> Workout:
    if args.from_api:
        client = LiftosaurClient(os.getenv("LIFTOSAUR_API_KEY", ""))
        return client.get_workout(args.from_api)
    return load_workout(args.workout_file)


def strava_oauth_from_env() -> StravaOAuth:
    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise MissingCredentials(
            "Missing Strava credentials in .env. Run strava-auth first."
        )
    return StravaOAuth(client_id, client_secret)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if bool(args.workout_file) == bool(args.from_api):
        parser.error("Provide exactly one of workout_file or --from-api")

    # Needed before loading the workout: --from-api reads LIFTOSAUR_API_KEY
    # from .env at load time, dry-run or not. Harmless no-op for the
    # workout_file route, which doesn't consume any env vars.
    load_dotenv(config.ENV_PATH)
    hide_from_home = not args.public

    try:
        workout = load_input(args)

        if args.dry_run:
            print("Would upload the following to Strava (--dry-run, nothing sent):\n")
            print(
                json.dumps(
                    preview_upload(workout, hide_from_home=hide_from_home), indent=2
                )
            )
            return

        service = SyncService(
            strava_oauth_from_env(),
            EnvFileTokenStore(config.ENV_PATH),
            progress=print,
        )
        result = asyncio.run(service.sync(workout, hide_from_home))
    except MissingCredentials as e:
        print(e)
        sys.exit(1)

    print(f"\nDone: {result.url}")
    if result.hidden_from_home:
        print(
            "Note: hide_from_home only mutes it from feeds — it is not "
            "the same as 'Only You' visibility. Set your account's "
            "default activity privacy to 'Only You' in Strava's app "
            "settings if you want that guarantee (see README)."
        )


if __name__ == "__main__":
    main()
