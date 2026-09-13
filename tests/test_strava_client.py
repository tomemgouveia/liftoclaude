"""Locks in the HTTP-calling half of sync_to_strava.py — token refresh,
upload, poll, and mute — against Strava's API shape, with all requests
mocked via `responses` (no real network, no credentials needed). These
pin down a few behaviors that were bugfixed deliberately and would be easy
to lose in a refactor:

  - refresh_access_token persists a rotated refresh_token to a real .env
    file, but only writes when Strava actually returned a different one.
  - upload_activity gives every call a unique filename/external_id, since
    Strava dedupes uploads by that field and a fixed name made retries
    return a stale cached result (see the comment above upload_activity).
  - poll_upload distinguishes "still processing" from an error response
    from a resolved activity_id, and times out rather than hanging forever.
"""

import pytest
import responses

import sync_to_strava as sts


@responses.activate
def test_refresh_access_token_persists_a_rotated_refresh_token(tmp_path, monkeypatch):
    # A real .env file rather than a mocked set_key: this verifies the
    # actual persisted state, not just that some function was called with
    # arguments that looked right.
    env_file = tmp_path / ".env"
    env_file.write_text("STRAVA_REFRESH_TOKEN=old-refresh\n")
    monkeypatch.setattr(sts, "ENV_PATH", str(env_file))
    responses.add(
        responses.POST,
        "https://www.strava.com/oauth/token",
        json={"access_token": "new-access", "refresh_token": "rotated-refresh"},
        status=200,
    )

    token = sts.refresh_access_token("cid", "csecret", "old-refresh")

    assert token == "new-access"
    assert "STRAVA_REFRESH_TOKEN='rotated-refresh'" in env_file.read_text()


@responses.activate
def test_refresh_access_token_skips_rewrite_when_refresh_token_is_unchanged(
    tmp_path, monkeypatch
):
    env_file = tmp_path / ".env"
    env_file.write_text("STRAVA_REFRESH_TOKEN=same-refresh\n")
    monkeypatch.setattr(sts, "ENV_PATH", str(env_file))
    before = env_file.read_text()
    responses.add(
        responses.POST,
        "https://www.strava.com/oauth/token",
        json={"access_token": "new-access", "refresh_token": "same-refresh"},
        status=200,
    )

    sts.refresh_access_token("cid", "csecret", "same-refresh")

    # No rewrite at all — not even a reformatted but value-equal line.
    assert env_file.read_text() == before


@responses.activate
def test_upload_activity_sends_expected_form_fields_and_payload(sample_workout):
    responses.add(
        responses.POST,
        "https://www.strava.com/api/v3/uploads",
        json={"id": 999, "status": "Your activity is still being processed."},
        status=201,
    )

    result = sts.upload_activity("token", sample_workout, "WeightTraining")

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

    sts.upload_activity("token", sample_workout, "WeightTraining")
    sts.upload_activity("token", sample_workout, "WeightTraining")

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
    monkeypatch.setattr(sts.time, "sleep", lambda s: None)

    status = sts.poll_upload("token", 1, timeout_s=5)

    assert status["activity_id"] == 555


@responses.activate
def test_poll_upload_raises_on_a_strava_error(monkeypatch):
    responses.add(
        responses.GET,
        "https://www.strava.com/api/v3/uploads/1",
        json={"id": 1, "error": "duplicate of activity 123"},
        status=200,
    )
    monkeypatch.setattr(sts.time, "sleep", lambda s: None)

    with pytest.raises(RuntimeError, match="duplicate of activity 123"):
        sts.poll_upload("token", 1, timeout_s=5)


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
    monkeypatch.setattr(sts.time, "sleep", lambda s: None)

    with pytest.raises(TimeoutError, match="still processing"):
        sts.poll_upload("token", 1, timeout_s=0.05)


@responses.activate
def test_set_muted_sends_a_lowercase_string_value():
    responses.add(
        responses.PUT,
        "https://www.strava.com/api/v3/activities/123",
        json={},
        status=200,
    )

    sts.set_muted("token", 123, True)

    assert responses.calls[0].request.body == "hide_from_home=true"
