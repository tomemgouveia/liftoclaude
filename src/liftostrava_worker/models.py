from dataclasses import dataclass

from liftostrava.tokens import StravaTokens


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
    # IANA name (e.g. "Europe/London") used for Strava's local start time;
    # None falls back to service.DEFAULT_TIMEZONE.
    timezone: str | None = None

    # the strava access token allows the worker to make strava API calls
    strava_access_token: str | None = None
    # the strava refresh token allows the worker to refresh the access token
    # without having to sign in again
    strava_refresh_token: str | None = None
    strava_expires_at: int | None = None

    def strava_tokens(self) -> StravaTokens | None:
        if not self.strava_refresh_token:
            return None
        return StravaTokens(
            access_token=self.strava_access_token or "",
            refresh_token=self.strava_refresh_token,
            expires_at=self.strava_expires_at or 0,
        )
