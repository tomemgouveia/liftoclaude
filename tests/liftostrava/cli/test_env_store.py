"""The CLI's .env-backed TokenStore."""

import asyncio

from liftostrava.cli.env_store import EnvFileTokenStore
from liftostrava.tokens import StravaTokens


def test_env_store_persists_a_rotated_refresh_token(tmp_path):
    # A real .env file rather than a mocked set_key: this verifies the
    # actual persisted state, not just that some function was called.
    env_file = tmp_path / ".env"
    env_file.write_text("STRAVA_REFRESH_TOKEN=old-refresh\n")

    asyncio.run(EnvFileTokenStore(env_file).save(StravaTokens("a", "rotated", 1)))

    assert "STRAVA_REFRESH_TOKEN='rotated'" in env_file.read_text()


def test_env_store_skips_rewrite_when_refresh_token_is_unchanged(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("STRAVA_REFRESH_TOKEN=same-refresh\n")
    before = env_file.read_text()

    asyncio.run(EnvFileTokenStore(env_file).save(StravaTokens("a", "same-refresh", 1)))

    # No rewrite at all — not even a reformatted but value-equal line.
    assert env_file.read_text() == before


def test_env_store_loads_the_refresh_token_from_the_environment(monkeypatch, tmp_path):
    store = EnvFileTokenStore(tmp_path / ".env")
    monkeypatch.delenv("STRAVA_REFRESH_TOKEN", raising=False)
    assert asyncio.run(store.load()) is None

    monkeypatch.setenv("STRAVA_REFRESH_TOKEN", "from-env")
    tokens = asyncio.run(store.load())
    assert tokens is not None
    assert tokens.refresh_token == "from-env"
    assert not tokens.access_token_is_valid()
