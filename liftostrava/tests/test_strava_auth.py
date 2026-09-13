"""Locks in strava/auth.py: build_authorize_url/extract_code (the pure
pieces of the one-time interactive authorization flow, pulled out into
standalone functions specifically so they could be tested directly), and
refresh_access_token/exchange_authorization_code's token-rotation
handling — both persist to a real .env file, but only write when Strava
actually returned a different refresh_token than they were given."""

import pytest
import responses
from liftostrava.strava import auth


def test_build_authorize_url_includes_client_id_and_scope():
    url = auth.build_authorize_url("my-client-id")

    assert url.startswith("https://www.strava.com/oauth/authorize?")
    assert "client_id=my-client-id" in url
    assert f"redirect_uri={auth.REDIRECT_URI}" in url
    assert f"scope={auth.SCOPE}" in url


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("http://localhost/exchange_token?state=&code=abc123&scope=read", "abc123"),
        ("abc123", "abc123"),
    ],
)
def test_extract_code_handles_full_url_and_bare_code(raw, expected):
    assert auth.extract_code(raw) == expected


@responses.activate
def test_exchange_authorization_code_persists_the_refresh_token(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("")
    monkeypatch.setattr(auth, "ENV_PATH", str(env_file))
    responses.add(
        responses.POST,
        "https://www.strava.com/oauth/token",
        json={
            "access_token": "access-token",
            "refresh_token": "initial-refresh",
            "athlete": {"firstname": "Tome"},
        },
        status=200,
    )

    tokens = auth.exchange_authorization_code("cid", "csecret", "auth-code")

    assert tokens["athlete"]["firstname"] == "Tome"
    assert "STRAVA_REFRESH_TOKEN='initial-refresh'" in env_file.read_text()


@responses.activate
def test_refresh_access_token_persists_a_rotated_refresh_token(tmp_path, monkeypatch):
    # A real .env file rather than a mocked set_key: this verifies the
    # actual persisted state, not just that some function was called with
    # arguments that looked right.
    env_file = tmp_path / ".env"
    env_file.write_text("STRAVA_REFRESH_TOKEN=old-refresh\n")
    monkeypatch.setattr(auth, "ENV_PATH", str(env_file))
    responses.add(
        responses.POST,
        "https://www.strava.com/oauth/token",
        json={"access_token": "new-access", "refresh_token": "rotated-refresh"},
        status=200,
    )

    token = auth.refresh_access_token("cid", "csecret", "old-refresh")

    assert token == "new-access"
    assert "STRAVA_REFRESH_TOKEN='rotated-refresh'" in env_file.read_text()


@responses.activate
def test_refresh_access_token_skips_rewrite_when_refresh_token_is_unchanged(
    tmp_path, monkeypatch
):
    env_file = tmp_path / ".env"
    env_file.write_text("STRAVA_REFRESH_TOKEN=same-refresh\n")
    monkeypatch.setattr(auth, "ENV_PATH", str(env_file))
    before = env_file.read_text()
    responses.add(
        responses.POST,
        "https://www.strava.com/oauth/token",
        json={"access_token": "new-access", "refresh_token": "same-refresh"},
        status=200,
    )

    auth.refresh_access_token("cid", "csecret", "same-refresh")

    # No rewrite at all — not even a reformatted but value-equal line.
    assert env_file.read_text() == before
