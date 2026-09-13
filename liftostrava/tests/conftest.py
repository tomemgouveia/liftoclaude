from pathlib import Path

import pytest
from liftostrava.sources.mcp_export import McpExportSource

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def sample_workout():
    """A fresh Workout parsed from fixtures/sample_workout.json for each
    test, so tests that mutate it (e.g. setting utc_offset) can't leak
    into other tests."""
    return McpExportSource(FIXTURES / "sample_workout.json").load()
