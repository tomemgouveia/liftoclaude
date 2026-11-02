"""Exercise the Strava authorization helpers and token refresh."""

import pytest
import responses

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


def test_authorize_url_supports_a_custom_redirect_and_state():
    url = oauth.StravaOAuth("cid", "secret").authorize_url(
        "https://w.example/connect/strava/callback", "a.b"
    )

    assert "redirect_uri=https://w.example/connect/strava/callback" in url
    assert "state=a.b" in url
