"""A WorkoutSource is anything that can produce a Workout. strava/ only
ever depends on this interface, not on how a given source gets its data —
that's what lets a second route (e.g. sources/liftosaur_api.py, hitting
Liftosaur's REST API directly) sit alongside mcp_export.py later without
touching anything downstream.
"""

from typing import Protocol

from liftostrava.models import Workout


class WorkoutSource(Protocol):
    def load(self) -> Workout: ...
