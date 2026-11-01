"""Strava OAuth: the one-time interactive authorization flow (see
cli/auth.py) and the per-run access-token refresh (see cli/sync.py and
strava/client.py)."""

import re
from dataclasses import dataclass

import requests

from liftostrava.config import ENV_PATH

REQUEST_TIMEOUT_S = 30
SCOPE = "activity:write,activity:read_all"
REDIRECT_URI = "http://localhost/exchange_token"


@dataclass
class StravaTokens:
    access_token: str
    refresh_token: str
    expires_at: int


def build_authorize_url(client_id: str) -> str:
    return (
        "https://www.strava.com/oauth/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={REDIRECT_URI}"
        "&response_type=code"
        "&approval_prompt=force"
        f"&scope={SCOPE}"
    )


def extract_code(raw: str) -> str:
    """Accepts either a bare code or the full redirected localhost URL."""
    match = re.search(r"code=([^&]+)", raw)
    return match.group(1) if match else raw


def exchange_authorization_code(client_id: str, client_secret: str, code: str) -> dict:
    """One-time exchange of an authorization code for tokens (the caller
    persists the refresh token — see save_refresh_token_to_env). Raises via
    raise_for_status() on failure; the caller (cli/auth.py) handles that
    with more specific guidance since the common causes are user-facing
    (stale code, wrong credentials)."""
    resp = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=REQUEST_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()


def refresh_strava_tokens(
    client_id: str, client_secret: str, refresh_token: str
) -> StravaTokens:
    resp = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=REQUEST_TIMEOUT_S,
    )
    resp.raise_for_status()
    data = resp.json()

    return StravaTokens(
        access_token=data.get("access_token"),
        # Strava may omit a rotated token; keep using the one we sent.
        refresh_token=data.get("refresh_token", refresh_token),
        expires_at=data.get("expires_at"),
    )


def save_refresh_token_to_env(refresh_token: str) -> None:
    """Persist the refresh token to .env (CLI only — the worker keeps
    tokens in D1). Skips the write when the value is unchanged. The
    access token and expiry aren't persisted: they're re-derived from
    the refresh token on every run."""
    from dotenv import get_key, set_key

    if refresh_token != get_key(ENV_PATH, "STRAVA_REFRESH_TOKEN"):
        set_key(ENV_PATH, "STRAVA_REFRESH_TOKEN", refresh_token)


def save_strava_tokens_to_env(tokens: StravaTokens) -> None:
    # Strava rotates refresh tokens on some accounts; persist the latest.
    save_refresh_token_to_env(tokens.refresh_token)
