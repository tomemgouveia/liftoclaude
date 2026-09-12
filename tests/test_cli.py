"""An end-to-end check of main()'s --dry-run path: argument parsing plus
build_strava_payload wired together, exercised as a real subprocess so it
also pins down the current `python sync_to_strava.py <file>` invocation
itself — the part of the CLI's behavior users (and CLAUDE.md) depend on
that unit tests of the individual functions wouldn't catch. --dry-run
needs no credentials or network, since main() returns before load_dotenv.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_dry_run_prints_the_built_payload_without_network_or_credentials(tmp_path):
    workout_file = tmp_path / "workout.json"
    workout_file.write_text(
        json.dumps(
            {
                "name": "Test Workout",
                "start_time": "2026-08-24T16:56:02Z",
                "elapsed_time": 100,
                "exercises": [
                    {"name": "Squat", "sets": [{"reps": 5, "weight_kg": 60}]}
                ],
            }
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "sync_to_strava.py"),
            str(workout_file),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout[result.stdout.index("{") :])

    assert payload["form_fields"]["name"] == "Test Workout"
    assert payload["file_content"]["sets"][0]["exercise_type"] == "BARBELL_BACK_SQUAT"
    assert payload["hide_from_home_after_upload"] is True


def test_dry_run_public_flag_disables_hide_from_home(tmp_path):
    workout_file = tmp_path / "workout.json"
    workout_file.write_text(
        json.dumps(
            {
                "start_time": "2026-08-24T16:56:02Z",
                "elapsed_time": 100,
                "exercises": [],
            }
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "sync_to_strava.py"),
            str(workout_file),
            "--dry-run",
            "--public",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout[result.stdout.index("{") :])
    assert payload["hide_from_home_after_upload"] is False
