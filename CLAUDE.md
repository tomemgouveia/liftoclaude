# Liftosaur → Strava sync

When the user asks to sync a Liftosaur workout to Strava (e.g. "push
yesterday's workout to Strava", "sync my last session"):

1. Use the Liftosaur MCP tools (`get_history` or `get_history_record`)
   to fetch the relevant workout. Match by date if the user gave one.

2. Convert it into a `workout.json` file matching this shape:

   ```json
   {
     "name": "<program> - <dayName>",
     "start_time": "<ISO 8601 UTC timestamp from the record>",
     "elapsed_time": <duration in seconds>,
     "description": "Synced from Liftosaur",
     "exercises": [
       {"name": "<exercise name>", "sets": [{"reps": N, "weight_kg": N}, ...]}
     ]
   }
   ```

   Important: only include **completed/actual** sets (the numbers the
   user actually logged), not the `warmup:` or `target:` sets from the
   Liftohistory record — those aren't working sets.

3. Run the script:

   ```
   python sync_to_strava.py workout.json
   ```

   By default this mutes the activity from Strava's home feed
   (`hide_from_home`), but see the privacy caveat in `sync_to_strava.py`'s
   docstring and `README.md` — that is NOT the same as "Only You"
   visibility, which the Strava API cannot set. Pass `--public` only if
   the user explicitly asks not to mute it. If the user wants a true
   "Only You" default, tell them to set that in the Strava app itself
   (Settings > Privacy Controls > Activities) — this only needs doing
   once, and then every upload (from this script or anywhere else)
   inherits it automatically.

4. Report back the activity URL from the script's output.

If credentials are missing (`sync_to_strava.py` will say so), tell the
user to run `strava_auth.py` once first — that's an interactive,
one-time step they need to do themselves (it opens a browser
authorization flow), not something to automate on their behalf.
