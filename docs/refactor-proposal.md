# Proposal: restructuring `liftostrava`

## What's wrong today

1. **Style is decided per file, not by role.**
   - `LiftosaurApiSource` is a class holding an API key. The Strava client, by contrast, is loose functions that thread `access_token` through every call (`upload_activity(token, …)`, `poll_upload(token, …)`, `set_muted(token, …)`).
   - `McpExportSource` is a class whose most useful method is a `@staticmethod`.
   - `WorkoutSource` is a `Protocol` that nothing uses. The CLI picks a source with `if/else`, and the `list_history`/`get_workout` methods that callers really use aren't on it.
2. **The sync flow exists twice.** `cli/sync.py` and `cloudflare_worker.py` both do refresh token → upload → poll → mute. The worker re-implements polling (`poll_upload_async`) and mutates `workout.utc_offset` to inject a timezone.
3. **Responsibilities leak across modules.**
   - `strava/auth.py` mixes HTTP with `.env` persistence.
   - `strava/client.py` builds payloads and owns the form fields the CLI's `--dry-run` reuses.
   - `payload.py` holds config (the athlete timezone).
   - `config.py` computes paths from `__file__` at import.
   - `cli/sync.py` mixes env reading, orchestration and printing, with `assert`s for type narrowing.
4. **Dead or duplicated bits.**
   - `--sport-type` is plumbed everywhere but never varies.
   - `REQUEST_TIMEOUT_S` and the token URL are repeated 4×.
   - `SCOPE` and `REDIRECT_URI` are defined in `strava/auth.py` and `cli/auth.py`'s docs.
   - Three long docstrings duplicate each other.
5. **Packaging.** A top-level `cloudflare` package shadows the PyPI `cloudflare` SDK name. `cloudflare_worker.py` (483 lines) is one class of routing, auth, D1 and orchestration. Neither is in the wheel.

## Guiding rule (one style, applied by role)

| Role | Form |
| --- | --- |
| Data (workout, tokens, settings) | frozen `@dataclass` |
| Pure transformation (parse, build payload, unit conversion) | plain functions, no I/O |
| Anything holding config or a connection (API clients) | small class, constructed once |
| Swappable behaviour (sources, token storage) | `Protocol` that is actually used by the caller |
| Orchestration | one service class taking its collaborators in `__init__` |
| Entry points (CLI, worker) | thin: parse input → call service → format output |

## Target layout

Two vendors, one package each; no source/destination abstraction (this tool will only ever be Liftosaur → Strava).

```
src/
  liftostrava/                     # core library, no CLI/worker concerns
    domain.py                      # Workout, Exercise, Set (frozen; Set keeps its unit)
    errors.py                      # StravaUploadError, MissingCredentials, ...
    settings.py                    # Settings dataclass + from_env(); the only env reader
    tokens.py                      # StravaTokens, TokenStore Protocol, EnvFileTokenStore
    service.py                     # SyncService(oauth, strava, tokens, tz).sync(workout, hide_from_home)
    liftosaur/
      client.py                    # LiftosaurClient (class: key, pagination): get(id), list(start, end), health_check
      history_parser.py            # parse_liftohistory (pure)
      mcp_export.py                # JSON bridge for MCP-fetched workouts: load(path), list(dir)
    strava/
      oauth.py                     # StravaOAuth(client_id, secret): authorize_url / exchange / refresh
      client.py                    # StravaClient(access_token): upload / wait_for_upload / set_hide_from_home
      payload.py                   # build_payload(workout, utc_offset) – pure; includes the
                                   # EXERCISE_TYPE_MAP table + exercise_type_for
  liftostrava_cli/
    sync.py  auth.py               # argparse + print only
  liftostrava_worker/              # renamed from cloudflare/
    entry.py                       # WorkerEntrypoint: dispatch only
    repository.py                  # UserRepository (D1 + credential encryption), D1TokenStore
    routes/ (connect.py, sync.py, history.py)
    access_jwt.py, crypto.py, oauth_state.py, history_range.py
  cloudflare_worker.py             # 3-line shim, wrangler `main` unchanged
```

Key design points:

- **`SyncService` takes a `Workout`, not a source.** Callers fetch it (CLI: API client or JSON file; worker: API client), so there's no `WorkoutSource` protocol. It is the single sync flow. It returns a `SyncResult(activity_id, url)` and never prints. The CLI prints and the worker serialises to JSON. Both go through the same refresh → upload → poll → mute path.
- **`TokenStore` abstracts where refresh tokens live.** `.env` for the CLI, D1 for the worker. This removes the dotenv import from inside `strava/auth.py` and the credential `assert`s.
- **`StravaClient` owns one `requests.Session`**, the timeout and the base URL. This removes the 4× duplicated constants and token threading. Polling takes an injectable `sleep`, so the worker can supply an async variant or reuse the sync one.
- **Timezone is explicit data.** `Workout.utc_offset` stops being mutated. `SyncService` takes `tz` from settings (default Europe/London) and passes the offset to `build_payload`.
- **Weights normalised to kg in the parser.** This removes `Set.unit` and the lb→kg branch from payload building.
- **Dry-run is `service.preview(id)`**, which returns the form fields and payload. It shares code with the real upload, so the two can't diverge.
- **Drop `--sport-type`.** It is a constant in `StravaClient`.
- **Docs.** The long caveat docstring moves from `cli/sync.py` into `docs/usage.md`, where it is partly duplicated already.

