"""Locks in the pure parts of the /connect onboarding flow: OAuth state
signing, the page's escaping/status handling, and the legacy-plaintext
passthrough of credential decryption. (The WebCrypto encrypt path and the
worker routes need the Workers runtime and aren't covered here.)"""

import asyncio
import base64

from cloudflare.connect_page import STATUS_MESSAGES, render_connect_page
from cloudflare.credential_crypto import STATE_LABEL, decrypt, derive_key
from cloudflare.oauth_state import STATE_TTL_SECONDS, sign_state, verify_state
from liftostrava.strava import auth

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


def test_page_escapes_user_supplied_values():
    html = render_connect_page(
        email='<script>alert(1)</script>"',
        liftosaur_set=False,
        strava_connected=False,
        timezone='"><img src=x>',
    )

    assert "<script>alert(1)" not in html
    assert "<img src=x>" not in html


def test_page_shows_a_known_status_and_ignores_unknown_ones():
    known = render_connect_page("a@b.c", True, True, "Europe/London", "bad_key")
    unknown = render_connect_page("a@b.c", True, True, None, "<b>injected</b>")

    assert STATUS_MESSAGES["bad_key"][0] in known
    assert "injected" not in unknown


def test_authorize_url_supports_a_custom_redirect_and_state():
    url = auth.build_authorize_url(
        "cid", "https://w.example/connect/strava/callback", "a.b"
    )

    assert "redirect_uri=https://w.example/connect/strava/callback" in url
    assert "state=a.b" in url
