"""Per-request wiring: the Worker env bindings, derived secret keys, and
the services built from them."""

from typing import Any

from liftostrava.strava.oauth import StravaOAuth
from liftostrava_worker.security.crypto import AES_LABEL, derive_key
from liftostrava_worker.storage.repository import UserRepository


class AppContext:
    def __init__(self, env: Any):
        self.env = env

    def secret_key(self, label: bytes) -> bytes:
        master = self.env.CREDENTIALS_SECRET
        if not isinstance(master, str) or not master:
            raise RuntimeError("CREDENTIALS_SECRET is not configured")
        return derive_key(master, label)

    @property
    def repo(self) -> UserRepository:
        return UserRepository(
            self.env.liftosaur_strava_sync_users, self.secret_key(AES_LABEL)
        )

    @property
    def strava_oauth(self) -> StravaOAuth:
        return StravaOAuth(self.env.STRAVA_CLIENT_ID, self.env.STRAVA_CLIENT_SECRET)
