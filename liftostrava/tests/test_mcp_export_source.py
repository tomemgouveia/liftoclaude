"""Locks in McpExportSource's parsing of the workout JSON file CLAUDE.md
has Claude write after pulling a record over the Liftosaur MCP server —
the one ingestion route that exists today."""

import json

from liftostrava.models import Exercise, Set, Workout
from liftostrava.sources.mcp_export import McpExportSource


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

    workout = McpExportSource(workout_file).load()

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

    workout = McpExportSource(workout_file).load()

    assert workout.utc_offset == 3600


def _write_workout(directory, filename, start_time):
    (directory / filename).write_text(
        json.dumps({"start_time": start_time, "elapsed_time": 100, "exercises": []})
    )


def test_list_history_returns_every_file_newest_first(tmp_path):
    _write_workout(tmp_path, "a.json", "2026-09-07T07:20:12Z")
    _write_workout(tmp_path, "b.json", "2026-09-11T17:30:05Z")
    _write_workout(tmp_path, "c.json", "2026-09-09T06:37:54Z")

    entries = McpExportSource.list_history(directory=tmp_path)

    assert [e.workout.start_time for e in entries] == [
        "2026-09-11T17:30:05Z",
        "2026-09-09T06:37:54Z",
        "2026-09-07T07:20:12Z",
    ]


def test_list_history_filters_by_date_range_inclusive(tmp_path):
    _write_workout(tmp_path, "a.json", "2026-09-07T07:20:12Z")
    _write_workout(tmp_path, "b.json", "2026-09-09T06:37:54Z")
    _write_workout(tmp_path, "c.json", "2026-09-11T17:30:05Z")

    entries = McpExportSource.list_history(
        start_date="2026-09-08", end_date="2026-09-11T17:30:05Z", directory=tmp_path
    )

    assert [e.workout.start_time for e in entries] == [
        "2026-09-11T17:30:05Z",
        "2026-09-09T06:37:54Z",
    ]


def test_list_history_returns_empty_list_for_a_missing_directory(tmp_path):
    assert McpExportSource.list_history(directory=tmp_path / "does-not-exist") == []


def test_list_history_entry_identifier_reloads_the_same_workout(tmp_path):
    _write_workout(tmp_path, "only.json", "2026-09-11T17:30:05Z")

    [entry] = McpExportSource.list_history(directory=tmp_path)

    assert entry.identifier == str(tmp_path / "only.json")
    assert entry.workout.start_time == "2026-09-11T17:30:05Z"
    # The whole point of `identifier`: it round-trips back into the same
    # source constructor to reload the same workout.
    assert McpExportSource(entry.identifier).load() == entry.workout
