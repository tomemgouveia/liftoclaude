import pytest

from liftostrava.domain import Exercise, HeartRateSample, Set, Workout
from liftostrava.errors import NotSyncedYet
from liftostrava.heart_rate import (
    coverage_report,
    describe_shape,
    parse_iso,
    samples_for_workout,
    window_samples,
    with_heart_rate,
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


def test_no_samples_returns_empty_so_the_workout_uploads_without_heart_rate():
    assert samples_for_workout([], START, ELAPSED) == []


def test_only_samples_outside_the_window_count_as_none():
    raw = [sample("2026-11-11T17:00:00Z"), sample("2026-11-11T19:00:00Z")]
    assert samples_for_workout(raw, START, ELAPSED) == []


def test_with_heart_rate_attaches_samples_to_the_workout():
    workout = Workout(START, ELAPSED, [Exercise("Squat", [Set(5, 100.0)])])
    raw = [sample("2026-11-11T17:46:00Z", 99), sample("2026-11-11T17:55:00Z", 110)]
    result = with_heart_rate(workout, raw)
    assert [s.bpm for s in result.heart_rate] == [99, 110]
    assert workout.heart_rate == []  # original untouched


def test_with_heart_rate_and_no_samples_leaves_the_workout_without_any():
    workout = Workout(START, ELAPSED, [])
    assert with_heart_rate(workout, []).heart_rate == []


def test_with_heart_rate_raises_when_not_synced():
    workout = Workout(START, ELAPSED, [])
    with pytest.raises(NotSyncedYet):
        with_heart_rate(workout, [sample("2026-11-11T17:46:00Z")])


def test_coverage_report_describes_what_the_check_sees():
    raw = [sample("2026-11-11T17:46:00Z"), sample("2026-11-11T17:50:00Z"), "junk"]
    assert coverage_report(raw, START, ELAPSED) == {
        "samples_in_window": 2,
        "received": 3,
        "shape": "list[3]",
        "unreadable": 1,
        "unreadable_examples": ["'junk'"],
        "first_sample": "2026-11-11T17:46:00Z",
        "last_sample": "2026-11-11T17:50:00Z",
        "workout_start": "2026-11-11T17:45:17Z",
        "workout_end": "2026-11-11T17:55:17Z",
        "covers_workout": False,
    }


def test_coverage_report_with_no_samples():
    report = coverage_report([], START, ELAPSED)
    assert report["samples_in_window"] == 0
    assert report["first_sample"] is None
    assert report["covers_workout"] is False


def test_window_accepts_parallel_arrays():
    raw = {
        "time": [
            "2026-11-11T17:46:00Z",
            "2026-11-11T17:47:00Z",
            "2026-11-11T19:00:00Z",
        ],
        "bpm": [100, 110, 120],
    }
    assert [s.bpm for s in window_samples(raw, START, ELAPSED)] == [100, 110]


@pytest.mark.parametrize(
    "raw",
    [
        {"time": ["2026-11-11T17:46:00Z"], "bpm": [100, 110]},  # unequal
        {"time": "x", "bpm": "y"},
        {"bpm": [100]},
    ],
)
def test_window_unusable_parallel_arrays_are_empty(raw):
    assert window_samples(raw, START, ELAPSED) == []


@pytest.mark.parametrize(
    "bpm,expected",
    [("72 count/min", 72), ("  95", 95), ("120.4 bpm", 120), ("count/min 72", None)],
)
def test_bpm_text_with_units(bpm, expected):
    result = window_samples([sample("2026-11-11T17:46:00Z", bpm)], START, ELAPSED)
    assert [s.bpm for s in result] == ([] if expected is None else [expected])


def test_window_accepts_newline_separated_text_lists():
    raw = {
        "time": "2026-11-11T17:46:00Z\n2026-11-11T17:47:00Z\n",
        "bpm": "100 count/min\n110 count/min",
    }
    assert [s.bpm for s in window_samples(raw, START, ELAPSED)] == [100, 110]


def test_describe_shape_shows_types_and_lengths_not_values():
    assert describe_shape({"time": ["a", "b"], "bpm": "1\n2", "x": 5}) == {
        "time": "list[2]",
        "bpm": "str[3]",
        "x": "int",
    }
    assert describe_shape(None) == "NoneType"


def test_allow_partial_returns_samples_that_stop_early():
    raw = [sample("2026-11-11T17:46:00Z"), sample("2026-11-11T17:54:16Z")]
    result = samples_for_workout(raw, START, ELAPSED, allow_partial=True)
    assert len(result) == 2


def test_with_heart_rate_allow_partial_attaches_early_stopping_samples():
    workout = Workout(START, ELAPSED, [])
    result = with_heart_rate(
        workout, [sample("2026-11-11T17:46:00Z")], allow_partial=True
    )
    assert len(result.heart_rate) == 1
