"""Where the CLI's .env lives.

.env stays at the repo root (liftoclaude/.env), not inside this package,
since it's runtime config rather than code. This file's own location is
liftoclaude/src/liftostrava/cli/config.py, so the repo root is four
parents up — that holds for an editable install from this checkout
(the only way this personal tool is meant to run; it isn't published
anywhere __file__ would point outside the checkout). Set
LIFTOSAUR_DOTENV_PATH to override.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = Path(os.environ.get("LIFTOSAUR_DOTENV_PATH", REPO_ROOT / ".env"))
