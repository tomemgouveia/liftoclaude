"""Locks in build_payload(), utc_offset_at() and upload_form_fields() — the
pure transformation from a Workout into what Strava's /uploads endpoint
expects. In particular, utc_offset_at's DST handling is a regression
guard: an activity uploaded without a correct utc_offset previously
rendered an hour early on Strava whenever the athlete wasn't literally in
UTC+0.
"""

from zoneinfo import ZoneInfo

import pytest

from liftostrava.domain import Exercise, Set, Workout
from liftostrava.strava.payload import build_payload, upload_form_fields, utc_offset_at

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
