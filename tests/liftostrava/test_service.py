"""SyncService orchestration with every Strava call mocked, driven through
an in-memory TokenStore — the same flow the CLI and the worker share."""

import asyncio
import time
from dataclasses import replace
from zoneinfo import ZoneInfo

import pytest
import responses

from liftostrava.domain import HeartRateSample
from liftostrava.errors import MissingCredentials
from liftostrava.service import SyncService, preview_upload, resolve_utc_offset
from liftostrava.strava.oauth import StravaOAuth
from liftostrava.tokens import StravaTokens


class MemoryTokenStore:
    def __init__(self, tokens):
        self.tokens = tokens
        self.saved = []

    async def load(self):
        return self.tokens

    async def save(self, tokens):
        self.saved.append(tokens)
        self.tokens = tokens


def _service(tokens, **kwargs):
    store = MemoryTokenStore(tokens)
    return SyncService(StravaOAuth("cid", "secret"), store, **kwargs), store


def _mock_strava(mute=True):
    responses.add(
        responses.POST,
        "https://www.strava.com/api/v3/uploads",
        json={"id": 42},
        status=201,
    )
    responses.add(
        responses.GET,
        "https://www.strava.com/api/v3/uploads/42",
        json={"id": 42, "activity_id": 999},
        status=200,
    )
    if mute:
        responses.add(
            responses.PUT,
            "https://www.strava.com/api/v3/activities/999",
            json={},
            status=200,
        )


@responses.activate
def test_sync_refreshes_an_expired_token_saves_it_then_uploads_and_mutes(
    sample_workout,
):
    responses.add(
        responses.POST,
        "https://www.strava.com/oauth/token",
        json={"access_token": "new", "refresh_token": "rotated", "expires_at": 5},
        status=200,
    )
    _mock_strava()
    service, store = _service(StravaTokens("", "old-refresh", 0))

    result = asyncio.run(service.sync(sample_workout))

    assert result.url == "https://www.strava.com/activities/999"
    assert result.hidden_from_home is True
    assert store.saved == [StravaTokens("new", "rotated", 5)]
    upload = next(c for c in responses.calls if c.request.url.endswith("/uploads"))
    assert upload.request.headers["Authorization"] == "Bearer new"
    assert responses.calls[-1].request.body == "hide_from_home=true"


@responses.activate
def test_sync_reuses_a_still_valid_access_token(sample_workout):
    _mock_strava(mute=False)
    valid = StravaTokens("current", "refresh", int(time.time()) + 10_000)
    service, store = _service(valid)

    result = asyncio.run(service.sync(sample_workout, hide_from_home=False))

    assert result.hidden_from_home is False
    assert store.saved == []
    assert not any("oauth/token" in c.request.url for c in responses.calls)
    assert not any(c.request.method == "PUT" for c in responses.calls)


def test_sync_without_tokens_raises_missing_credentials(sample_workout):
    service, _ = _service(None)

    with pytest.raises(MissingCredentials):
        asyncio.run(service.sync(sample_workout))


def test_progress_messages_are_reported_to_the_callback(sample_workout):
    messages = []
    with responses.RequestsMock() as mock:
        mock.add(
            responses.POST,
            "https://www.strava.com/api/v3/uploads",
            json={"id": 42},
            status=201,
        )
        mock.add(
            responses.GET,
            "https://www.strava.com/api/v3/uploads/42",
            json={"id": 42, "activity_id": 999},
            status=200,
        )
        service, _ = _service(
            StravaTokens("a", "r", int(time.time()) + 10_000), progress=messages.append
        )
        asyncio.run(service.sync(sample_workout, hide_from_home=False))

    assert messages[0] == "Uploading workout..."
    assert len(messages) == 2


def test_utc_offset_prefers_the_workout_then_the_timezone(sample_workout):
    assert sample_workout.utc_offset is None
    summer = ZoneInfo("Europe/London")
    assert resolve_utc_offset(sample_workout, summer) == 3600  # BST on 2026-08-24
    assert resolve_utc_offset(sample_workout, ZoneInfo("America/New_York")) == -14400

    explicit = type(sample_workout)(**{**sample_workout.__dict__, "utc_offset": 1234})
    assert resolve_utc_offset(explicit, summer) == 1234


def test_preview_matches_what_would_be_uploaded(sample_workout):
    preview = preview_upload(sample_workout, hide_from_home=False)

    assert preview["form_fields"]["name"] == "Fierce 5 - Workout A"
    assert preview["file_content"]["utc_offset"] == 3600
    assert preview["hide_from_home_after_upload"] is False


def test_preview_summarises_streams_instead_of_dumping_them(sample_workout):
    workout = replace(
        sample_workout,
        heart_rate=[HeartRateSample(0, 90), HeartRateSample(600, 130)],
    )
    streams = preview_upload(workout)["file_content"]["streams"]
    assert streams == {
        "samples": 2,
        "first_offset_s": 0,
        "last_offset_s": 600,
        "min_bpm": 90,
        "max_bpm": 130,
    }
