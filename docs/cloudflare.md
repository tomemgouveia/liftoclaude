# Cloudflare Worker

The Cloudflare Worker provides a hosted sync path. These instructions cover
local development and deployment; they are separate from the local CLI
workflow in [Usage](usage.md).

## Run locally with Docker

Build and run the Pywrangler local runtime from the repository root:

```sh
docker build -t liftosaur-worker .
docker run --rm -p 8787:8787 \
  --mount "type=bind,source=$(pwd)/src,target=/app/src" \
  --mount "type=bind,source=$(pwd)/src/liftostrava,target=/app/python_modules/liftostrava" \
  liftosaur-worker
```

The source mounts let you edit the Worker without rebuilding the image. For
the GET handler, create a local `.dev.vars` file containing
`LIFTOSAUR_API_KEY=...` and mount it:

```sh
docker run --rm -p 8787:8787 \
  -e LIFTOSAUR_DOTENV_PATH=/app/.dev.vars \
  --mount "type=bind,source=$(pwd)/src,target=/app/src" \
  --mount "type=bind,source=$(pwd)/src/liftostrava,target=/app/python_modules/liftostrava" \
  --mount "type=bind,source=$(pwd)/.dev.vars,target=/app/.dev.vars" \
  liftosaur-worker
```

With the Worker running, send a request to `http://localhost:8787/`, for
example:

```sh
curl -i http://localhost:8787/
```

`.dev.vars` is gitignored. The writable mount lets a rotated refresh token be
saved back to that file. Restart the container after a token rotation so
Wrangler reloads the bindings. The GET handler makes a live request to the
Liftosaur API.

## Web app

Opening the Worker URL in a browser serves a React app (source in `web/`)
that lists your Liftosaur workouts for a chosen date range (presets or custom
from/to dates, up to 366 days) and syncs the one you pick. Build it before
running or deploying the Worker, because `wrangler.toml` serves `web/dist`:

```sh
cd web && npm install && npm run build
```

For UI work, run the Worker (`pywrangler dev`) and then `npm run dev` in
`web/`; Vite proxies `/api` to `localhost:8787`. When using the Docker
command above, also mount `web/dist` into `/app/web/dist`.

The Worker's JSON API:

- `GET /api/workouts?start=YYYY-MM-DD&end=YYYY-MM-DD` lists workouts, newest
  first. Both bounds are inclusive days in the user's timezone and default to
  the last 7 days.
- `POST /api/sync` with `{"workout_id": "..."}` syncs one workout. Add
  `"heart_rate": [{"time": "<ISO 8601 with offset>", "bpm": 120}, ...]` to
  upload it with a heart-rate stream. A Shortcut can instead send two
  parallel lists of equal length, `"heart_rate": {"time": [...], "bpm": [...]}`,
  which avoids a "Repeat with each" loop. A `bpm` given as text such as
  `"72 count/min"` is read by its leading number. The Worker keeps samples inside the
  workout's window. If there are none, it uploads the workout without heart
  rate and says so. If there are some but they stop more than 60 seconds
  before the workout ends, it replies `425` ("not synced yet", nothing
  uploaded); add `"override": true` to upload with the partial heart rate
  anyway (only `true` counts; the default is to block). Omit `heart_rate` for the plain upload. Add `"dry_run": true` (with
  `heart_rate`) to get a JSON report of what the check saw (including how
  many items were unreadable, with examples), without uploading.
- `GET`/`POST /api/settings` read and save the signed-in user's Liftosaur key
  and timezone for the `/connect` page. `/connect/strava` and
  `/connect/strava/callback` remain server-side OAuth redirects.

`GET /` (without `Accept: text/html`) and `POST /` still work for Shortcuts.
`GET /` returns the compact `{id, name, date, start, end}` list (`start` and
`end` are the workout window in UTC, for querying Apple Health); add `?brief=1` to
`/api/workouts` for the same compact shape with a date range.

## Heart rate from a Shortcut

To add heart rate to a synced workout, the Shortcut sends the Apple Health
samples along with the workout id. Without a "Repeat with each" loop:

