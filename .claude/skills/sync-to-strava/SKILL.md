---
name: sync-to-strava
description: Sync a Liftosaur workout to Strava. Use when the user asks to push, sync or upload a Liftosaur workout or session (e.g. "push yesterday's workout to Strava", "sync my last session") to Strava.
---

# Liftosaur → Strava sync

**First, check whether `LIFTOSAUR_API_KEY` is set in `.env`** (repo root;
read the file, don't echo the key). That decides which flow to use.

## Flow A — `LIFTOSAUR_API_KEY` is set (preferred)

1. Use the Liftosaur MCP's `get_history` to find the record the user
   means (match by date/program/dayName as needed). You only need its
   **ID** — no transcription, no JSON file.

2. Run the CLI against that ID:

   ```
   uv run sync-to-strava --from-api <id>
   ```

   (If the environment isn't set up yet, run `uv sync` from the repo
   root — see `docs/setup.md`.)

   The CLI fetches and parses the record itself (`liftostrava/liftosaur/`):
   completed vs. `warmup:`/`target:` sets and unit handling are done in
   code, not by you.

3. Report the activity URL from the CLI's output.

If it reports a missing/invalid `LIFTOSAUR_API_KEY`, fall back to Flow B
for this request and tell the user the key needs fixing.

## Flow B — no `LIFTOSAUR_API_KEY` (fallback)

1. Use the Liftosaur MCP tools (`get_history` or `get_history_record`) to
   fetch the workout. Match by date if the user gave one.

2. Convert it into a JSON file of this shape:

   ```json
   {
     "name": "<Lower|Balanced|Upper> Body Workout",
     "start_time": "<ISO 8601 UTC timestamp from the record>",
     "elapsed_time": <duration in seconds>,
     "description": "Synced from Liftosaur",
     "exercises": [
       {"name": "<exercise name>", "sets": [{"reps": N, "weight_kg": N}, ...]}
     ]
   }
   ```

   `name` comes from the record's day name in the L/B/U program:

   | dayName  | name                  |
   | -------- | --------------------- |
   | Lower    | Lower Body Workout    |
   | Balanced | Balanced Body Workout |
   | Upper    | Upper Body Workout    |

   Only include **completed/actual** sets (what the user logged), never
   the `warmup:` or `target:` sets from the Liftohistory record.

   Save it under `workouts/` (create it if needed) as
   `workouts/<start_time with colons stripped>-<slugified name>.json`,
   e.g. `workouts/2026-08-24T165602Z-fierce-5-workout-a.json`. This is
   gitignored scratch space, not an archive: it holds personal exercise
   data that must not end up in the (public) repo.

3. Run the CLI on it:

   ```
   uv run sync-to-strava workouts/<the file you just wrote>.json
   ```

4. On success, delete the file (`rm workouts/<the file>.json`). Never
   `git add` or commit anything under `workouts/`. If the upload fails,
   leave the file so it can be retried or inspected.

5. Report the activity URL from the CLI's output.

## Privacy

By default the CLI mutes the activity from Strava's home feed
(`hide_from_home`). That is **not** "Only You" visibility, which the
Strava API cannot set (details: `src/liftostrava/cli/sync.py` docstring
and `docs/usage.md`). Pass `--public` only if the user explicitly asks
not to mute it. If they want a true "Only You" default, tell them to set
it once in the Strava app (Settings > Privacy Controls > Activities);
every upload then inherits it.

Use `--dry-run` to preview what would be sent without calling Strava.

## Credentials

If `sync-to-strava` reports missing Strava credentials, tell the user to
run `strava-auth` once first. It's an interactive, one-time browser
authorization step the user must do themselves — don't try to automate it.
