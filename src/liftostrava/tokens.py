"""Strava tokens and where they are kept. SyncService only needs to load
and save them; the CLI keeps the refresh token in .env (cli/env_store.py)
and the worker keeps the pair per user in D1."""

import time
from dataclasses import dataclass
from typing import Protocol

# Refresh the access token this long before it actually expires.
REFRESH_THRESHOLD_S = 3600


@dataclass(frozen=True)
class StravaTokens:
    access_token: str
    refresh_token: str
    expires_at: int

    def access_token_is_valid(self, now: float | None = None) -> bool:
        if not self.access_token or not self.expires_at:
            return False
        current = time.time() if now is None else now
        return self.expires_at > current + REFRESH_THRESHOLD_S


class TokenStore(Protocol):
    async def load(self) -> StravaTokens | None: ...

    async def save(self, tokens: StravaTokens) -> None: ...
