def test_history_range_defaults_to_last_week_in_user_timezone():
    from datetime import UTC, datetime

    from liftostrava_worker.routes.history_range import parse_history_range

    now = datetime(2026, 11, 1, 23, 30, tzinfo=UTC)
    start, end = parse_history_range({}, "Asia/Tokyo", now=now)

    assert start == datetime(2026, 10, 26, 15, 0, tzinfo=UTC)  # Oct 27 00:00 JST
    assert end.date().isoformat() == "2026-11-02"


def test_history_range_rejects_bad_input():
    import pytest

    from liftostrava_worker.routes.history_range import (
        HistoryRangeError,
        parse_history_range,
    )

    for params in (
        {"start": ["nope"]},
        {"start": ["2026-10-02"], "end": ["2026-10-01"]},
        {"start": ["2020-01-01"], "end": ["2026-01-01"]},
    ):
        with pytest.raises(HistoryRangeError):
            parse_history_range(params, None)
