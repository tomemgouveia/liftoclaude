"""Strava OAuth: the one-time interactive authorization flow (see
cli/auth.py) and the per-run access-token refresh (see cli/sync.py and
strava/client.py)."""

import re

import requests
from dotenv import set_key

from liftostrava.config import ENV_PATH

SCOPE = "activity:write,activity:read_all"
REDIRECT_URI = "http://localhost/exchange_token"


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
    """One-time exchange of an authorization code for tokens. Raises via
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
    )
    resp.raise_for_status()
    tokens = resp.json()
    set_key(ENV_PATH, "STRAVA_REFRESH_TOKEN", tokens["refresh_token"])
    return tokens


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    resp = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    resp.raise_for_status()
    data = resp.json()
    # Strava rotates refresh tokens on some accounts; persist the latest.
    if data.get("refresh_token") and data["refresh_token"] != refresh_token:
        set_key(ENV_PATH, "STRAVA_REFRESH_TOKEN", data["refresh_token"])
    return data["access_token"]
