"""Shared config: where .env lives, and the credentials read from it.

.env stays at the repo root (liftoclaude/.env), not inside this package,
since it's runtime config rather than code. This file's own location is
liftoclaude/liftostrava/src/liftostrava/config.py, so the repo root is
three parents up — that holds for an editable install from this checkout
(the only way this personal tool is meant to run; it isn't published
anywhere __file__ would point outside the checkout).
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = REPO_ROOT / ".env"
# CLAUDE.md's scratch space for hand-transcribed workout JSON files (see
# sources/mcp_export.py's list_history) — gitignored, not an archive.
WORKOUTS_DIR = REPO_ROOT / "workouts"
