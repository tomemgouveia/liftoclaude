"""Locks in the parsing of the workout JSON file the sync-to-strava skill
has Claude write after pulling a record over the Liftosaur MCP server."""

import json

from liftostrava.domain import Exercise, Set, Workout
from liftostrava.liftosaur.mcp_export import list_exported, load_workout


def test_load_parses_the_full_fixture(sample_workout):
    assert sample_workout == Workout(
        start_time="2026-08-24T16:56:02Z",
        elapsed_time=1868,
        name="Fierce 5 - Workout A",
        description="Synced from Liftosaur",
        utc_offset=None,
        exercises=[
            Exercise(name="Squat", sets=[Set(5, 60), Set(5, 60), Set(5, 60)]),
            Exercise(name="Bench Press", sets=[Set(5, 40), Set(5, 40), Set(5, 40)]),
            Exercise(name="Pendlay Row", sets=[Set(8, 40), Set(9, 40), Set(8, 40)]),
        ],
    )


def test_load_defaults_optional_fields_to_none_when_absent(tmp_path):
    workout_file = tmp_path / "minimal.json"
    workout_file.write_text(
        json.dumps(
            {
                "start_time": "2026-01-15T10:00:00Z",
                "elapsed_time": 100,
                "exercises": [],
            }
        )
    )

    workout = load_workout(workout_file)

    assert workout.name is None
    assert workout.description is None
    assert workout.utc_offset is None
    assert workout.exercises == []


def test_load_respects_an_explicit_utc_offset(tmp_path):
    workout_file = tmp_path / "with_offset.json"
    workout_file.write_text(
        json.dumps(
            {
                "start_time": "2026-01-15T10:00:00Z",
                "elapsed_time": 100,
                "utc_offset": 3600,
                "exercises": [],
            }
        )
    )

    workout = load_workout(workout_file)

    assert workout.utc_offset == 3600


def _write_workout(directory, filename, start_time):
    (directory / filename).write_text(
        json.dumps({"start_time": start_time, "elapsed_time": 100, "exercises": []})
    )


def test_list_exported_returns_every_file_newest_first(tmp_path):
    _write_workout(tmp_path, "a.json", "2026-09-07T07:20:12Z")
    _write_workout(tmp_path, "b.json", "2026-09-11T17:30:05Z")
    _write_workout(tmp_path, "c.json", "2026-09-09T06:37:54Z")

    entries = list_exported(tmp_path)

    assert [e.workout.start_time for e in entries] == [
        "2026-09-11T17:30:05Z",
        "2026-09-09T06:37:54Z",
        "2026-09-07T07:20:12Z",
    ]


def test_list_exported_filters_by_date_range_inclusive(tmp_path):
    _write_workout(tmp_path, "a.json", "2026-09-07T07:20:12Z")
    _write_workout(tmp_path, "b.json", "2026-09-09T06:37:54Z")
    _write_workout(tmp_path, "c.json", "2026-09-11T17:30:05Z")

    entries = list_exported(
        tmp_path, start_date="2026-09-08", end_date="2026-09-11T17:30:05Z"
    )

    assert [e.workout.start_time for e in entries] == [
        "2026-09-11T17:30:05Z",
        "2026-09-09T06:37:54Z",
    ]


def test_list_exported_returns_empty_list_for_a_missing_directory(tmp_path):
    assert list_exported(tmp_path / "does-not-exist") == []


def test_list_exported_entry_id_reloads_the_same_workout(tmp_path):
    _write_workout(tmp_path, "only.json", "2026-09-11T17:30:05Z")

    [entry] = list_exported(tmp_path)

    assert entry.id == str(tmp_path / "only.json")
    assert entry.workout.start_time == "2026-09-11T17:30:05Z"
    # The whole point of `id`: it round-trips back into load_workout.
    assert load_workout(entry.id) == entry.workout
