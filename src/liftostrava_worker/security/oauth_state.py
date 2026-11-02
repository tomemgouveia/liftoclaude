"""Signed, expiring `state` values for the Strava OAuth round trip, so the
callback can prove it answers a redirect this worker started for that
user. Stdlib only (hmac works under Pyodide), so it's unit-testable."""

import base64
import hashlib
import hmac
import json
import time

STATE_TTL_SECONDS = 600


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(payload: str, key: bytes) -> str:
    return _b64(hmac.new(key, payload.encode("ascii"), hashlib.sha256).digest())


def sign_state(user_id: str, key: bytes, now: float | None = None) -> str:
    expires_at = int((time.time() if now is None else now) + STATE_TTL_SECONDS)
    payload = _b64(json.dumps({"u": user_id, "e": expires_at}).encode())
    return f"{payload}.{_signature(payload, key)}"


def verify_state(state: str, key: bytes, now: float | None = None) -> str | None:
    """The user id the state was signed for, or None if it's malformed,
    forged or expired."""
    payload, _, signature = state.partition(".")
    if not payload or not hmac.compare_digest(signature, _signature(payload, key)):
        return None
    try:
        claims = json.loads(_unb64(payload))
        user_id, expires_at = claims["u"], claims["e"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(user_id, str) or not isinstance(expires_at, int):
        return None
    if expires_at <= (time.time() if now is None else now):
        return None
    return user_id
