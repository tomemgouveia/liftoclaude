"""Locks in StravaClient against Strava's API shape, with all requests
mocked via `responses` (no real network, no credentials needed). These pin
down a couple of behaviors that were bugfixed deliberately and would be
easy to lose in a refactor:

  - upload gives every call a unique filename/external_id, since Strava
    dedupes uploads by that field and a fixed name made retries return a
    stale cached result (see the comment above StravaClient.upload).
  - wait_for_upload distinguishes "still processing" from an error
    response from a resolved activity_id, and times out rather than
    hanging forever.
"""

import asyncio

import pytest
import requests
import responses

from liftostrava.errors import StravaUploadError
from liftostrava.strava.client import StravaClient

client = StravaClient("token")


async def _no_sleep(seconds):
    pass


@responses.activate
def test_upload_sends_expected_form_fields_and_payload(sample_workout):
    responses.add(
        responses.POST,
        "https://www.strava.com/api/v3/uploads",
        json={"id": 999, "status": "Your activity is still being processed."},
        status=201,
    )

    upload_id = client.upload(sample_workout, 3600)

    assert upload_id == 999
    sent = responses.calls[0].request
    assert sent.headers["Authorization"] == "Bearer token"
    body = sent.body
    assert isinstance(body, bytes)
    assert b'"version": "1.0"' in body
    assert b'"utc_offset": 3600' in body


@responses.activate
def test_upload_uses_a_unique_filename_per_call(sample_workout):
    for upload_id in (1, 2):
        responses.add(
            responses.POST,
            "https://www.strava.com/api/v3/uploads",
            json={"id": upload_id},
            status=201,
        )

    client.upload(sample_workout, 0)
    client.upload(sample_workout, 0)

    filenames = []
    for call in responses.calls:
        body = call.request.body
        assert isinstance(body, bytes)
        filenames.append(body.split(b'filename="')[1].split(b'"')[0])
    assert filenames[0] != filenames[1]


@responses.activate
def test_wait_for_upload_keeps_polling_until_activity_id_appears():
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

    activity_id = asyncio.run(client.wait_for_upload(1, timeout_s=5, sleep=_no_sleep))

    assert activity_id == 555


@responses.activate
def test_wait_for_upload_raises_on_a_strava_error():
    responses.add(
        responses.GET,
        "https://www.strava.com/api/v3/uploads/1",
        json={"id": 1, "error": "duplicate of activity 123"},
        status=200,
    )

    with pytest.raises(StravaUploadError, match="duplicate of activity 123"):
        asyncio.run(client.wait_for_upload(1, timeout_s=5, sleep=_no_sleep))


@responses.activate
def test_wait_for_upload_times_out_if_never_resolved():
    responses.add(
        responses.GET,
        "https://www.strava.com/api/v3/uploads/1",
        json={"id": 1, "status": "still processing"},
        status=200,
    )
    # A tiny real timeout (with sleep mocked out) rather than faking
    # time.time: requests' own cookie-jar handling calls it too, so a
    # short canned sequence of fake values would run out in unrelated code.
    with pytest.raises(TimeoutError, match="still processing"):
        asyncio.run(client.wait_for_upload(1, timeout_s=0.05, sleep=_no_sleep))


@responses.activate
def test_set_hide_from_home_sends_a_lowercase_string_value():
    responses.add(
        responses.PUT,
        "https://www.strava.com/api/v3/activities/123",
        json={},
        status=200,
    )

    client.set_hide_from_home(123, True)

    assert responses.calls[0].request.body == "hide_from_home=true"


@responses.activate
def test_get_activity_returns_the_activity_json():
    responses.add(
        responses.GET,
        "https://www.strava.com/api/v3/activities/123",
        json={"id": 123, "name": "Lower Body Workout"},
        status=200,
    )

    activity = client.get_activity(123)

    assert activity == {"id": 123, "name": "Lower Body Workout"}
    assert responses.calls[0].request.headers["Authorization"] == "Bearer token"


@responses.activate
def test_get_activity_raises_on_a_missing_activity():
    responses.add(
        responses.GET,
        "https://www.strava.com/api/v3/activities/404",
        json={"message": "Resource Not Found"},
        status=404,
    )

    with pytest.raises(requests.HTTPError):
        client.get_activity(404)
