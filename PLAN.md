# Add a Liftosaur-REST-API source (`sources/api.py`)

## Context

Today the only way a workout gets into `liftostrava` is `sources/mcp_export.py`:
Claude reads a Liftosaur MCP tool's output (Liftohistory text) and hand-transcribes
it into JSON. That works, but it means every sync depends on me (Claude) being in
the loop and correctly transcribing reps/weights by eye — not something that can
run unattended, and not something that could plausibly become a native Liftosaur
feature (the eventual goal: contribute a "sync to Strava" feature upstream to
[astashov/liftosaur](https://github.com/astashov/liftosaur) — there's already a
live, maintainer-engaged discussion about this,
[#369](https://github.com/astashov/liftosaur/discussions/369), which you've
already commented on).

Liftosaur has a real REST API (`https://www.liftosaur.com/api/v1`, Bearer
`LIFTOSAUR_API_KEY`, requires Premium) that can fetch workout history without any
agent involved. This phase adds it as a second, independent `WorkoutSource`.

**Key discovery from research just now:** the REST API's `GET /api/v1/history(/:id)`
returns the workout as a `"text"` field containing the exact same Liftohistory
text format the MCP tools already return (confirmed directly — fetched 3 real
records via `get_history` and the API docs' example response is structurally
identical). That means the real engineering work here isn't the HTTP call, it's
writing a parser for that text format — and that parser can be built and fully
tested right now against real data, with no API key needed yet.

Decisions already made (asked and answered):
- **Keep `mcp_export.py` and `api.py` as fully separate implementations**
  — no shared parser between them. `mcp_export.py` stays exactly as-is.
- **But change CLAUDE.md's default workflow**: once this exists, use MCP's
  `get_history` only to *find which record ID* matches what the user asked for
  (e.g. "yesterday"), then call `sync-to-strava --from-api <id>` directly instead
  of hand-transcribing JSON. MCP+hand-transcription becomes the fallback for when
  no `LIFTOSAUR_API_KEY` is configured.
- **Unilateral sets** (`3x8|7 0lb`, "8 reps right, 7 left"): take the first number
  only, side ignored — `3x8|7` becomes 3 sets of 8 reps.
- **Units**: extend the `Set` model with a `unit` field rather than converting at
  parse time — `strava/payload.py` converts to kg (Strava's expected unit) when
  building the upload payload.
- **Scope**: this phase is "add `--from-api ID` as an alternative to a JSON file,"
  still manually invoked. Fully unattended/cron sync (auto-detect latest workout,
  no agent at all) is a deliberately separate, later phase — not designed here.

## Approach

### 1. `models.py` — extend `Set` with a unit, keep positional construction working

```python
@dataclass
class Set:
    reps: int
    weight: float
    unit: Literal["kg", "lb"] = "kg"
```

Renaming `weight_kg` → `weight` + new `unit` (defaulting `"kg"`) means every
existing positional construction (`Set(5, 60)`, used throughout the test suite)
keeps working unchanged — only keyword-argument call sites need updating.

### 2. `sources/liftohistory.py` (new) — pure text → `Workout` parser

One function, `parse_liftohistory(text: str) -> Workout`, no I/O, fully unit-testable
in isolation. Algorithm:

- **Header**: split on `" / "` (space-slash-space — safe because program names
  containing a bare `/` like `"5/3/1"` or `"L/S/U"` never have spaces around it,
  confirmed in real data). First segment is the date (handle both the
  `2026-09-11 17:30:05 +00:00` form seen in real records and the
  `2026-02-28T10:45:30Z` form from the reference doc — `datetime.fromisoformat`
  handles both once normalized). Remaining segments are `key: value` pairs
  (`program`, `dayName`, `week`, `dayInWeek`, `duration`) — all individually
  optional per the format spec except the exercises block itself. Build
  `name` from `program`/`dayName` the same way CLAUDE.md currently instructs me
  to (`"<program> - <dayName>"`, gracefully degrading if either is missing), and
  parse `duration: Ns` into `elapsed_time` (default to `0` if absent, since
  Strava's upload needs *something*).
- **Exercises**: each line between `exercises: {` and the closing `}` (skip `//`
  note lines) splits on `" / "` into: exercise name (kept whole, including an
  equipment suffix like `", Leverage Machine"` — matches `EXERCISE_TYPE_MAP`'s
  existing keys exactly, confirmed against real data), then a completed-sets
  segment (whichever segment isn't prefixed `warmup:`/`target:` — those two are
  dropped entirely, matching CLAUDE.md's existing rule, just enforced in code
  instead of by me reading it), which itself splits on `", "` into groups like
  `2x8 42.5kg` or `3x8|7 0lb` or `1x5+ 185lb`.
- **Set-group regex**: capture set-count, reps, optional `+` (AMRAP marker,
  ignored) and optional `|N` (unilateral, ignored per the decision above),
  weight, unit, optional trailing `@RPE` (ignored). Expand each group into that
  many individual `Set` entries.

Build fixtures from **real data** (already fetched — 3 actual records spanning
kg-only weights, unilateral sets, exercises with/without warmup, an exercise
with only completed sets and no warmup/target at all) plus the reference doc's
synthetic edge cases (`lb` units, AMRAP `+`, multi-exercise notes) for cases your
own recent history doesn't happen to cover.

**Known, documented limitation** (not worth solving now): a program/dayName
value that itself contains the literal substring `" / "` would break the header
split. None of your real programs do; flag it in the parser's docstring.

### 3. `sources/api.py` (new) — thin HTTP client

```python
class LiftosaurApiSource:
    def __init__(self, record_id: str): ...
    def load(self) -> Workout:
        # GET https://www.liftosaur.com/api/v1/history/{record_id}
        # Authorization: Bearer <LIFTOSAUR_API_KEY>
        # -> parse_liftohistory(response["data"]["text"])
```

Raise a clear error if `LIFTOSAUR_API_KEY` is unset (mirroring how `cli/sync.py`
already handles missing Strava credentials) — point at Settings → API Keys and
the Premium requirement.

### 4. `sources/mcp_export.py` — one-line adaptation

`Set(reps=s["reps"], weight_kg=s["weight_kg"])` → `Set(reps=s["reps"], weight=s["weight_kg"])`.
The JSON *wire format* CLAUDE.md documents is untouched (`weight_kg` stays the
key in the file) — only the internal dataclass construction changes.

### 5. `strava/payload.py` — convert to kg at payload-build time

`build_strava_payload` reads `s.weight`/`s.unit` instead of `s.weight_kg`,
converting `lb → kg` (×0.45359237) when `unit == "lb"` before emitting Strava's
`"weight"` field — Strava's own field has always been kg here.

### 6. `cli/sync.py` — `--from-api` as an alternative to the positional file arg

Make `workout_file` optional (`nargs="?"`), add `--from-api RECORD_ID`, require
exactly one of the two, and pick the source accordingly. Everything downstream
(`build_strava_payload`, `upload_activity`, `--dry-run`, `--public`) is unchanged
— this is purely a different way to obtain a `Workout`.

### 7. Config / docs

- `.env.example`: add `LIFTOSAUR_API_KEY=` with a comment (Premium required,
  generated at Settings → API Keys).
- `README.md`: update the `sources/` tree comment (currently says
  `mcp_export.py # today's only route`) and document `--from-api`.
- `CLAUDE.md`: restructure the workflow — if `LIFTOSAUR_API_KEY` is set, use
  `get_history` (MCP) only to resolve the record ID for what the user asked for,
  then run `sync-to-strava --from-api <id>` directly (no JSON file, no manual
  transcription, no `workouts/` scratch file for this path since there's nothing
  to write). If no key is set, fall back to today's full JSON-transcription flow
  unchanged.

### 8. Tests

- `tests/test_liftohistory_parser.py`: the bulk of new test coverage — pure
  function, no mocking, real+synthetic fixtures per the cases above.
- `tests/test_api_source.py`: mock the HTTP GET via `responses`
  (matching the existing Strava-client test pattern), assert the Bearer header
  and URL, and that the response's `text` field reaches the parser correctly.
- Update `test_mcp_export_source.py` / `test_payload.py` / `test_strava_client.py`
  for the `Set` field rename (positional constructions stay valid; keyword ones
  need `weight=` instead of `weight_kg=`), plus a `build_strava_payload` test for
  `lb → kg` conversion.
- `test_cli.py`: extend the existing `--dry-run` tests with a `--from-api`
  variant (API call mocked).

## Verification

- `python -m pytest` (from `liftostrava/`) — full suite green, including new
  parser/API-source tests.
- `ruff check .` / `ruff format --check .`, `pyright` — clean, matching every
  prior phase in this project.
- Manual smoke test once you have a `LIFTOSAUR_API_KEY`: `sync-to-strava
  --from-api <a real record id> --dry-run` against one of your own real
  workouts, comparing the printed payload against what the MCP+hand-transcription
  route would have produced for the same workout — the two should match.

## Explicitly out of scope for this phase

- Unifying `mcp_export.py` onto the new parser (kept separate, per your answer).
- Fully unattended/cron sync — deferred to its own later phase.
- Anything in Liftosaur's own upstream repo — this phase only prepares the
  ground (a working, tested reference implementation) for that eventual
  contribution; replying to discussion #369 with a concrete example is a
  separate, low-effort action you can take independently whenever you like.
