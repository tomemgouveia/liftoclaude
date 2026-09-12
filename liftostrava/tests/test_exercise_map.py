"""Locks in exercise_type_for()'s behavior — both the curated
EXERCISE_TYPE_MAP entries (several of which were fixed in response to real
"Unknown" renders on Strava, per the map's comments and commit history) and
the upper-snake-case fallback for anything not in the map.
"""

import pytest
from liftostrava.strava.exercise_map import exercise_type_for


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Squat", "BARBELL_BACK_SQUAT"),
        ("Bench Press", "BARBELL_BENCH_PRESS"),
        ("Pendlay Row", "BENT_OVER_ROW"),
        ("Standing Calf Raise, Cable", "STANDING_CALF_RAISE"),
        ("Standing Calf Raise, Leverage Machine", "STANDING_CALF_RAISE"),
        ("Incline Crunch", "DECLINE_CRUNCH"),
        ("Pull Up", "PULL_UP_GENERIC"),
    ],
)
def test_known_mapping(name, expected):
    assert exercise_type_for(name) == expected


def test_unmapped_name_falls_back_to_upper_snake_case():
    assert exercise_type_for("Some New Machine") == "SOME_NEW_MACHINE"


def test_fallback_collapses_punctuation_runs_to_a_single_underscore():
    # A regression guard for the bug described at exercise_map.py's
    # EXERCISE_TYPE_MAP comment: an untrimmed ", Cable"-style suffix used
    # to leave a stray comma in the enum value and render "Unknown".
    assert exercise_type_for("Some New, Cable Machine") == "SOME_NEW_CABLE_MACHINE"


def test_fallback_strips_leading_and_trailing_punctuation_and_whitespace():
    assert exercise_type_for("  Weird!! Name--  ") == "WEIRD_NAME"
