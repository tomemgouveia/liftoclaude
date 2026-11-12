"""The one sync flow, shared by the CLI and the Cloudflare worker:
get a valid access token, upload the workout, wait for Strava to process
it, and mute it from the home feed. It never prints — callers decide how
to report progress and results."""

from collections.abc import Callable
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from liftostrava.domain import Workout
from liftostrava.errors import MissingCredentials
from liftostrava.strava.client import StravaClient
from liftostrava.strava.oauth import StravaOAuth
from liftostrava.strava.payload import (
    build_payload,
    upload_form_fields,
    utc_offset_at,
)
from liftostrava.tokens import StravaTokens, TokenStore

# The athlete's home timezone — used for Strava's start_date_local display
# when the caller doesn't supply one. A zoneinfo name, not a fixed offset,
# so it stays correct across BST/GMT transitions.
DEFAULT_TIMEZONE = ZoneInfo("Europe/London")


@dataclass(frozen=True)
class SyncResult:
    activity_id: int
    hidden_from_home: bool

    @property
    def url(self) -> str:
        return f"https://www.strava.com/activities/{self.activity_id}"


def resolve_utc_offset(workout: Workout, tz: ZoneInfo) -> int:
    if workout.utc_offset is not None:
        return workout.utc_offset
    return utc_offset_at(workout.start_time, tz)


def preview_upload(
    workout: Workout, tz: ZoneInfo = DEFAULT_TIMEZONE, hide_from_home: bool = True
) -> dict:
    """What sync() would send to Strava, without calling it or needing
    credentials. Built from the same functions the real upload uses, so
    the two can't diverge. The one display-only change: the (long) heart-rate
    arrays in `streams` are shown as a summary."""
    file_content = build_payload(workout, resolve_utc_offset(workout, tz))
    if "streams" in file_content:
        times = file_content["streams"]["time"]
        bpms = file_content["streams"]["heartrate"]
        file_content["streams"] = {
            "samples": len(times),
            "first_offset_s": times[0],
            "last_offset_s": times[-1],
            "min_bpm": min(bpms),
            "max_bpm": max(bpms),
        }
    return {
        "form_fields": upload_form_fields(workout),
        "file_content": file_content,
        "hide_from_home_after_upload": hide_from_home,
    }


class SyncService:
    def __init__(
        self,
        oauth: StravaOAuth,
        token_store: TokenStore,
        tz: ZoneInfo = DEFAULT_TIMEZONE,
        progress: Callable[[str], None] = lambda message: None,
    ):
        self.oauth = oauth
        self.token_store = token_store
        self.tz = tz
        self.progress = progress

    async def access_token(self) -> str:
        """Reuse a still-valid access token, or refresh and persist the
        (possibly rotated) pair."""
        tokens = await self.token_store.load()
        if tokens is None or not tokens.refresh_token:
            raise MissingCredentials("Strava is not connected")
        if tokens.access_token_is_valid():
            return tokens.access_token
        self.progress("Refreshing access token...")
        refreshed: StravaTokens = self.oauth.refresh(tokens.refresh_token)
        await self.token_store.save(refreshed)
        return refreshed.access_token

    async def sync(self, workout: Workout, hide_from_home: bool = True) -> SyncResult:
        client = StravaClient(await self.access_token())

        self.progress("Uploading workout...")
        upload_id = client.upload(workout, resolve_utc_offset(workout, self.tz))

        self.progress(
            f"Upload accepted (id={upload_id}), waiting for Strava to process it..."
        )
        activity_id = await client.wait_for_upload(upload_id)

        if hide_from_home:
            self.progress("Muting activity from home feed (hide_from_home=true)...")
            client.set_hide_from_home(activity_id, True)
        return SyncResult(activity_id, hide_from_home)
