from liftostrava.tokens import StravaTokens


def test_access_token_validity_respects_the_refresh_threshold():
    tokens = StravaTokens("a", "r", expires_at=10_000)

    assert tokens.access_token_is_valid(now=10_000 - 2 * 3600)
    assert not tokens.access_token_is_valid(now=10_000 - 60)
    assert not StravaTokens("", "r", 0).access_token_is_valid()
