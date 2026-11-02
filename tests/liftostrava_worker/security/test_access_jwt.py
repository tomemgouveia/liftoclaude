from liftostrava_worker.security.access_jwt import AccessIDKey, get_id_key_from_claims


def test_get_id_key_from_claims_normalizes_human_email():
    principal = get_id_key_from_claims({"email": " Person@Example.com "})

    assert principal == AccessIDKey(email="person@example.com")


def test_get_id_key_from_claims_uses_service_token_client_id():
    principal = get_id_key_from_claims({"common_name": "abc123.access", "sub": ""})

    assert principal == AccessIDKey(service_token_id="abc123.access")


def test_get_id_key_from_claims_rejects_non_service_common_name():
    principal = get_id_key_from_claims(
        {"common_name": "certificate.example.com", "sub": "user-id"}
    )

    assert principal is None


def test_get_id_key_from_claims_rejects_missing_identity():
    assert get_id_key_from_claims({"sub": "user-id"}) is None
