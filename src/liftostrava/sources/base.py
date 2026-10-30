"""A WorkoutSource is anything that can produce a Workout. strava/ only
ever depends on this interface, not on how a given source gets its data —
that's what lets a second route (sources/api.py, hitting Liftosaur's REST
API directly) sit alongside mcp_export.py without touching anything
downstream.
"""

from dataclasses import dataclass
from typing import Protocol

from liftostrava.models import Workout


class WorkoutSource(Protocol):
    def load(self) -> Workout: ...


@dataclass
class WorkoutEntry:
    """One entry from a WorkoutSource's list_history(): `identifier` is
    whatever a source's own constructor takes to load that same workout
    again — SourceClass(identifier).load() — a stringified file path for
    McpExportSource, a Liftosaur record id for LiftosaurApiSource. Both
    constructors already take a single string (or, for McpExportSource,
    a Path — which stringifies to the same thing), so one shared type
    covers both rather than each source needing its own Entry shape.
    Paired with the already-parsed `workout` so callers usually don't
    need to load() again at all.
    """

    identifier: str
    workout: Workout