1. `GET /` and pick a workout. Each item has `start` and `end` (UTC).
2. "Find Health Samples" (Type = Heart Rate). Filtering to the workout's
   window keeps the request small; the Worker also filters, so sending a
   wider range works.
3. `POST /api/sync` with a JSON body: `workout_id` (text) and `heart_rate`
   (a dictionary) with `time` set to the samples' **Start Date** and `bpm`
   set to the **Health Samples** themselves, both as plain variables. Do not
   use "Get Details of Health Samples" for these: its output arrived empty.
   Shortcuts turns each list into text with one value per line, which the
   Worker reads (dates as ISO 8601 such as `2026-11-12T08:47:34Z`).
4. Add `"dry_run": true` first. The response reports `received`,
   `unreadable` (with examples), `samples_in_window`, first and last sample,
   the workout's start and end, `covers_workout`, and `shape` (the types and
   lengths of what arrived, never the values).
5. A `425` means some samples exist but stop more than 60 seconds before the
   workout ends (usually the watch has not finished syncing); nothing was
   uploaded. No samples at all uploads the workout without heart rate.

Heart rate only lands densely in Apple Health while the Watch is recording a
workout session. Outside one, the Watch logs a sample every few minutes, so
the workout window has gaps or stops early, and the Worker answers `425`
every time, however long you wait (if there are no samples at all, it uploads
without heart rate). Start a workout on the Watch (for
example Strength Training) before lifting, or omit `heart_rate` to sync the
workout without it.

## Access authentication for users and Shortcuts

The Worker verifies the `Cf-Access-Jwt-Assertion` header. For a human Access
login it looks up the user by the verified email claim. For a service-token
request it looks up the user by the verified `common_name` claim, which is the
service token's Client ID.

Create a separate Access service token for each user's Shortcut. Store only
its Client ID in D1; keep the Client Secret in that user's Shortcut. Add the
lookup column and unique index to the existing `users` table once:

```sql
ALTER TABLE users ADD COLUMN access_service_token_id TEXT;

CREATE UNIQUE INDEX users_access_service_token_id_unique
ON users(access_service_token_id);
```

Then associate each Client ID with its user:

```sql
UPDATE users
SET access_service_token_id = '<CLIENT_ID>'
WHERE email = '<USER_EMAIL>';
```

Use the Client ID value ending in `.access`, not the Client Secret. A service
token identifies the Shortcut, not a human, so sharing one token between users
would make their requests indistinguishable.

## Onboarding a user

1. In Cloudflare Zero Trust, create a service token for the user's
   Shortcut and add it to the Access application's policy. Add the user's
   email to a policy too, so they can sign in to the onboarding page.
2. Ask the user to open `https://<worker>/connect` and sign in with that
   email. This creates their `users` row. There they paste their Liftosaur
   API key (Settings > API Keys, Premium), confirm their timezone, and click
   **Connect Strava**.
3. Link their service token to the row (see the `UPDATE` above) and give
   them the Client ID and Secret for their Shortcut headers.

Credentials (Liftosaur key, Strava tokens) are stored AES-GCM encrypted in
D1 using `CREDENTIALS_SECRET`. Rows saved before encryption was added are
read as plaintext and are encrypted the next time they are saved.

## Deploy

Apply the D1 migrations once (`users.timezone` and the nullable
`credentials` columns; the SQL lives in the gitignored
`private/d1.py`).

In your Strava API settings (strava.com/settings/api) set **Authorization
Callback Domain** to the Worker's domain.

Set the secrets and deploy:

```sh
npx wrangler secret put STRAVA_CLIENT_ID
npx wrangler secret put STRAVA_CLIENT_SECRET
openssl rand -base64 32 | npx wrangler secret put CREDENTIALS_SECRET
npx wrangler deploy
```

Keep a backup of `CREDENTIALS_SECRET`: losing it makes every stored
credential unreadable and every user has to reconnect.

Avoid concurrent sync requests for the same user: concurrent token
refreshes can race while Strava rotates refresh tokens.
