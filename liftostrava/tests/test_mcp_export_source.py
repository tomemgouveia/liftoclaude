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
