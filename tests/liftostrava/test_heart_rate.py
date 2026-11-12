import pytest

from liftostrava.domain import HeartRateSample
from liftostrava.errors import NotSyncedYet
from liftostrava.heart_rate import (
    parse_iso,
    samples_for_workout,
    window_samples,
    workout_end,
)

START = "2026-11-11T17:45:17Z"
ELAPSED = 600  # ends 17:55:17


def sample(time: str, bpm: object = 120) -> dict:
    return {"time": time, "bpm": bpm}


def test_workout_end_is_start_plus_duration():
    assert workout_end(START, ELAPSED) == parse_iso("2026-11-11T17:55:17Z")


def test_parse_iso_converts_offsets_to_utc():
    assert parse_iso("2026-11-11T18:45:17+01:00") == parse_iso(START)


def test_parse_iso_rejects_naive_times():
    with pytest.raises(ValueError):
        parse_iso("2026-11-11T17:45:17")


def test_window_keeps_inside_samples_as_offsets_oldest_first():
    raw = [
        sample("2026-11-11T17:50:17Z", 130),
        sample("2026-11-11T17:45:17Z", 100),  # exactly at start
        sample("2026-11-11T17:55:17Z", 110),  # exactly at end
    ]
    assert window_samples(raw, START, ELAPSED) == [
        HeartRateSample(0, 100),
        HeartRateSample(300, 130),
        HeartRateSample(600, 110),
    ]


def test_window_drops_samples_outside():
    raw = [sample("2026-11-11T17:45:16Z"), sample("2026-11-11T17:55:18Z")]
    assert window_samples(raw, START, ELAPSED) == []


@pytest.mark.parametrize(
    "bad",
    [
        "not a dict",
        {"time": "2026-11-11T17:50:00Z"},  # no bpm
        {"bpm": 120},  # no time
        sample("2026-11-11T17:50:00Z", True),  # bool
        sample("2026-11-11T17:50:00Z", "fast"),
        sample("2026-11-11T17:50:00Z", None),
        sample("2026-11-11T17:50:00Z", 29),
        sample("2026-11-11T17:50:00Z", 241),
        sample("garbage"),
        sample("2026-11-11T17:50:00"),  # naive
        sample(12345),
    ],
)
def test_window_drops_invalid_samples(bad):
    good = sample("2026-11-11T17:46:00Z", 99)
    assert window_samples([bad, good], START, ELAPSED) == [HeartRateSample(43, 99)]


def test_window_accepts_numeric_text_and_floats():
    raw = [
        sample("2026-11-11T17:46:00Z", "121.4"),
        sample("2026-11-11T17:47:00Z", 98.6),
    ]
    assert [s.bpm for s in window_samples(raw, START, ELAPSED)] == [121, 99]


@pytest.mark.parametrize("not_a_list", [None, {}, "x", 5])
def test_window_non_list_input_is_empty(not_a_list):
    assert window_samples(not_a_list, START, ELAPSED) == []


def test_samples_for_workout_returns_samples_when_covered():
    raw = [sample("2026-11-11T17:46:00Z"), sample("2026-11-11T17:55:00Z")]
    assert len(samples_for_workout(raw, START, ELAPSED)) == 2


def test_last_sample_exactly_at_tolerance_boundary_is_ok():
    # end 17:55:17 - 60s = 17:54:17
    raw = [sample("2026-11-11T17:54:17Z")]
    assert samples_for_workout(raw, START, ELAPSED)


def test_last_sample_one_second_past_tolerance_is_not_synced():
    raw = [sample("2026-11-11T17:54:16Z")]
    with pytest.raises(NotSyncedYet, match="only runs to 17:54"):
        samples_for_workout(raw, START, ELAPSED)


def test_samples_after_the_end_are_ignored_not_an_error():
    raw = [sample("2026-11-11T17:55:00Z"), sample("2026-11-11T18:30:00Z")]
    assert [s.offset_s for s in samples_for_workout(raw, START, ELAPSED)] == [583]


def test_no_samples_is_not_synced():
    with pytest.raises(NotSyncedYet, match="No heart-rate samples"):
        samples_for_workout([], START, ELAPSED)
