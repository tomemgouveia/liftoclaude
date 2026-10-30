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

## Deploy

The Worker stores the current Strava access token, refresh token, and expiry in
Cloudflare KV. Create a namespace, then replace the placeholder namespace ID
in `wrangler.toml` with the ID printed by Wrangler:

```sh
npx wrangler kv namespace create STRAVA_TOKEN_STORE
```

Set the required secrets and deploy:

```sh
npx wrangler secret put STRAVA_CLIENT_ID
npx wrangler secret put STRAVA_CLIENT_SECRET
npx wrangler secret put STRAVA_REFRESH_TOKEN
npx wrangler secret put LIFTOSAUR_API_KEY
npx wrangler deploy
```

`STRAVA_REFRESH_TOKEN` is only the bootstrap value used when KV has no token
state. After the first successful refresh, the Worker stores and uses the
rotated token pair in KV.

Local `wrangler dev` uses a local KV store and does not share the production
namespace contents. Avoid concurrent sync requests: KV is eventually
consistent, so concurrent refreshes can race while Strava rotates tokens.
