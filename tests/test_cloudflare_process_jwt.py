from cloudflare.process_jwt import AccessPrincipal, principal_from_claims


def test_principal_from_claims_normalizes_human_email():
    principal = principal_from_claims({"email": " Person@Example.com "})

    assert principal == AccessPrincipal(email="person@example.com")


def test_principal_from_claims_uses_service_token_client_id():
    principal = principal_from_claims({"common_name": "abc123.access", "sub": ""})

    assert principal == AccessPrincipal(service_token_id="abc123.access")


def test_principal_from_claims_rejects_non_service_common_name():
    principal = principal_from_claims(
        {"common_name": "certificate.example.com", "sub": "user-id"}
    )

    assert principal is None


def test_principal_from_claims_rejects_missing_identity():
    assert principal_from_claims({"sub": "user-id"}) is None
