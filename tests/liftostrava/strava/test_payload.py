"""Locks in build_payload(), utc_offset_at(), upload_form_fields() and
exercise_type_for() — the
pure transformation from a Workout into what Strava's /uploads endpoint
expects. In particular, utc_offset_at's DST handling is a regression
guard: an activity uploaded without a correct utc_offset previously
rendered an hour early on Strava whenever the athlete wasn't literally in
UTC+0.
"""

import re
from zoneinfo import ZoneInfo

import pytest

from liftostrava.domain import Exercise, Set, Workout
from liftostrava.strava.payload import (
    EXERCISE_TYPE_MAP,
    build_payload,
    exercise_type_for,
    upload_form_fields,
    utc_offset_at,
)

LONDON = ZoneInfo("Europe/London")


@pytest.mark.parametrize(
    "iso,expected_offset",
    [
        ("2026-08-24T16:56:02Z", 3600),  # BST (British Summer Time)
        ("2026-01-15T10:00:00Z", 0),  # GMT
    ],
)
def test_utc_offset_at_accounts_for_dst(iso, expected_offset):
    assert utc_offset_at(iso, LONDON) == expected_offset


def test_build_payload_flattens_every_set_across_exercises(sample_workout):
    payload = build_payload(sample_workout, 3600)

    total_sets = sum(len(ex.sets) for ex in sample_workout.exercises)
    assert len(payload["sets"]) == total_sets


def test_build_payload_maps_each_set_correctly(sample_workout):
    payload = build_payload(sample_workout, 3600)

    squat_sets = [
        s for s in payload["sets"] if s["exercise_type"] == "BARBELL_BACK_SQUAT"
    ]
    assert len(squat_sets) == 3
    assert all(s["repetitions"] == 5 and s["weight"] == 60 for s in squat_sets)
    assert all(s["start_time"] == sample_workout.start_time for s in payload["sets"])


def test_build_payload_top_level_fields(sample_workout):
    payload = build_payload(sample_workout, 3600)
    assert payload["version"] == "1.0"
    assert payload["start_time"] == sample_workout.start_time
    assert payload["elapsed_time"] == sample_workout.elapsed_time


def test_build_payload_converts_lb_sets_to_kg():
    # Strava's own "weight" field has always been kg here — a set
    # recorded in lb (only possible via sources/api.py's Liftohistory
    # parser, since mcp_export.py's JSON wire format is always weight_kg)
    # must be converted before it's emitted.
    workout = Workout(
        start_time="2026-01-15T10:00:00Z",
        elapsed_time=100,
        exercises=[Exercise(name="Squat", sets=[Set(reps=5, weight=100, unit="lb")])],
    )
    payload = build_payload(workout, 0)
    assert payload["sets"][0]["weight"] == pytest.approx(45.359237)


def test_build_payload_leaves_kg_sets_unconverted():
    workout = Workout(
        start_time="2026-01-15T10:00:00Z",
        elapsed_time=100,
        exercises=[Exercise(name="Squat", sets=[Set(reps=5, weight=60, unit="kg")])],
    )
    payload = build_payload(workout, 0)
    assert payload["sets"][0]["weight"] == 60


def test_build_payload_uses_the_given_utc_offset(sample_workout):
    assert build_payload(sample_workout, 1234)["utc_offset"] == 1234


def test_form_fields_default_a_missing_name_and_description():
    workout = Workout(start_time="2026-01-15T10:00:00Z", elapsed_time=100, exercises=[])

    fields = upload_form_fields(workout)

    assert fields["name"] == "Strength Workout"
    assert fields["description"] == ""
    assert fields["sport_type"] == "WeightTraining"


def test_form_fields_preserve_an_explicitly_empty_name_and_description():
    workout = Workout(
        start_time="2026-01-15T10:00:00Z",
        elapsed_time=100,
        exercises=[],
        name="",
        description="",
    )

    fields = upload_form_fields(workout)

    assert fields["name"] == ""
    assert fields["description"] == ""


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
        ("Seated Row - Leverage Machine", "MACHINE_CHEST_SUPPORTED_ROW"),
        ("Seated Leg Press", "LEG_PRESS"),
        ("Triceps Extension, Cable", "CABLE_OVERHEAD_TRICEPS_EXTENSION"),
        ("Skullcrusher, Dumbbell", "DUMBBELL_SKULLCRUSHER"),
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


@pytest.mark.parametrize("liftosaur_name,strava_value", EXERCISE_TYPE_MAP.items())
def test_every_curated_mapping_is_a_well_formed_strava_enum_value(
    liftosaur_name, strava_value
):
    # A structural guard over the whole map, not just the handful of
    # entries spot-checked above: this is exactly the bug class the map's
    # own comments describe recurring (an untrimmed equipment suffix
    # leaving a stray comma/space in the enum value, rendering "Unknown"
    # on Strava) — this catches it in any of the ~40 entries, not just the
    # ones with a dedicated example test.
    assert re.fullmatch(r"[A-Z][A-Z0-9_]*", strava_value), (
        f"{liftosaur_name!r} maps to {strava_value!r}, which isn't "
        "upper-snake-case — check it against developers.strava.com/docs/uploads/"
    )
