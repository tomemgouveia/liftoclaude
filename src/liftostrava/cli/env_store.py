"""TokenStore for the CLI: the refresh token lives in .env."""

import os
from pathlib import Path

from dotenv import get_key, set_key

from liftostrava.tokens import StravaTokens

KEY = "STRAVA_REFRESH_TOKEN"


def save_refresh_token(env_path: str | Path, refresh_token: str) -> None:
    """Skips the write when the value is unchanged."""
    if refresh_token != get_key(env_path, KEY):
        set_key(env_path, KEY, refresh_token)


class EnvFileTokenStore:
    """Only the refresh token is persisted; the access token and expiry
    are re-derived from it on every run, so `load` always returns an
    already-expired access token."""

    def __init__(self, env_path: str | Path):
        self.env_path = env_path

    async def load(self) -> StravaTokens | None:
        refresh_token = os.getenv(KEY)
        if not refresh_token:
            return None
        return StravaTokens(access_token="", refresh_token=refresh_token, expires_at=0)

    async def save(self, tokens: StravaTokens) -> None:
        # Strava rotates refresh tokens on some accounts; persist the latest.
        save_refresh_token(self.env_path, tokens.refresh_token)
