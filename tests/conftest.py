import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def sample_workout():
    """A fresh copy of sample_workout.json for each test, so tests that
    mutate it (e.g. adding utc_offset) can't leak into other tests."""
    with open(REPO_ROOT / "sample_workout.json") as f:
        return json.load(f)
