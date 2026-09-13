"""Locks in upload_activity, poll_upload, and set_muted against Strava's
API shape, with all requests mocked via `responses` (no real network, no
credentials needed). These pin down a couple of behaviors that were
bugfixed deliberately and would be easy to lose in a refactor:

  - upload_activity gives every call a unique filename/external_id, since
    Strava dedupes uploads by that field and a fixed name made retries
    return a stale cached result (see the comment above upload_activity).
  - poll_upload distinguishes "still processing" from an error response
    from a resolved activity_id, and times out rather than hanging forever
    (or raising a bare NameError — see the comment in client.py).
"""

import pytest
import responses
from liftostrava.strava import client


@responses.activate
def test_upload_activity_sends_expected_form_fields_and_payload(sample_workout):
    responses.add(
        responses.POST,
        "https://www.strava.com/api/v3/uploads",
        json={"id": 999, "status": "Your activity is still being processed."},
        status=201,
    )

    result = client.upload_activity("token", sample_workout, "WeightTraining")

    assert result["id"] == 999
    sent = responses.calls[0].request
    assert sent.headers["Authorization"] == "Bearer token"
    body = sent.body
    assert isinstance(body, bytes)
    assert b'"version": "1.0"' in body


@responses.activate
def test_upload_activity_uses_a_unique_filename_per_call(sample_workout):
    responses.add(
        responses.POST,
        "https://www.strava.com/api/v3/uploads",
        json={"id": 1},
        status=201,
    )
    responses.add(
        responses.POST,
        "https://www.strava.com/api/v3/uploads",
        json={"id": 2},
        status=201,
    )

    client.upload_activity("token", sample_workout, "WeightTraining")
    client.upload_activity("token", sample_workout, "WeightTraining")

    filenames = []
    for call in responses.calls:
        body = call.request.body
        assert isinstance(body, bytes)
        filenames.append(body.split(b'filename="')[1].split(b'"')[0])
    assert filenames[0] != filenames[1]


@responses.activate
def test_poll_upload_keeps_polling_until_activity_id_appears(monkeypatch):
    responses.add(
        responses.GET,
        "https://www.strava.com/api/v3/uploads/1",
        json={"id": 1, "status": "processing"},
        status=200,
    )
    responses.add(
        responses.GET,
        "https://www.strava.com/api/v3/uploads/1",
        json={"id": 1, "status": "done", "activity_id": 555},
        status=200,
    )
    monkeypatch.setattr(client.time, "sleep", lambda s: None)

    status = client.poll_upload("token", 1, timeout_s=5)

    assert status["activity_id"] == 555


@responses.activate
def test_poll_upload_raises_on_a_strava_error(monkeypatch):
    responses.add(
        responses.GET,
        "https://www.strava.com/api/v3/uploads/1",
        json={"id": 1, "error": "duplicate of activity 123"},
        status=200,
    )
    monkeypatch.setattr(client.time, "sleep", lambda s: None)

    with pytest.raises(RuntimeError, match="duplicate of activity 123"):
        client.poll_upload("token", 1, timeout_s=5)


@responses.activate
def test_poll_upload_times_out_if_never_resolved(monkeypatch):
    responses.add(
        responses.GET,
        "https://www.strava.com/api/v3/uploads/1",
        json={"id": 1, "status": "still processing"},
        status=200,
    )
    # Mocking time.sleep (rather than faking time.time itself) keeps the
    # real wall clock in play — requests' own cookie-jar handling calls
    # time.time() too, so a short canned sequence of fake values runs out
    # and raises StopIteration from unrelated code. A tiny real timeout is
    # both simpler and safer.
    monkeypatch.setattr(client.time, "sleep", lambda s: None)

    with pytest.raises(TimeoutError, match="still processing"):
        client.poll_upload("token", 1, timeout_s=0.05)


@responses.activate
def test_set_muted_sends_a_lowercase_string_value():
    responses.add(
        responses.PUT,
        "https://www.strava.com/api/v3/activities/123",
        json={},
        status=200,
    )

    client.set_muted("token", 123, True)

    assert responses.calls[0].request.body == "hide_from_home=true"
