"""Strava OAuth: the one-time interactive authorization (see cli/auth.py
and the worker's /connect flow) and the per-run access-token refresh."""

import re
from dataclasses import dataclass
from urllib.parse import quote

import requests

from liftostrava.tokens import StravaTokens

TOKEN_URL = "https://www.strava.com/oauth/token"
AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
REQUEST_TIMEOUT_S = 30
SCOPE = "activity:write,activity:read_all"
REDIRECT_URI = "http://localhost/exchange_token"


@dataclass(frozen=True)
class Authorization:
    tokens: StravaTokens
    athlete: dict


def extract_code(raw: str) -> str:
    """Accepts either a bare code or the full redirected localhost URL."""
    match = re.search(r"code=([^&]+)", raw)
    return match.group(1) if match else raw


class StravaOAuth:
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret

    def authorize_url(
        self, redirect_uri: str = REDIRECT_URI, state: str | None = None
    ) -> str:
        url = (
            f"{AUTHORIZE_URL}"
            f"?client_id={self.client_id}"
            f"&redirect_uri={redirect_uri}"
            "&response_type=code"
            "&approval_prompt=force"
            f"&scope={SCOPE}"
        )
        if state is not None:
            url += f"&state={quote(state, safe='')}"
        return url

    def _token_request(self, **fields: str) -> dict:
        resp = requests.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                **fields,
            },
            timeout=REQUEST_TIMEOUT_S,
        )
        resp.raise_for_status()
        return resp.json()

    def exchange_code(self, code: str) -> Authorization:
        """One-time exchange of an authorization code for tokens. Raises
        via raise_for_status() on failure; callers handle that with more
        specific guidance since the common causes are user-facing (stale
        code, wrong credentials)."""
        data = self._token_request(code=code, grant_type="authorization_code")
        return Authorization(
            tokens=StravaTokens(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                expires_at=data["expires_at"],
            ),
            athlete=data.get("athlete", {}),
        )

    def refresh(self, refresh_token: str) -> StravaTokens:
        data = self._token_request(
            refresh_token=refresh_token, grant_type="refresh_token"
        )
        return StravaTokens(
            access_token=data["access_token"],
            # Strava may omit a rotated token; keep using the one we sent.
            refresh_token=data.get("refresh_token", refresh_token),
            expires_at=data.get("expires_at", 0),
        )
