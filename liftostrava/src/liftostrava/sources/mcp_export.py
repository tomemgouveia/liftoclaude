"""Today's only WorkoutSource: the JSON file written into workouts/ after
fetching a record over the Liftosaur MCP server (see CLAUDE.md in the repo
root, which drives that fetch-and-write step — this module only parses the
result).

Expected shape (already filtered to completed/actual sets only — CLAUDE.md
is responsible for dropping `warmup:`/`target:` sets before this file is
written, not this module):

    {
      "name": "Fierce 5 - Workout A",
      "start_time": "2026-08-24T16:56:02Z",
      "elapsed_time": 1868,
      "utc_offset": 3600,               // optional
      "description": "optional free text",
      "exercises": [
        {"name": "Squat", "sets": [{"reps": 5, "weight_kg": 60}, ...]},
        ...
      ]
    }
"""

import json
from pathlib import Path

from liftostrava.models import Exercise, Set, Workout


class McpExportSource:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> Workout:
        with open(self.path) as f:
            data = json.load(f)

        exercises = [
            Exercise(
                name=exercise["name"],
                sets=[
                    Set(reps=s["reps"], weight_kg=s["weight_kg"])
                    for s in exercise["sets"]
                ],
            )
            for exercise in data["exercises"]
        ]
        return Workout(
            start_time=data["start_time"],
            elapsed_time=data["elapsed_time"],
            exercises=exercises,
            name=data.get("name"),
            description=data.get("description"),
            utc_offset=data.get("utc_offset"),
        )
