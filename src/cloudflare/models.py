import time
from dataclasses import dataclass

STRAVA_REFRESH_THRESHOLD_SECONDS = 3600


@dataclass(frozen=True)
class AccessIDKey:
    email: str | None = None
    service_token_id: str | None = None


@dataclass
class User:
    user_id: str
    email: str
    name: str
    has_credentials: bool
    liftosaur_api_key: str | None = None

    # the strava access token allows the worker to make strava API calls
    strava_access_token: str | None = None
    # the strava refresh token allows the worker to refresh the access token
    # without having to sign in again
    strava_refresh_token: str | None = None
    strava_expires_at: int | None = None

    def is_strava_access_token_valid(self) -> bool:
        if self.strava_access_token and self.strava_expires_at:
            return (
                self.strava_expires_at > time.time() + STRAVA_REFRESH_THRESHOLD_SECONDS
            )
        return False
