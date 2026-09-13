# Liftosaur → Strava sync

Syncs a strength workout logged in [Liftosaur](https://www.liftosaur.com/)
to Strava as a structured Weight Training activity — real
exercises/sets/reps/weight, not just a generic "workout" entry with a
duration.

**Why this exists:** Strava's official MCP connector is read-only —
there's no way to get a workout *into* Strava through it. This project
is the missing write path: it pulls a session from Liftosaur and
uploads it via Strava's undocumented JSON activity-upload format.

**A note on that format:** Strava has not published a schema for the
JSON upload payload or the `exercise_type` values it accepts for
strength activities. Everything this tool does around that shape
(see `liftostrava/src/liftostrava/strava/`) is reverse-engineered from
observed behavior, not official docs — it may drift as Strava changes
things.

## Project layout

This repo is a single installable package, `liftostrava`, living in
its own `liftostrava/` subdirectory (room for a sibling package later,
without reshuffling this one, if there's ever a reason to split
something out — see `liftostrava/src/liftostrava/sources/` below).
`.env` and `workouts/` stay at the repo root since they're runtime
config/data, not code:

```
liftostrava/
├── pyproject.toml
├── src/liftostrava/
│   ├── models.py        # Set, Exercise, Workout — the normalized shape
│   ├── sources/         # how a workout gets into the system
│   │   ├── base.py          # WorkoutSource protocol
│   │   └── mcp_export.py    # today's route: the JSON file written after
│   │                        # an MCP call (see CLAUDE.md) — a second
│   │                        # route (e.g. calling Liftosaur's REST API
│   │                        # directly) can sit alongside this later
│   ├── strava/           # everything Strava-facing
│   │   ├── exercise_map.py  # Liftosaur name -> Strava exercise_type
│   │   ├── payload.py       # Workout -> Strava's upload JSON
│   │   ├── auth.py          # OAuth: authorize once, refresh per run
│   │   └── client.py        # upload / poll / mute, over HTTP
│   └── cli/
│       ├── sync.py          # `sync-to-strava` entrypoint
│       └── auth.py          # `strava-auth` entrypoint
└── tests/
```

## Network access (Claude Code environments)

If you're running this project inside a sandboxed Claude Code
environment (web, cloud, or a locked-down local sandbox), configure it
to allow outbound access to **`*.strava.com`** (a plain `strava.com`
entry is not enough — the allowlist matches hostnames exactly unless
you use a leading `*.` wildcard, and none of what's needed here is the
bare domain). That wildcard covers both hosts this project needs:

- **`www.strava.com`** — OAuth and every Strava API call (`strava-auth`,
  `sync-to-strava`); the sync flow can't work at all without this.
- **`developers.strava.com`** — Strava's official API docs, notably
  the ["Supported Exercises"](https://developers.strava.com/docs/uploads/)
  list of `exercise_type` values that `strava/exercise_map.py`'s
  `EXERCISE_TYPE_MAP` is built from. Without this allowed, Claude
  can't check the live docs when extending the map for a new exercise
  and has to fall back to guessing.

## Setup (one-time)

1. **Install the package** (into a virtualenv — this creates `.venv/`
   if you don't already have one)
   ```
   python -m venv .venv && source .venv/bin/activate
   pip install -e "./liftostrava[dev]"
   ```
   This installs `liftostrava` in editable mode plus its dev
   dependencies (pytest, responses, pre-commit, ruff), and puts the
   `sync-to-strava` / `strava-auth` commands on your `PATH` within the
   venv.

2. **Register a Strava API app**: go to
   [strava.com/settings/api](https://www.strava.com/settings/api),
   create an app (any name/website works — this is just for your own
   use), and note the **Client ID** and **Client Secret**.

3. **Configure credentials**
   ```
   cp .env.example .env
   ```
   Fill in `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET` in `.env`.

4. **Authorize once**
   ```
   strava-auth
   ```
   This opens a Strava consent flow in your browser and saves a
   refresh token into `.env`. You only need to do this once — the
   CLI refreshes the access token automatically after that.

## Test it (a sample workout is included as a fixture)

Dry run first — no network calls, no credentials needed, just prints
what would be sent:
```
sync-to-strava liftostrava/tests/fixtures/sample_workout.json --dry-run
```

Once your `.env` is set up, do a real upload:
```
sync-to-strava liftostrava/tests/fixtures/sample_workout.json
```
It'll print the resulting activity URL when done.

## Normal usage (via Claude Code)

Point Claude Code at this project (it reads `CLAUDE.md` automatically)
and just ask it to sync a workout — it'll pull the data from your
connected Liftosaur MCP, shape it into the JSON `sync-to-strava`
expects, and run the upload for you.

Each synced workout is written to `workouts/` as its own timestamped
file (e.g. `workouts/2026-08-24T165602Z-fierce-5-workout-a.json`)
rather than overwriting a single shared file, so past syncs stay
around as a record. You can also build/edit one by hand — see
`liftostrava/tests/fixtures/sample_workout.json` for the shape.

## Privacy — please read

**The Strava API cannot set an activity's visibility** (Everyone /
Followers / Only You) — this has been a documented API limitation
since around 2018, confirmed still true as of this writing. No
third-party integration, including this one, can set true "Only You"
privacy on upload.

What this script *can* do, and does by default, is set
`hide_from_home=true` after upload, which mutes the activity from
Strava's activity feed. That is a weaker guarantee — it still exists
at whatever visibility your account default is set to, it's just not
pushed into feeds.

**For an actual reliable "private by default"**, set your account-wide
default in the Strava app once: **Settings → Privacy Controls →
Activities → Only You**. Every upload — from this script, from any
other app, from anywhere — will then default to private, and you can
loosen individual activities afterwards in the app if you want to
share one.

Pass `--public` to skip the `hide_from_home` step for a specific
upload (again: only relevant to feed visibility, not true privacy).

## Known limitations

- **Exercise name matching is best-effort.** Strava publishes a
  "Supported Exercises" list of accepted `exercise_type` values at
  [developers.strava.com/docs/uploads](https://developers.strava.com/docs/uploads/),
  but not a formal machine-readable schema, and Liftosaur exercise
  names don't map onto that list automatically. This project ships a
  small mapping (`EXERCISE_TYPE_MAP` in
  `liftostrava/src/liftostrava/strava/exercise_map.py`), built from
  that page, for common lifts and falls back to an automatic
  guess otherwise. Unmatched exercises typically show up as "Unknown"
  in the Strava app rather than causing an error — reps/weight/volume
  still show up correctly either way, only the exercise label and
  muscle-map may be affected. Extend the map as you find mismatches —
  check the live docs page first (see "Network access" above).
- The muscle-map visualization Strava shows for in-app-logged
  workouts has been reported not to reliably appear on API-uploaded
  activities. Cosmetic only — doesn't affect the logged data.
