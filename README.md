# Liftosaur → Strava

Sync strength workouts from [Liftosaur](https://www.liftosaur.com/) to Strava
with structured exercises, sets, reps, and weights.

## Get started

```sh
uv sync
cp .env.example .env
```

Add your Strava API app credentials to `.env`, then authorize once:

```sh
uv run strava-auth
```

Try a dry run with the included sample workout:

```sh
uv run sync-to-strava tests/fixtures/sample_workout.json --dry-run
```

## Documentation

- [Setup and credentials](docs/setup.md)
- [CLI, Claude/MCP workflows, and privacy](docs/usage.md)
- [Cloudflare Worker](docs/cloudflare.md)

For Claude Code workout-sync behavior, see [CLAUDE.md](CLAUDE.md).
