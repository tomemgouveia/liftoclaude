"""End-to-end checks of the `sync-to-strava` CLI: the --dry-run path via
a real subprocess (pinning down the actual invocation itself, not just
the functions underneath it — no credentials or network needed since
main() returns before load_dotenv), and the real upload path in-process
with Strava mocked via `responses` (a subprocess can't easily have its
network calls intercepted, so this half uses a real .env file plus
monkeypatched ENV_PATH/argv instead) — verifying refresh -> upload ->
poll -> mute are actually wired together correctly, including the
--public branch.
"""

import json
import subprocess
import sys

import responses
from liftostrava.cli import sync


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


def _write_env(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "STRAVA_CLIENT_ID=cid\n"
        "STRAVA_CLIENT_SECRET=csecret\n"
        "STRAVA_REFRESH_TOKEN=old-refresh\n"
    )
    return env_file


@responses.activate
def test_main_runs_the_full_upload_flow(tmp_path, monkeypatch, capsys):
    """The real counterpart to the --dry-run tests above: exercises
    main()'s actual upload path in-process (not a subprocess, so env vars
    can be controlled) with every Strava call mocked. Nothing else in the
    suite verifies that refresh -> upload -> poll -> mute are actually
    wired together correctly, or what ends up printed."""
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
    monkeypatch.setattr(sync, "ENV_PATH", str(_write_env(tmp_path)))
    monkeypatch.setattr(sys, "argv", ["sync-to-strava", str(workout_file)])

    responses.add(
        responses.POST,
        "https://www.strava.com/oauth/token",
        json={"access_token": "access-token", "refresh_token": "old-refresh"},
        status=200,
    )
    responses.add(
        responses.POST,
        "https://www.strava.com/api/v3/uploads",
        json={"id": 42},
        status=201,
    )
    responses.add(
        responses.GET,
        "https://www.strava.com/api/v3/uploads/42",
        json={"id": 42, "activity_id": 999},
        status=200,
    )
    responses.add(
        responses.PUT,
        "https://www.strava.com/api/v3/activities/999",
        json={},
        status=200,
    )

    sync.main()

    out = capsys.readouterr().out
    assert "https://www.strava.com/activities/999" in out
    mute_calls = [c for c in responses.calls if c.request.method == "PUT"]
    assert len(mute_calls) == 1
    assert mute_calls[0].request.body == "hide_from_home=true"


@responses.activate
def test_main_with_public_flag_skips_muting(tmp_path, monkeypatch, capsys):
    workout_file = tmp_path / "workout.json"
    workout_file.write_text(
        json.dumps(
            {"start_time": "2026-08-24T16:56:02Z", "elapsed_time": 100, "exercises": []}
        )
    )
    monkeypatch.setattr(sync, "ENV_PATH", str(_write_env(tmp_path)))
    monkeypatch.setattr(sys, "argv", ["sync-to-strava", str(workout_file), "--public"])

    responses.add(
        responses.POST,
        "https://www.strava.com/oauth/token",
        json={"access_token": "access-token", "refresh_token": "old-refresh"},
        status=200,
    )
    responses.add(
        responses.POST,
        "https://www.strava.com/api/v3/uploads",
        json={"id": 42},
        status=201,
    )
    responses.add(
        responses.GET,
        "https://www.strava.com/api/v3/uploads/42",
        json={"id": 42, "activity_id": 999},
        status=200,
    )

    sync.main()

    out = capsys.readouterr().out
    assert "https://www.strava.com/activities/999" in out
    assert not any(c.request.method == "PUT" for c in responses.calls)
