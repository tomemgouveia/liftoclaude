"""AES-GCM encryption for the secrets stored in D1 (Liftosaur API keys,
Strava tokens), using the Workers runtime's WebCrypto. The key is derived
from the CREDENTIALS_SECRET worker secret (base64, 32 random bytes), so a
D1 export alone doesn't reveal anything usable.

Stored format: "v1:<b64 iv>:<b64 ciphertext>". Values without that prefix
are legacy plaintext and are returned unchanged by decrypt(), so rows
written before encryption keep working until they're next saved."""

import base64
import hashlib
import hmac
import os
from typing import Any

PREFIX = "v1:"
AES_LABEL = b"credentials-aes-gcm"
STATE_LABEL = b"oauth-state"


def derive_key(master_b64: str, label: bytes) -> bytes:
    """A purpose-specific key, so the same secret never serves two uses."""
    return hmac.new(base64.b64decode(master_b64), label, hashlib.sha256).digest()


def _to_uint8_array(value: bytes) -> Any:
    from js import Uint8Array  # pyright: ignore[reportMissingImports]

    result = Uint8Array.new(len(value))
    for index, byte in enumerate(value):
        result[index] = byte
    return result


def _algorithm(**fields: Any) -> Any:
    from js import Object  # pyright: ignore[reportMissingImports]
    from pyodide.ffi import to_js

    return to_js(fields, dict_converter=Object.fromEntries)


async def _import_key(key: bytes, usage: str) -> Any:
    from js import crypto  # pyright: ignore[reportMissingImports]
    from pyodide.ffi import to_js

    return await crypto.subtle.importKey(
        "raw",
        _to_uint8_array(key),
        _algorithm(name="AES-GCM"),
        False,
        to_js([usage]),
    )


async def encrypt(plaintext: str, key: bytes) -> str:
    from js import crypto  # pyright: ignore[reportMissingImports]

    iv = os.urandom(12)
    ciphertext = await crypto.subtle.encrypt(
        _algorithm(name="AES-GCM", iv=_to_uint8_array(iv)),
        await _import_key(key, "encrypt"),
        _to_uint8_array(plaintext.encode()),
    )
    encoded_iv = base64.b64encode(iv).decode()
    encoded_ct = base64.b64encode(bytes(ciphertext.to_py())).decode()
    return f"{PREFIX}{encoded_iv}:{encoded_ct}"


async def decrypt(value: str, key: bytes) -> str:
    if not value.startswith(PREFIX):
        return value
    from js import crypto  # pyright: ignore[reportMissingImports]

    encoded_iv, _, encoded_ct = value[len(PREFIX) :].partition(":")
    plaintext = await crypto.subtle.decrypt(
        _algorithm(name="AES-GCM", iv=_to_uint8_array(base64.b64decode(encoded_iv))),
        await _import_key(key, "decrypt"),
        _to_uint8_array(base64.b64decode(encoded_ct)),
    )
    return bytes(plaintext.to_py()).decode()
