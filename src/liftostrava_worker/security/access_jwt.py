import base64
import binascii
import json
import logging
import re
import time
from typing import Any

from pyodide.ffi import JsException

from liftostrava_worker.storage.models import AccessIDKey

logger = logging.getLogger(__name__)

JWKS_CACHE_TTL_SECONDS = 3600
# issuer -> (fetched_at, jwks). Module-level, so it lives as long as the
# Worker isolate does; a rotated key just means a cache miss on `kid`.
_jwks_cache: dict[str, tuple[float, Any]] = {}


def get_id_key_from_claims(claims: dict[str, Any]) -> AccessIDKey | None:
    common_name = claims.get("common_name")
    if common_name is not None:
        if (
            isinstance(common_name, str)
            and common_name.endswith(".access")
            and claims.get("sub") == ""
        ):
            return AccessIDKey(service_token_id=common_name)
        logger.warning("Unsupported Cloudflare Access token identity")
        return None

    email = claims.get("email")
    if isinstance(email, str) and email.strip():
        return AccessIDKey(email=email.strip().lower())

    logger.warning("Cloudflare Access token has no supported identity")
    return None


async def process_jwt(
    assertion: str,
    team_domain: str,
    expected_audience: str,
) -> AccessIDKey | None:
    team_domain = team_domain.strip().rstrip("/")
    if team_domain.startswith("https://"):
        issuer = team_domain
    elif "://" not in team_domain:
        issuer = f"https://{team_domain}"
    else:
        logger.error("Cloudflare Access team domain must use HTTPS")
        return None

    try:
        segments = assertion.split(".")
        if len(segments) != 3:
            raise ValueError("Malformed JWT")
        encoded_header, encoded_payload, encoded_signature = segments
        header = json.loads(_decode_jwt_segment(encoded_header))
        claims = json.loads(_decode_jwt_segment(encoded_payload))
        signature = _decode_jwt_segment(encoded_signature)
        if not isinstance(header, dict) or not isinstance(claims, dict):
            raise TypeError("JWT header and claims must be objects")
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise ValueError("Unsupported JWT signing algorithm")

        from js import (  # pyright: ignore[reportMissingImports]
            Object,
            Uint8Array,
            crypto,
        )
        from pyodide.ffi import to_js
        from workers import fetch

        cached = _jwks_cache.get(issuer)
        if cached is not None and time.time() - cached[0] < JWKS_CACHE_TTL_SECONDS:
            jwks = cached[1]
        else:
            keys_response = await fetch(f"{issuer}/cdn-cgi/access/certs")
            keys_response.raise_for_status()
            jwks = json.loads(await keys_response.text())
            _jwks_cache[issuer] = (time.time(), jwks)
        keys = jwks.get("keys") if isinstance(jwks, dict) else None
        if not isinstance(keys, list):
            raise TypeError("Invalid Access signing keys")
        signing_key = next(
            (
                key
                for key in keys
                if isinstance(key, dict)
                and key.get("kid") == header["kid"]
                and key.get("kty") == "RSA"
                and key.get("use", "sig") == "sig"
                and key.get("alg", "RS256") == "RS256"
            ),
            None,
        )
        if signing_key is None:
            _jwks_cache.pop(issuer, None)
            logger.warning("No matching Cloudflare Access signing key")
            return None

        import_algorithm = to_js(
            {"name": "RSASSA-PKCS1-v1_5", "hash": "SHA-256"},
            dict_converter=Object.fromEntries,
        )
        crypto_key = await crypto.subtle.importKey(
            "jwk",
            to_js(signing_key, dict_converter=Object.fromEntries),
            import_algorithm,
            False,
            to_js(["verify"]),
        )
        valid_signature = await crypto.subtle.verify(
            to_js(
                {"name": "RSASSA-PKCS1-v1_5"},
                dict_converter=Object.fromEntries,
            ),
            crypto_key,
            _to_uint8_array(signature, Uint8Array),
            _to_uint8_array(
                f"{encoded_header}.{encoded_payload}".encode("ascii"),
                Uint8Array,
            ),
        )
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        binascii.Error,
        JsException,
    ) as error:
        logger.warning(
            "Cloudflare Access JWT validation failed (%s)",
            type(error).__name__,
        )
        return None

    if not valid_signature:
        logger.warning("Cloudflare Access JWT signature is invalid")
        return None

    audience = claims.get("aud")
    if isinstance(audience, str):
        audience = [audience]
    if (
        claims.get("iss") != issuer
        or claims.get("type") != "app"
        or not isinstance(audience, list)
        or expected_audience not in audience
    ):
        logger.warning("Cloudflare Access JWT issuer or audience is invalid")
        return None

    now = time.time()
    expires_at = claims.get("exp")
    not_before = claims.get("nbf", 0)
    if (
        not isinstance(expires_at, (int, float))
        or isinstance(expires_at, bool)
        or expires_at <= now
        or not isinstance(not_before, (int, float))
        or isinstance(not_before, bool)
        or not_before > now
    ):
        logger.warning("Cloudflare Access JWT is expired or not yet valid")
        return None

    return get_id_key_from_claims(claims)


def _decode_jwt_segment(segment: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", segment):
        raise ValueError("Invalid base64url JWT segment")
    return base64.b64decode(
        segment + "=" * (-len(segment) % 4),
        altchars=b"-_",
        validate=True,
    )


def _to_uint8_array(value: bytes, uint8_array: Any) -> Any:
    result = uint8_array.new(len(value))
    for index, byte in enumerate(value):
        result[index] = byte
    return result
