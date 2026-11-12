# Plan: include heart rate in synced Strava workouts

Branch: `feature/include-heart-rate` · Target release: v1.1.0

## Problem

Liftosaur reads heart rate from HealthKit and shows it, but does not save it
or return it through its REST API or MCP (confirmed against all history
records and a raw REST response). So workouts synced by liftostrava reach
Strava with no heart rate.

Strava's API cannot attach a heart-rate stream to an existing activity, so
the samples must be inside the file at upload time. The current upload is
`data_type=json` ([payload.py](../../src/liftostrava/strava/payload.py)),
which has no heart-rate field. A FIT file can carry both the exercise sets
and per-second heart-rate records.

## Goals

- A synced activity shows the exercise sets **and** a heart-rate graph.
- Existing Shortcuts keep working unchanged (`POST /`, `POST /api/sync` with
  only `{"workout_id": ...}`). No heart-rate data means today's JSON upload.
- No new heart-rate source other than Apple Health, read by the Shortcut.

## Non-goals

- Fetching heart rate server-side (the Worker cannot read HealthKit).
- Adding heart rate to activities already on Strava. For those: delete the
  activity in the Strava app, then re-sync. Strava's API has no delete or
  stream-edit endpoint, and it rejects duplicate uploads.
- Other metrics (calories, HRV, zones).

## Design

### Data flow

```
1. Shortcut: GET the workout list (each item now includes start and end).
   User picks a workout.
2. Shortcut: "Find Health Samples" (heart rate) between that workout's
   start and end.
3. Shortcut: POST /api/sync {workout_id, heart_rate: [...]}
4. Worker: fetch the workout from Liftosaur, validate the samples, and
   check they cover the workout through to its end.
   Latest sample before the end -> NotSyncedYet error, nothing uploaded.
5. Worker: build the FIT file from workout + samples, upload to Strava.
```

The workout window is `[start_time, start_time + elapsed_time]`. The
Shortcut runs after the workout, so the samples are normally in Health
already; `NotSyncedYet` covers the case where the watch has not yet synced
to the phone.

### Workout list change

`GET /` and `GET /api/workouts?brief=1` return `{id, name, date}` today.
Add `start` and `end` (ISO 8601, UTC) as extra fields so the Shortcut can
query Health for the exact window. Additive only: the existing fields and
their meaning stay, so the current Shortcut is unaffected.

### Request shape (backward compatible)

`heart_rate` is optional and each sample is `{"time": "<ISO 8601>", "bpm": <int>}`.

- **Field absent** (the current Shortcut): unchanged JSON upload, no heart rate.
- **Field present:** the Worker takes the heart-rate path and does not fall
  back silently. Samples are filtered to the workout window; invalid ones
  (non-numeric, bpm outside 30-240, unparseable time) are dropped.
  - Empty after filtering, or latest sample earlier than `end` minus a
    tolerance: respond with `NotSyncedYet`, upload nothing. The user can
    run the Shortcut again once the watch has synced.
  - Otherwise: build FIT and upload.

### NotSyncedYet

