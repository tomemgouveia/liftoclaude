"""Locks in refresh_access_token()'s token-rotation handling: it persists
a rotated refresh_token, but only writes to .env when Strava actually
returned a different one than it was given."""

import responses
from liftostrava.strava import auth


@responses.activate
def test_refresh_access_token_persists_a_rotated_refresh_token(monkeypatch):
    responses.add(
        responses.POST,
        "https://www.strava.com/oauth/token",
        json={"access_token": "new-access", "refresh_token": "rotated-refresh"},
        status=200,
    )
    set_key_calls = []
    monkeypatch.setattr(
        auth, "set_key", lambda path, key, value: set_key_calls.append((key, value))
    )

    token = auth.refresh_access_token("cid", "csecret", "old-refresh")

    assert token == "new-access"
    assert set_key_calls == [("STRAVA_REFRESH_TOKEN", "rotated-refresh")]


@responses.activate
def test_refresh_access_token_skips_rewrite_when_refresh_token_is_unchanged(
    monkeypatch,
):
    responses.add(
        responses.POST,
        "https://www.strava.com/oauth/token",
        json={"access_token": "new-access", "refresh_token": "same-refresh"},
        status=200,
    )
    set_key_calls = []
    monkeypatch.setattr(auth, "set_key", lambda *a: set_key_calls.append(a))

    auth.refresh_access_token("cid", "csecret", "same-refresh")

    assert set_key_calls == []
