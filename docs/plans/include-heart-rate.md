# Plan: include heart rate in synced Strava workouts

Branch: `feature/include-heart-rate` · Target release: v1.1.0

## Problem

Liftosaur reads heart rate from HealthKit and shows it, but does not save it
or return it through its REST API or MCP (confirmed against all history
records and a raw REST response). So workouts synced by liftostrava reach
Strava with no heart rate.

Strava's API cannot attach a heart-rate stream to an existing activity, so
the samples must be in the file at upload time.

## Approach: JSON `streams`

Strava's JSON strength upload (what we already send) has an optional
`streams` object: `time` (seconds from `start_time`, required), `heartrate`
(bpm) and `active`, all arrays of the same length. We add `streams` to the
existing payload when heart-rate samples are supplied. Nothing else about
the upload changes, so the verified exercise-type mapping in
[payload.py](../../src/liftostrava/strava/payload.py) keeps working.

**Verified by spike:** one JSON upload with `sets` and `streams.heartrate`
produced a WeightTraining activity with the sets rendered by name and
heart rate present (average 116, max 139, matching the fake test data).

### Rejected: FIT upload

A FIT file can also carry sets plus heart rate (also verified by spike), but
it needs numeric FIT exercise enums. Strava's documented exercise list is
the JSON vocabulary, and 22 of our 43 mapped exercises have no exact FIT
equivalent (Leg Extension, Seated Leg Curl, machine Hip Thrust, Pallof
Press, hip abductor/adductor machines, Skullcrusher, ...), so FIT would
likely regress how they render. FIT also needs an encoder, and Garmin's FIT
SDK licence limits use to "internal business purposes". JSON streams avoids
all of that.

## Goals

- A synced activity shows the exercise sets **and** a heart-rate graph.
- Existing Shortcuts keep working unchanged (`POST /`, `POST /api/sync` with
  only `{"workout_id": ...}`). No `heart_rate` field means today's upload.
- Heart rate source is Apple Health, read by the Shortcut.

## Non-goals

- Fetching heart rate server-side (the Worker cannot read HealthKit).
- Adding heart rate to activities already on Strava. For those: delete the
  activity in the Strava app, then re-sync. Strava's API has no delete or
  stream-edit endpoint, and it rejects duplicate uploads.
- Other metrics (calories, HRV, zones).
- Fixing exercises that already render as "Unknown" (separate work on
  `EXERCISE_TYPE_MAP`; for example "Incline Bench Press, Dumbbell" is
  unmapped today).

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
5. Worker: build the JSON payload with `streams`, upload to Strava.
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

- **Field absent** (the current Shortcut): unchanged upload, no heart rate.
- **Field present:** the Worker takes the heart-rate path and does not fall
  back silently. Samples are filtered to the workout window; invalid ones
  (non-numeric, bpm outside 30-240, unparseable or naive time) are dropped.
  - Empty after filtering, or latest sample earlier than `end` minus
    `SYNC_TOLERANCE`: respond with `NotSyncedYet`, upload nothing. The user
    can run the Shortcut again once the watch has synced.
  - Otherwise: build the payload with `streams` and upload.

### NotSyncedYet