New `NotSyncedYet` exception in [errors.py](../../src/liftostrava/errors.py),
raised by the pure window check in `heart_rate.py` (so the CLI and Worker
share it). The Worker maps it to HTTP 425 with a plain message ("Heart rate
data only runs to 18:42, the workout ended 18:51. Wait for the watch to
sync and try again."). 409 stays reserved for Strava duplicates.

The rule is `latest_sample >= end - SYNC_TOLERANCE`, with `end = start_time +
elapsed_time` (no separate end field on `Workout`). `SYNC_TOLERANCE` is a
named constant of **60 seconds**, the most we allow. It only absorbs the
watch's sampling gap just before the end; samples after `end` are not an
error, the window filter drops them.

### Domain

Add to `Workout` in [domain.py](../../src/liftostrava/domain.py):

```python
@dataclass(frozen=True)
class HeartRateSample:
    offset_s: int  # seconds since workout start
    bpm: int

heart_rate: list[HeartRateSample] = field(default_factory=list)
```

Parsing and window filtering is a pure function (`heart_rate.py`), unit-tested.

### FIT builder

New `src/liftostrava/strava/fit.py`: pure Python, no dependencies (Workers
only run pure-Python packages, and the FIT binary format is small). Messages:
`file_id`, `event` (start/stop), `record` (timestamp + heart_rate) for each
sample, `set` (category, exercise name, reps, weight, start time, duration)
for each set, `lap`, `session` (sport = training, sub_sport = strength),
`activity`; then CRC.

`StravaClient.upload` picks the format: FIT when `workout.heart_rate` is
non-empty, JSON otherwise. The form field `data_type` becomes `fit` (the
filename keeps the random suffix to avoid Strava's external_id dedupe, see
the comment in [client.py](../../src/liftostrava/strava/client.py)).

### Exercise mapping (the biggest piece of work)

`EXERCISE_TYPE_MAP` holds Strava JSON string values (for example
`BARBELL_BACK_SQUAT`). FIT needs numeric `exercise_category` plus
`exercise_name` from the FIT SDK profile. Plan: add a second table keyed by
the same Liftosaur names, mapping to `(category, name)` ints, sourced from the
FIT SDK `Profile.xlsx`. A test asserts every key in `EXERCISE_TYPE_MAP` has a
FIT entry, so the two tables cannot drift. Unmapped exercises fall back to the
category only (`unknown` name).

### Set timing

Liftosaur gives no per-set timestamps. Spread sets evenly across
`elapsed_time` in order, using each set's share. Heart rate lines up by
absolute time, so this only affects the per-set marks, not the graph.

## Phases

Each phase ends with something runnable.

1. **Spike (about 1 hour, do first).** Script (not committed to `src/`) that
   builds one FIT file by hand for the 11 Nov workout with fake heart-rate
   samples and uploads it to Strava.
   **Go/no-go:** the activity must show named exercises/sets and a heart-rate
   graph. If Strava drops the sets or the heart rate, stop and rethink
   (fallback options: TCX with heart rate only, losing sets; or keep JSON).
2. **Domain + parsing (about 1 hour).** `HeartRateSample`, parse/filter/
   validate function, tests in `tests/liftostrava/test_heart_rate.py`.
3. **FIT encoder + mapping (about 4 hours).** `strava/fit.py`, the FIT
   exercise table, tests (round-trip decode in tests against a minimal
   reader, CRC check, mapping coverage).
4. **Upload + service (about 1 hour).** Format switch in `StravaClient`,
   `preview_upload` support for `--dry-run` (summarise the FIT instead of
   dumping bytes), tests with `responses`.
5. **Worker + CLI (about 1.5 hours).** `handle_sync` reads optional
   `heart_rate` and maps `NotSyncedYet` to HTTP 425; add `start`/`end` to the
   compact workout list; CLI accepts `--heart-rate FILE.json`. Tests for:
   absent field (unchanged behaviour), valid samples, garbage samples,
   samples outside the window, latest sample before the end
   (`NotSyncedYet`), empty samples. Add a dry-run check (CLI flag and a
   Worker option) that reports, without uploading: sample count, first and
   last sample times, workout end, and whether the check passes. This is how
   we tune `SYNC_TOLERANCE` and explain a `NotSyncedYet`.
6. **Shortcut (about 1 hour).** Use the new `start`/`end` from the list for
   "Find Health Samples" (heart rate) and pass the result as `heart_rate`;
   show the 425 message to the user. Document in
   [cloudflare.md](../cloudflare.md). Update the Shortcut only after the
   Worker is deployed; the old Shortcut keeps working either way.
7. **Release (about 30 minutes).** Update docs, release notes, v1.1.0.

## Risks and open questions

| Risk | Mitigation |
| --- | --- |
| Strava may not render sets and heart rate together from one FIT | Phase 1 spike is the go/no-go gate |
| FIT exercise enums do not cover every Liftosaur exercise | Category-level fallback; test that flags unmapped names |
| Shortcut payload size / Shortcuts building JSON from samples | About 500 samples per 45 minutes (about 25 KB). Check how Shortcuts formats the sample list; if awkward, also accept CSV text `ISO,bpm` per line |
| Samples not yet in Health when the Shortcut runs | `NotSyncedYet` (HTTP 425), nothing uploaded, so no duplicate to delete; retry later |
| Heart rate legitimately stops before the workout end (watch removed, strap dropout) | Would raise `NotSyncedYet` forever; the Shortcut can omit `heart_rate` for a plain upload |
| Worker runtime limits for FIT encoding | Encoding is a few KB of work; verify in the Docker runtime during phase 5 |
| Workout times: Liftosaur `start_time` vs actual watch recording | Start/end tolerance, decide after spike |

Decisions:

1. **Tolerance:** 60 seconds at most (`end - 60s`). If a fully synced
   workout of yours ever fails the check, look at the dry-run output before
   raising it.
2. **Override:** none. If the watch really has no data to the end, the
   Shortcut omits `heart_rate` and gets the plain JSON upload (no heart
   rate), which already works. No `allow_partial` flag.

## Testing

- Unit: sample parsing/filtering, FIT encoding and CRC, mapping coverage.
- Existing tests must pass untouched (JSON path unchanged).
- Manual: sync the 11 Nov workout from the Shortcut after phase 6 and check
  the Strava activity.
