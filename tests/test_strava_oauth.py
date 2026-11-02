"""Exercise the Strava authorization helpers, token refresh and the
CLI's .env-backed token store."""

import asyncio

import pytest
import responses

from liftostrava.cli.env_store import EnvFileTokenStore
from liftostrava.strava import oauth
from liftostrava.tokens import StravaTokens

strava_oauth = oauth.StravaOAuth("cid", "csecret")


def test_authorize_url_includes_client_id_and_scope():
    url = oauth.StravaOAuth("my-client-id", "s").authorize_url()

    assert url.startswith("https://www.strava.com/oauth/authorize?")
    assert "client_id=my-client-id" in url
    assert f"redirect_uri={oauth.REDIRECT_URI}" in url
    assert f"scope={oauth.SCOPE}" in url


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("http://localhost/exchange_token?state=&code=abc123&scope=read", "abc123"),
        ("abc123", "abc123"),
    ],
)
def test_extract_code_handles_full_url_and_bare_code(raw, expected):
    assert oauth.extract_code(raw) == expected


@responses.activate
def test_exchange_code_returns_tokens_and_athlete():
    responses.add(
        responses.POST,
        "https://www.strava.com/oauth/token",
        json={
            "access_token": "access-token",
            "refresh_token": "initial-refresh",
            "expires_at": 99,
            "athlete": {"firstname": "Tome"},
        },
        status=200,
    )

    authorization = strava_oauth.exchange_code("auth-code")

    assert authorization.athlete["firstname"] == "Tome"
    assert authorization.tokens == StravaTokens("access-token", "initial-refresh", 99)
    assert b"grant_type=authorization_code" in responses.calls[0].request.body.encode()


@responses.activate
def test_refresh_returns_the_rotated_tokens():
    responses.add(
        responses.POST,
        "https://www.strava.com/oauth/token",
        json={
            "access_token": "new-access",
            "refresh_token": "rotated-refresh",
            "expires_at": 1234567890,
        },
        status=200,
    )

    tokens = strava_oauth.refresh("old-refresh")

    assert tokens == StravaTokens("new-access", "rotated-refresh", 1234567890)


@responses.activate
def test_refresh_keeps_the_sent_refresh_token_when_strava_omits_one():
    responses.add(
        responses.POST,
        "https://www.strava.com/oauth/token",
        json={"access_token": "new-access", "expires_at": 1234567890},
        status=200,
    )

    assert strava_oauth.refresh("sent-refresh").refresh_token == "sent-refresh"


def test_access_token_validity_respects_the_refresh_threshold():
    tokens = StravaTokens("a", "r", expires_at=10_000)

    assert tokens.access_token_is_valid(now=10_000 - 2 * 3600)
    assert not tokens.access_token_is_valid(now=10_000 - 60)
    assert not StravaTokens("", "r", 0).access_token_is_valid()


def test_env_store_persists_a_rotated_refresh_token(tmp_path):
    # A real .env file rather than a mocked set_key: this verifies the
    # actual persisted state, not just that some function was called.
    env_file = tmp_path / ".env"
    env_file.write_text("STRAVA_REFRESH_TOKEN=old-refresh\n")

    asyncio.run(EnvFileTokenStore(env_file).save(StravaTokens("a", "rotated", 1)))

    assert "STRAVA_REFRESH_TOKEN='rotated'" in env_file.read_text()


def test_env_store_skips_rewrite_when_refresh_token_is_unchanged(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("STRAVA_REFRESH_TOKEN=same-refresh\n")
    before = env_file.read_text()

    asyncio.run(EnvFileTokenStore(env_file).save(StravaTokens("a", "same-refresh", 1)))

    # No rewrite at all — not even a reformatted but value-equal line.
    assert env_file.read_text() == before


def test_env_store_loads_the_refresh_token_from_the_environment(monkeypatch, tmp_path):
    store = EnvFileTokenStore(tmp_path / ".env")
    monkeypatch.delenv("STRAVA_REFRESH_TOKEN", raising=False)
    assert asyncio.run(store.load()) is None

    monkeypatch.setenv("STRAVA_REFRESH_TOKEN", "from-env")
    tokens = asyncio.run(store.load())
    assert tokens is not None
    assert tokens.refresh_token == "from-env"
    assert not tokens.access_token_is_valid()
