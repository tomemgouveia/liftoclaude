"""Locks in build_strava_payload() and default_utc_offset() — the pure
transformation from a Liftosaur-shaped workout dict into the JSON Strava's
/uploads endpoint expects. In particular, default_utc_offset's DST handling
is a regression guard: an activity uploaded without a correct utc_offset
previously rendered an hour early on Strava whenever the athlete wasn't
literally in UTC+0 (see ATHLETE_TIMEZONE's comment in sync_to_strava.py and
commit c02cae0).
"""

import pytest

import sync_to_strava as sts


@pytest.mark.parametrize(
    "iso,expected_offset",
    [
        ("2026-08-24T16:56:02Z", 3600),  # BST (British Summer Time)
        ("2026-01-15T10:00:00Z", 0),  # GMT
    ],
)
def test_default_utc_offset_accounts_for_dst(iso, expected_offset):
    assert sts.default_utc_offset(iso) == expected_offset


def test_build_strava_payload_flattens_every_set_across_exercises(sample_workout):
    payload = sts.build_strava_payload(sample_workout)

    total_sets = sum(len(ex["sets"]) for ex in sample_workout["exercises"])
    assert len(payload["sets"]) == total_sets


def test_build_strava_payload_maps_each_set_correctly(sample_workout):
    payload = sts.build_strava_payload(sample_workout)

    squat_sets = [
        s for s in payload["sets"] if s["exercise_type"] == "BARBELL_BACK_SQUAT"
    ]
    assert len(squat_sets) == 3
    assert all(s["repetitions"] == 5 and s["weight"] == 60 for s in squat_sets)
    assert all(s["start_time"] == sample_workout["start_time"] for s in payload["sets"])


def test_build_strava_payload_computes_utc_offset_when_absent(sample_workout):
    assert "utc_offset" not in sample_workout  # sanity-check the fixture
    payload = sts.build_strava_payload(sample_workout)
    assert payload["utc_offset"] == sts.default_utc_offset(sample_workout["start_time"])


def test_build_strava_payload_respects_an_explicit_utc_offset(sample_workout):
    sample_workout["utc_offset"] = 1234
    payload = sts.build_strava_payload(sample_workout)
    assert payload["utc_offset"] == 1234


def test_build_strava_payload_top_level_fields(sample_workout):
    payload = sts.build_strava_payload(sample_workout)
    assert payload["version"] == "1.0"
    assert payload["start_time"] == sample_workout["start_time"]
    assert payload["elapsed_time"] == sample_workout["elapsed_time"]
