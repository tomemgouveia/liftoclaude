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
(see `src/liftostrava/strava/`) is reverse-engineered from
observed behavior, not official docs — it may drift as Strava changes
things.

## Project layout

This repo is a single installable package, `liftostrava`, with its
project configuration and source tree at the repository root.
`.env` and `workouts/` stay at the repo root since they're runtime
config/data, not code:

```
.
├── pyproject.toml
├── Dockerfile
├── src/cloudflare_worker.py  # Cloudflare Worker entrypoint
├── src/liftostrava/
│   ├── models.py        # Set, Exercise, Workout — the normalized shape
│   ├── sources/         # how a workout gets into the system
│   │   ├── base.py          # WorkoutSource protocol
│   │   ├── mcp_export.py    # JSON file written after an MCP call (see
│   │   │                    # CLAUDE.md) — the fallback when no
│   │   │                    # LIFTOSAUR_API_KEY is configured
│   │   ├── liftohistory.py  # pure text parser: Liftohistory -> Workout
│   │   └── api.py           # hits Liftosaur's REST API directly, no
│   │                        # agent/JSON file involved (--from-api)
│   ├── strava/           # everything Strava-facing
│   │   ├── exercise_map.py  # Liftosaur name -> Strava exercise_type
│   │   ├── payload.py       # Workout -> Strava's upload JSON
│   │   ├── auth.py          # OAuth: authorize once, refresh per run
│   │   └── client.py        # upload / poll / mute, over HTTP
│   └── cli/
│       ├── sync.py          # `sync-to-strava` entrypoint
│       └── auth.py          # `strava-auth` entrypoint
├── wrangler.toml
└── tests/
```

## Network access (Claude Code environments)

If you're running this project inside a sandboxed Claude Code
environment (web, cloud, or a locked-down local sandbox), configure it
to allow outbound access to **`*.strava.com`** (a plain `strava.com`
entry is not enough — the allowlist matches hostnames exactly unless
you use a leading `*.` wildcard). That wildcard covers both Strava
hosts this project needs:

- **`www.strava.com`** — OAuth and every Strava API call (`strava-auth`,
  `sync-to-strava`); the sync flow can't work at all without this.
