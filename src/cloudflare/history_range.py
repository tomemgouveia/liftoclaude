"""Parses the ?start=&end= date range of the workout list. Pure, so the
validation is unit-testable outside the Workers runtime."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_DAYS = 7
MAX_DAYS = 366


class HistoryRangeError(ValueError):
    pass


def _parse_day(params: dict[str, list[str]], key: str) -> date | None:
    value = params.get(key, [""])[0].strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HistoryRangeError(f"'{key}' must be a date like 2026-10-31") from None


def parse_history_range(
    params: dict[str, list[str]],
    timezone: str | None,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Inclusive [start, end] days, interpreted in the user's timezone
    (UTC if unset), as UTC datetimes covering those whole local days.
    Defaults to the last DEFAULT_DAYS days."""
    try:
        tz = ZoneInfo(timezone) if timezone else UTC
    except (ZoneInfoNotFoundError, ValueError):
        tz = UTC
    today = (now or datetime.now(UTC)).astimezone(tz).date()
    end_day = _parse_day(params, "end") or today
    start_day = _parse_day(params, "start") or end_day - timedelta(
        days=DEFAULT_DAYS - 1
    )
    if start_day > end_day:
        raise HistoryRangeError("'start' must not be after 'end'")
    if (end_day - start_day).days >= MAX_DAYS:
        raise HistoryRangeError(f"Range can be at most {MAX_DAYS} days")
    start = datetime.combine(start_day, time.min, tzinfo=tz).astimezone(UTC)
    end = datetime.combine(end_day, time.max, tzinfo=tz).astimezone(UTC)
    return start, end
