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
strength activities. Everything this script does around that shape
(see `sync_to_strava.py`) is reverse-engineered from observed behavior,
not official docs — it may drift as Strava changes things.

## Setup (one-time)

1. **Install dependencies**
   ```
   pip install -r requirements.txt
   ```

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
   python strava_auth.py
   ```
   This opens a Strava consent flow in your browser and saves a
   refresh token into `.env`. You only need to do this once — the
   script refreshes the access token automatically after that.

## Test it (yesterday's workout is included as a fixture)

Dry run first — no network calls, no credentials needed, just prints
what would be sent:
```
python sync_to_strava.py sample_workout.json --dry-run
```

Once your `.env` is set up, do a real upload:
```
python sync_to_strava.py sample_workout.json
```
It'll print the resulting activity URL when done.

## Normal usage (via Claude Code)

Point Claude Code at this project (it reads `CLAUDE.md` automatically)
and just ask it to sync a workout — it'll pull the data from your
connected Liftosaur MCP, shape it into the JSON this script expects,
and run the upload for you.

You can also build/edit a `workout.json` by hand — see
`sample_workout.json` for the shape.

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

- **Exercise name matching is best-effort.** Strava hasn't published
  the `exercise_type` values the uploads API accepts. This script
  ships a small mapping (`EXERCISE_TYPE_MAP` in `sync_to_strava.py`)
  for common lifts and falls back to an automatic guess otherwise.
  Unmatched exercises typically show up as "Unknown" in the Strava
  app rather than causing an error — reps/weight/volume still show up
  correctly either way, only the exercise label and muscle-map may be
  affected. Extend the map as you find mismatches.
- The muscle-map visualization Strava shows for in-app-logged
  workouts has been reported not to reliably appear on API-uploaded
  activities. Cosmetic only — doesn't affect the logged data.