- **`developers.strava.com`** — Strava's official API docs, notably
  the ["Supported Exercises"](https://developers.strava.com/docs/uploads/)
  list of `exercise_type` values that `strava/exercise_map.py`'s
  `EXERCISE_TYPE_MAP` is built from. Without this allowed, Claude
  can't check the live docs when extending the map for a new exercise
  and has to fall back to guessing.

When using `--from-api`, also allow outbound access to
**`www.liftosaur.com`** for Liftosaur's REST API. The MCP + JSON-file
fallback does not use this API host.

## Setup (one-time)

1. **Install the package and dependencies** (this creates `.venv/` if
   needed and installs the project plus its dev dependencies)
   ```
   uv sync
   ```
   Run project commands with `uv run`, which uses the managed
   environment without requiring manual activation.

2. **Register a Strava API app**: go to
   [strava.com/settings/api](https://www.strava.com/settings/api),
   create an app (any name/website works — this is just for your own
   use), and note the **Client ID** and **Client Secret**.

3. **Configure credentials**
   ```
   cp .env.example .env
   ```
   Fill in `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET` in `.env`.
   Optionally also fill in `LIFTOSAUR_API_KEY` (requires Liftosaur
   Premium; generate at Settings > API Keys) to enable `--from-api`
   below — without it, syncing falls back to the MCP + JSON-file flow.

4. **Authorize once**
   ```
   uv run strava-auth
   ```
   This opens a Strava consent flow in your browser and saves a
   refresh token into `.env`. You only need to do this once — the
   CLI refreshes the access token automatically after that.

## Test it (a sample workout is included as a fixture)

Dry run first — no network calls, no credentials needed, just prints
what would be sent:
```
uv run sync-to-strava tests/fixtures/sample_workout.json --dry-run
```

Once your `.env` is set up, do a real upload:
```
uv run sync-to-strava tests/fixtures/sample_workout.json
```
It'll print the resulting activity URL when done.

## Run the Cloudflare Worker locally with Docker

The Docker image runs Pywrangler's local Worker runtime; it does not
deploy anything. Build and start it from the repository root:

```
docker build -t liftosaur-worker .
docker run --rm -p 8787:8787 \
  --mount "type=bind,source=$(pwd)/src,target=/app/src" \
  --mount "type=bind,source=$(pwd)/src/liftostrava,target=/app/python_modules/liftostrava" \
  liftosaur-worker
```

Then send a request to `http://localhost:8787/`, for example:

```
curl -i http://localhost:8787/
```

The source mount lets you edit the Worker without rebuilding the image.
To exercise the GET handler, create a local `.dev.vars` file with
`LIFTOSAUR_API_KEY=...` and mount it into the container:

```
docker run --rm -p 8787:8787 \
  -e LIFTOSAUR_DOTENV_PATH=/app/.dev.vars \
  --mount "type=bind,source=$(pwd)/src,target=/app/src" \
  --mount "type=bind,source=$(pwd)/src/liftostrava,target=/app/python_modules/liftostrava" \
  --mount "type=bind,source=$(pwd)/.dev.vars,target=/app/.dev.vars" \
  liftosaur-worker
```

`.dev.vars` is gitignored and excluded from the Docker build context.
The local Worker uses this writable mount as its dotenv file so that a
rotated Strava refresh token is saved back to `.dev.vars`. Restart the
container after a token rotation so Wrangler reloads the updated
bindings. The GET handler makes a live request to Liftosaur's API.

## Configure Strava token storage for Cloudflare

The Worker stores Strava's current access/refresh token pair and expiry
in a KV namespace. Create one, replace the placeholder `id` in
`wrangler.toml` with the returned namespace ID, then set the initial
credentials as Worker secrets:

```
npx wrangler kv namespace create STRAVA_TOKEN_STORE
npx wrangler secret put STRAVA_CLIENT_ID
npx wrangler secret put STRAVA_CLIENT_SECRET
npx wrangler secret put STRAVA_REFRESH_TOKEN
npx wrangler secret put LIFTOSAUR_API_KEY
npx wrangler deploy
```

The refresh-token secret is only the bootstrap value used when KV has no
token state yet. After the first successful refresh, the Worker reads and
updates the latest token pair in KV. Local `wrangler dev` uses a local KV
store by default; it does not share the production namespace's contents.
Avoid concurrent sync requests: KV is eventually consistent, so
simultaneous refreshes could race while Strava rotates the token.

## Normal usage (via Claude Code)

Point Claude Code at this project (it reads `CLAUDE.md` automatically)
and just ask it to sync a workout. What happens next depends on
whether `LIFTOSAUR_API_KEY` is configured:

- **With a key**: Claude uses the Liftosaur MCP's `get_history` only to
  find which record ID matches what you asked for, then runs
  `sync-to-strava --from-api <id>` directly — no JSON file, no
  hand-transcription.
- **Without one**: the original flow — Claude pulls the record from
  Liftosaur MCP and hand-transcribes it into a JSON file matching the
  shape `sync-to-strava` expects, then runs that.

  Each workout in this fallback flow is written to `workouts/` as its
  own timestamped file (e.g.
  `workouts/2026-08-24T165602Z-fierce-5-workout-a.json`) rather than
  overwriting a shared file. This is temporary scratch space: delete
  the file after a successful upload, but leave it in place if the
  upload fails so it can be retried or inspected. You can also
  build/edit a workout by hand — see
  `tests/fixtures/sample_workout.json` for the shape.

You can also invoke `--from-api` directly if you already know the
record ID (e.g. from `get_history`'s output):
```
uv run sync-to-strava --from-api 1789147805585
uv run sync-to-strava --from-api 1789147805585 --dry-run
```

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
  `src/liftostrava/strava/exercise_map.py`), built from
  that page, for common lifts and falls back to an automatic
  guess otherwise. Unmatched exercises typically show up as "Unknown"
  in the Strava app rather than causing an error — reps/weight/volume
  still show up correctly either way, only the exercise label and
  muscle-map may be affected. Extend the map as you find mismatches —
  check the live docs page first (see "Network access" above).
- The muscle-map visualization Strava shows for in-app-logged
  workouts has been reported not to reliably appear on API-uploaded
  activities. Cosmetic only — doesn't affect the logged data.
