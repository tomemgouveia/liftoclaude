"""Locks in LiftosaurApiSource against the REST API's shape, with the GET
mocked via `responses` (no real network, no real API key) — matching the
pattern in test_strava_client.py. The parsing itself is
test_liftohistory_parser.py's job; this only checks the HTTP plumbing:
URL, Bearer header, that the response's "text" field(s) reach the parser
correctly, and — for list_history — that cursor-based pagination and the
startDate/endDate query params are wired correctly against the response
shape documented at https://www.liftosaur.com/doc/api.
"""

import pytest
import responses
from liftostrava.models import Exercise, Set, Workout
from liftostrava.sources.api import LiftosaurApiSource

RECORD_TEXT = (
    '2026-09-11 17:30:05 +00:00 / program: "L/S/U" / dayName: "Upper" / '
    "duration: 2625s / exercises: {\n"
    "  Bench Press / 2x8 42.5kg\n"
    "}"
)


@responses.activate
def test_load_hits_the_expected_url_with_a_bearer_header(monkeypatch):
    monkeypatch.setenv("LIFTOSAUR_API_KEY", "test-api-key")
    responses.add(
        responses.GET,
        "https://www.liftosaur.com/api/v1/history/12345",
        json={"data": {"text": RECORD_TEXT}},
        status=200,
    )

    LiftosaurApiSource("12345").load()

    assert len(responses.calls) == 1
    sent = responses.calls[0].request
    assert sent.url == "https://www.liftosaur.com/api/v1/history/12345"
    assert sent.headers["Authorization"] == "Bearer test-api-key"


@responses.activate
def test_load_parses_the_response_text_field_into_a_workout(monkeypatch):
    monkeypatch.setenv("LIFTOSAUR_API_KEY", "test-api-key")
    responses.add(
        responses.GET,
        "https://www.liftosaur.com/api/v1/history/12345",
        json={"data": {"text": RECORD_TEXT}},
        status=200,
    )

    workout = LiftosaurApiSource("12345").load()

    assert workout == Workout(
        start_time="2026-09-11T17:30:05Z",
        elapsed_time=2625,
        name="L/S/U - Upper",
        description=None,
        utc_offset=None,
        exercises=[Exercise(name="Bench Press", sets=[Set(8, 42.5, "kg")] * 2)],
    )


def test_load_raises_a_clear_error_when_api_key_is_unset(monkeypatch):
    monkeypatch.delenv("LIFTOSAUR_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="LIFTOSAUR_API_KEY"):
        LiftosaurApiSource("12345").load()


@responses.activate
def test_list_history_parses_every_record_on_a_single_page(monkeypatch):
    monkeypatch.setenv("LIFTOSAUR_API_KEY", "test-api-key")
    responses.add(
        responses.GET,
        "https://www.liftosaur.com/api/v1/history",
        json={"data": {"records": [{"id": 2, "text": RECORD_TEXT}], "hasMore": False}},
        status=200,
    )

    entries = LiftosaurApiSource.list_history()

    assert len(entries) == 1
    assert entries[0].identifier == "2"
    assert entries[0].workout.name == "L/S/U - Upper"


@responses.activate
def test_list_history_follows_pagination_until_hasmore_is_false(monkeypatch):
    monkeypatch.setenv("LIFTOSAUR_API_KEY", "test-api-key")
    responses.add(
        responses.GET,
        "https://www.liftosaur.com/api/v1/history",
        json={
            "data": {
                "records": [{"id": 1, "text": RECORD_TEXT}],
                "hasMore": True,
                "nextCursor": 42,
            }
        },
        status=200,
    )
    responses.add(
        responses.GET,
        "https://www.liftosaur.com/api/v1/history",
        json={"data": {"records": [{"id": 2, "text": RECORD_TEXT}], "hasMore": False}},
        status=200,
    )

    entries = LiftosaurApiSource.list_history()

    assert [e.identifier for e in entries] == ["1", "2"]
    assert len(responses.calls) == 2
    assert "cursor=42" in (responses.calls[1].request.url or "")
    assert "cursor" not in (responses.calls[0].request.url or "")


@responses.activate
def test_list_history_passes_start_and_end_date_as_query_params(monkeypatch):
    monkeypatch.setenv("LIFTOSAUR_API_KEY", "test-api-key")
    responses.add(
        responses.GET,
        "https://www.liftosaur.com/api/v1/history",
        json={"data": {"records": [], "hasMore": False}},
        status=200,
    )

    LiftosaurApiSource.list_history(start_date="2026-09-01", end_date="2026-09-11")

    sent_url = responses.calls[0].request.url or ""
    assert "startDate=2026-09-01" in sent_url
    assert "endDate=2026-09-11" in sent_url


def test_list_history_raises_a_clear_error_when_api_key_is_unset(monkeypatch):
    monkeypatch.delenv("LIFTOSAUR_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="LIFTOSAUR_API_KEY"):
        LiftosaurApiSource.list_history()