`NotSyncedYet` in [errors.py](../../src/liftostrava/errors.py), raised by
`samples_for_workout` in [heart_rate.py](../../src/liftostrava/heart_rate.py)
(so the CLI and Worker share it). The Worker maps it to HTTP 425 with a
plain message ("Heart-rate data only runs to 18:42 UTC, but the workout ended
at 18:51 UTC. Wait for the watch to sync and try again."). 409 stays reserved
for Strava duplicates.

The rule is `latest_sample >= end - SYNC_TOLERANCE`, with `end = start_time +
elapsed_time` (no separate end field on `Workout`). `SYNC_TOLERANCE` is a
named constant of **60 seconds**, the most we allow. It only absorbs the
watch's sampling gap just before the end; samples after `end` are not an
error, the window filter drops them.

### Domain

`Workout.heart_rate: list[HeartRateSample]` (offset seconds, bpm), empty by
default. Done in phase 2.

### Payload

`build_payload` adds `"streams": {"time": [...], "heartrate": [...]}` when
`workout.heart_rate` is non-empty. Same length, offsets non-decreasing,
duplicate offsets collapsed (keep the last). Samples are about 5 seconds
apart (about 500 per 45 minutes); if the upload size ever matters, thin
them to at most one per 5 seconds.

## Phases

Each phase ends with something runnable.

1. **FIT spike (DONE).** Sets plus fake heart rate uploaded as FIT: worked,
   but exercise vocabulary mismatch and licence made it the wrong route.
2. **Domain + parsing (DONE).** `HeartRateSample`, `Workout.heart_rate`,
   parse/filter/validate, `NotSyncedYet`, tests.
3. **JSON streams spike (DONE).** Sets plus `streams.heartrate` in one JSON
   upload: both showed up in Strava. Go.
4. **Payload (DONE).** `build_payload` adds `streams`; tests (shape,
   equal lengths, duplicates, absent samples leave the payload unchanged).
   `preview_upload` / `--dry-run` shows a summary of the streams (count,
   first/last sample).
5. **Worker + CLI (DONE; `handle_sync` itself is only compile-checked, test it in the local runtime).** `handle_sync` reads optional
   `heart_rate` and maps `NotSyncedYet` to HTTP 425; add `start`/`end` to
   the compact workout list; CLI accepts `--heart-rate FILE.json`. Tests for:
   absent field (unchanged behaviour), valid samples, garbage samples,
   samples outside the window, latest sample before the end
   (`NotSyncedYet`), empty samples. Add a dry-run check (CLI flag and a
   Worker option) that reports, without uploading: sample count, first and
   last sample times, workout end, and whether the check passes. This is
   how we tune `SYNC_TOLERANCE` and explain a `NotSyncedYet`.
6. **Shortcut (about 1 hour).** Use the new `start`/`end` from the list for
   "Find Health Samples" (heart rate) and pass the result as `heart_rate`;
   show the 425 message to the user. Document in
   [cloudflare.md](../cloudflare.md). Update the Shortcut only after the
   Worker is deployed; the old Shortcut keeps working either way.
7. **Release (about 30 minutes).** Update docs, release notes, v1.1.0.

## Risks and open questions

| Risk | Mitigation |
| --- | --- |
| Shortcuts building the JSON sample list is fiddly | About 500 samples per 45 minutes (about 25 KB). Check how Shortcuts formats the sample list; if awkward, also accept CSV text `ISO,bpm` per line |
| Samples not yet in Health when the Shortcut runs | `NotSyncedYet` (HTTP 425), nothing uploaded, so no duplicate to delete; retry later |
| Heart rate legitimately stops before the workout end (watch removed, strap dropout) | Would raise `NotSyncedYet` forever; the Shortcut can omit `heart_rate` for a plain upload |
| Workout times: Liftosaur `start_time` vs actual watch recording | Window filter and tolerance; check with the dry-run output on real data |
| Strava rejects or mis-renders streams for some payloads | Only one spike so far; test a real workout with real samples before release |
| A push of this branch triggers a Cloudflare preview build whose preview command is `uv run pywrangler deploy` (a full deploy) | Change it to a versions upload, or turn off preview-branch builds, before pushing; `preview_urls = false` in `wrangler.toml` also needs deciding. Preview URLs sit outside Cloudflare Access, so the Worker would reject requests there anyway |

Decisions:

1. **Tolerance:** 60 seconds at most (`end - 60s`). If a fully synced
   workout of yours ever fails the check, look at the dry-run output before
   raising it.
2. **Override:** none. If the watch really has no data to the end, the
   Shortcut omits `heart_rate` and gets the plain upload (no heart rate),
   which already works. No `allow_partial` flag.

## Testing

- Unit: sample parsing/filtering, payload streams.
- Existing tests must pass untouched (no-heart-rate path unchanged).
- Manual: sync a real workout with real samples from the Shortcut after
  phase 6 and check the Strava activity.
