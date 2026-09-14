#!/bin/bash
# Installs the liftostrava package into a local .venv so `sync-to-strava` /
# `strava-auth` are ready to go at the start of a Claude Code on the web
# session, instead of Claude having to do it by hand every time.
#
# Only runs in remote (Claude Code on the web) sessions — local sessions
# are expected to have already run the one-time setup in README.md.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# liftostrava requires Python >=3.11 (see liftostrava/pyproject.toml); the
# image's default `python3` satisfies that.
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi

# pip install -e is idempotent/fast on repeat runs (no-op if unchanged), so
# it's safe to always run rather than trying to detect "already installed".
.venv/bin/pip install -q -e "./liftostrava[dev]"

# Put the venv's scripts (sync-to-strava, strava-auth, pytest, ruff, ...) on
# PATH for the rest of the session, so no `source .venv/bin/activate` needed.
echo "export PATH=\"$CLAUDE_PROJECT_DIR/.venv/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
