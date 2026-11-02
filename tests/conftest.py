from pathlib import Path

import pytest

from liftostrava.liftosaur.mcp_export import load_workout

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def sample_workout():
    """A fresh Workout parsed from fixtures/sample_workout.json for each
    test, so tests can't leak state into each other."""
    return load_workout(FIXTURES / "sample_workout.json")