## Migration plan (each step keeps `pytest` green)

1. Add `domain.py`, `errors.py` and `settings.py`. Move `models.py` and `config.py` onto them, with import shims.
2. Introduce `StravaOAuth`/`StravaClient` classes. Re-point `payload.py` and the form fields, folding `exercise_map.py` into `payload.py`. Delete the loose functions.
3. Create the `liftosaur/` package (no source protocol). Rename `LiftosaurApiSource` to `LiftosaurClient` (moving it and the parser into it), keep `McpExportSource` as `liftosaur/mcp_export.py`, then fix `WorkoutEntry`/`id` semantics.
4. Add `TokenStore` and `SyncService`. Rewrite `cli/sync.py` as a thin wrapper.
5. Rename `cloudflare/` to `liftostrava_worker/` and split the worker into routes. Move it onto `SyncService`. Update `wrangler.toml` and `pyproject.toml`.
6. Update `CLAUDE.md`, the docs and the console-script entry points (`sync-to-strava`/`strava-auth` names stay unchanged).

The CLI contract in `CLAUDE.md` (`uv run sync-to-strava --from-api <id>` and the JSON file route) is kept as is.

## Decisions (from review)

1. **Keep the JSON-file route.** The JSON bridge stays (as `liftosaur/mcp_export.py`), and I'll package Claude's sync workflow (today's `CLAUDE.md` Flow A/B) as a project skill in `.claude/skills/sync-to-strava/`. `CLAUDE.md` shrinks to a pointer.
2. **Worker rename is OK**, and you'll test the deploy.
3. **Keep `Set.unit`.** The lb→kg conversion stays in `build_payload`.

## Refinements after reading the worker

- **`SyncService.sync` is `async`.** Polling uses `asyncio.sleep`, so the worker and the CLI share one flow. The CLI wraps it in `asyncio.run`. The HTTP calls stay blocking `requests`, as today.
- **`TokenStore` is async** (`load`/`save`) because D1 is. `EnvFileTokenStore` implements it trivially. The access-token validity check (1h threshold) moves into `StravaTokens`.
- **The `wrangler.toml` `main` stays `src/cloudflare_worker.py`** as a ~3-line shim: `from liftostrava_worker.entry import Default`. Bundling siblings relative to `main` is what works today, and I can't verify a moved entry point from here. Only the `cloudflare/` package is renamed to `liftostrava_worker/`, and the Dockerfile's COPY line is updated.
- **Worker split.** `repository.py` (`UserRepository`: D1 queries and credential encryption), `routes/{connect,sync,history}.py` as plain functions, and `entry.py` for dispatch only. Logic is moved verbatim, not rewritten, because only the pure helpers have tests.
- **Rename for consistency:** `get_workout` → `get`, `list_history` → `list`, `WorkoutEntry` → `WorkoutRecord` (a plain id + workout pair). Tests are updated alongside.
- **Skill replaces the `CLAUDE.md` flows.** `SKILL.md` has the "check for `LIFTOSAUR_API_KEY`, then Flow A or B" logic and the privacy caveat. The `.json` scratch-file rules stay.

## Commit sequence (each commit green)

1. `domain`/`errors`/`settings`/`tokens`, with tests updated.
2. Strava `oauth`/`client`/`payload` classes.
3. Sources protocol and renames.
4. `SyncService` and the thin CLI.
5. Worker package rename, split and shim.
6. Skill, `CLAUDE.md` and docs.

## As implemented — deviations from the plan above

- Commits were grouped as: core library + CLI, worker, then skill/docs (the intermediate steps weren't independently green because `SyncService` touches everything).
- The CLI stayed inside the package as `liftostrava/cli/` (no separate `liftostrava_cli` package), so the console-script entry points and the wheel are unchanged.
- No `settings.py`: `.env` handling is CLI-only (`cli/config.py`, `cli/env_store.py`); the core takes explicit arguments and the worker builds its own from env bindings (`liftostrava_worker/context.py`).
- Kept the existing `LiftosaurClient.list_history` / `get_workout` names (a method called `list` would shadow the builtin).
- Worker module names: `crypto.py` and `access_jwt.py` (from `credential_crypto.py` / `process_jwt.py`).
- `liftosaur/mcp_export.py` is now two functions, `load_workout` and `list_exported`. `list_exported` has no caller outside tests; consider deleting it.
- The worker package is grouped by concern: `routes/`, `security/`, `storage/`, plus `entry.py` and `context.py` at the top.
