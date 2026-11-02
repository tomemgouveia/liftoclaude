"""Key derivation and the legacy-plaintext passthrough of credential
decryption. (The WebCrypto encrypt path needs the Workers runtime and isn't
covered here.)"""

import asyncio
import base64

from liftostrava_worker.security.crypto import STATE_LABEL, decrypt, derive_key

KEY = b"k" * 32


def test_derived_keys_differ_by_label():
    master = base64.b64encode(b"m" * 32).decode()

    assert derive_key(master, STATE_LABEL) != derive_key(master, b"other")
    assert len(derive_key(master, STATE_LABEL)) == 32


def test_decrypt_returns_legacy_plaintext_unchanged():
    assert asyncio.run(decrypt("plain-api-key", KEY)) == "plain-api-key"
