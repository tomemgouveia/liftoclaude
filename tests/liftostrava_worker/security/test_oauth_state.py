"""OAuth state signing for the /connect flow."""

import base64

from liftostrava_worker.security.oauth_state import (
    STATE_TTL_SECONDS,
    sign_state,
    verify_state,
)

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
