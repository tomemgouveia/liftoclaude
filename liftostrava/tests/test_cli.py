"""An end-to-end check of the `sync-to-strava` CLI's --dry-run path:
argument parsing, McpExportSource, and build_strava_payload wired
together, exercised as a real subprocess so it also pins down the actual
invocation itself, not just the functions underneath it. --dry-run needs
no credentials or network, since main() returns before load_dotenv.
"""

import json
import subprocess
import sys


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
        [sys.executable, "-m", "liftostrava.cli.sync", str(workout_file), "--dry-run"],
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
            "-m",
            "liftostrava.cli.sync",
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
