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
- `POST /api/sync` with `{"workout_id": "..."}` syncs one workout.
- `GET`/`POST /api/settings` read and save the signed-in user's Liftosaur key
  and timezone for the `/connect` page. `/connect/strava` and
  `/connect/strava/callback` remain server-side OAuth redirects.

`GET /` (without `Accept: text/html`) and `POST /` still work for Shortcuts.

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
