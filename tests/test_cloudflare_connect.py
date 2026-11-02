"""Locks in the pure parts of the /connect onboarding flow: OAuth state
signing and the legacy-plaintext
passthrough of credential decryption. (The WebCrypto encrypt path and the
worker routes need the Workers runtime and aren't covered here.)"""

import asyncio
import base64

from cloudflare.credential_crypto import STATE_LABEL, decrypt, derive_key
from cloudflare.oauth_state import STATE_TTL_SECONDS, sign_state, verify_state
from liftostrava.strava.oauth import StravaOAuth

KEY = b"k" * 32


def test_state_round_trips_to_the_signed_user():
    state = sign_state("user-1", KEY, now=1000)

    assert verify_state(state, KEY, now=1001) == "user-1"


def test_state_expires():
    state = sign_state("user-1", KEY, now=1000)

    assert verify_state(state, KEY, now=1000 + STATE_TTL_SECONDS + 1) is None


def test_state_signed_with_another_key_is_rejected():
    assert (
        verify_state(sign_state("user-1", b"x" * 32, now=1000), KEY, now=1001) is None
    )


def test_tampered_state_is_rejected():
    payload, _, signature = sign_state("user-1", KEY, now=1000).partition(".")
    forged = base64.urlsafe_b64encode(b'{"u": "admin", "e": 9999999999}').decode()

    assert verify_state(f"{forged}.{signature}", KEY, now=1001) is None
    assert verify_state(payload, KEY, now=1001) is None


def test_garbage_state_is_rejected():
    for state in ["", ".", "abc", "a.b"]:
        assert verify_state(state, KEY, now=1) is None


def test_derived_keys_differ_by_label():
    master = base64.b64encode(b"m" * 32).decode()

    assert derive_key(master, STATE_LABEL) != derive_key(master, b"other")
    assert len(derive_key(master, STATE_LABEL)) == 32


def test_decrypt_returns_legacy_plaintext_unchanged():
    assert asyncio.run(decrypt("plain-api-key", KEY)) == "plain-api-key"


def test_authorize_url_supports_a_custom_redirect_and_state():
    url = StravaOAuth("cid", "secret").authorize_url(
        "https://w.example/connect/strava/callback", "a.b"
    )

    assert "redirect_uri=https://w.example/connect/strava/callback" in url
    assert "state=a.b" in url


def test_history_range_defaults_to_last_week_in_user_timezone():
    from datetime import UTC, datetime

    from cloudflare.history_range import parse_history_range

    now = datetime(2026, 11, 1, 23, 30, tzinfo=UTC)
    start, end = parse_history_range({}, "Asia/Tokyo", now=now)

    assert start == datetime(2026, 10, 26, 15, 0, tzinfo=UTC)  # Oct 27 00:00 JST
    assert end.date().isoformat() == "2026-11-02"


def test_history_range_rejects_bad_input():
    import pytest

    from cloudflare.history_range import HistoryRangeError, parse_history_range

    for params in (
        {"start": ["nope"]},
        {"start": ["2026-10-02"], "end": ["2026-10-01"]},
        {"start": ["2020-01-01"], "end": ["2026-01-01"]},
    ):
        with pytest.raises(HistoryRangeError):
            parse_history_range(params, None)


def test_workout_json_brief_is_id_name_date_only():
    from cloudflare.workout_json import workout_json
    from liftostrava.domain import Exercise, Set, Workout, WorkoutRecord

    entry = WorkoutRecord(
        id="42",
        workout=Workout(
            start_time="2026-10-31T09:00:00Z",
            elapsed_time=3600,
            exercises=[Exercise("Squat", [Set(5, 100.0), Set(5, 100.0)])],
            name="Lower Body Workout",
        ),
    )

    assert workout_json(entry, brief=True) == {
        "id": "42",
        "name": "Lower Body Workout",
        "date": "2026-10-31",
    }
    full = workout_json(entry, brief=False)
    assert full["duration_s"] == 3600
    assert full["exercises"] == [{"name": "Squat", "sets": 2}]
