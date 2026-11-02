# Liftosaur → Strava sync

To sync a Liftosaur workout to Strava (e.g. "push yesterday's workout to
Strava", "sync my last session"), use the **sync-to-strava** skill
(`.claude/skills/sync-to-strava/SKILL.md`). It covers both routes — the
Liftosaur REST API when `LIFTOSAUR_API_KEY` is set, and the JSON-file
fallback otherwise — plus the privacy and credentials caveats.

## Code layout

- `src/liftostrava/` — core library
  - `domain.py` — `Workout` / `Exercise` / `Set` dataclasses
  - `service.py` — `SyncService`, the one refresh → upload → poll → mute flow
  - `tokens.py` — `StravaTokens` and the `TokenStore` protocol
  - `liftosaur/` — REST client, Liftohistory parser, MCP JSON bridge
  - `strava/` — `StravaOAuth`, `StravaClient`, payload building
  - `cli/` — `sync-to-strava` and `strava-auth` entry points (`.env` token store)
- `src/liftostrava_worker/` — Cloudflare Worker: `entry.py` (dispatch),
  `routes/` (handlers + their helpers), `security/` (Access JWT, OAuth
  state, credential crypto), `storage/` (D1 repository, models);
  `src/cloudflare_worker.py` is the `wrangler.toml` entry shim
- Style: dataclasses for data, pure functions for transformations, small
  classes for API clients, `Protocol`s only where there are two real
  implementations.
- Tests mirror the source tree: `tests/liftostrava/<pkg>/test_<module>.py`
  and `tests/liftostrava_worker/...`.
