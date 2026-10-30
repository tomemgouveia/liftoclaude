# Setup

## Requirements

- Python 3.11 or newer
- [`uv`](https://docs.astral.sh/uv/)
- A Strava API application

Install the project and its development dependencies:

```sh
uv sync
```

Use `uv run` for project commands; it runs them in the managed environment.

## Configure Strava

1. Create an app at [strava.com/settings/api](https://www.strava.com/settings/api)
   and note its Client ID and Client Secret.
2. Copy the example environment file and fill in the Strava credentials:

   ```sh
   cp .env.example .env
   ```

3. Authorize the app once:

   ```sh
   uv run strava-auth
   ```

   Follow the printed URL, then paste the redirect URL or authorization code
   into the terminal. The command saves the refresh token to `.env`; later
   uploads refresh it automatically.

To enable direct Liftosaur API access with `--from-api`, add
`LIFTOSAUR_API_KEY` to `.env`. This requires Liftosaur Premium; generate the key
under Settings > API Keys in the Liftosaur app. Without this key, use the MCP
and JSON-file workflow described in [Usage](usage.md).

## Claude Code network access

In a sandboxed Claude Code environment, allow outbound access to
`*.strava.com` for OAuth and Strava API calls. The wildcard is needed to cover
both `www.strava.com` and `developers.strava.com`.

The direct Liftosaur API workflow also needs access to `www.liftosaur.com`.
The MCP and JSON-file fallback does not use this host.
