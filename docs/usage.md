# Usage

## Try a dry run

The repository includes a sample workout. This command makes no network
requests and needs no credentials:

```sh
uv run sync-to-strava tests/fixtures/sample_workout.json --dry-run
```

Review the printed payload. To upload the sample for real, once Strava
credentials are configured:

```sh
uv run sync-to-strava tests/fixtures/sample_workout.json
```

The command prints the resulting Strava activity URL.

## Choose a workout source

### Direct Liftosaur API

With `LIFTOSAUR_API_KEY` configured, sync by Liftosaur history record ID:

```sh
uv run sync-to-strava --from-api 1789147805585 --dry-run
uv run sync-to-strava --from-api 1789147805585
```

The dry run fetches and parses the workout but does not contact Strava.
`--from-api` requires Liftosaur Premium and the `www.liftosaur.com` host to be
reachable.

### MCP and JSON file

Without an API key, Claude Code can use the Liftosaur MCP tools to find and
retrieve a workout, then write a JSON file for the CLI. The repository's
[Claude instructions](../CLAUDE.md) describe this flow, including how to
include completed sets and avoid warmup or target sets.

Keep temporary workout files in `workouts/`, which is gitignored. Use a
separate filename for each sync. A dry run checks the file without Strava
credentials:

```sh
uv run sync-to-strava workouts/workout.json --dry-run
```

After a successful upload, remove the temporary file. If an upload fails,
keep it for retry or inspection.

## Privacy

By default, the CLI sets `hide_from_home=true` after uploading, which mutes an
activity from Strava feeds. This **does not** set activity visibility to
“Only You”; the Strava API does not provide a way to set that visibility.

To have uploads default to private, set the account-wide default under
**Strava app > Settings > Privacy Controls > Activities**. Pass `--public` to
skip muting an activity from feeds; this does not change its visibility.

## Limitations

- Exercise names are mapped best-effort to Strava exercise types. Unmatched
  exercises may appear as “Unknown,” though their sets, reps, and weights are
  still uploaded. See
  [Strava's supported exercises](https://developers.strava.com/docs/uploads/)
  and the mapping in `src/liftostrava/strava/exercise_map.py`.
- Strava's strength-activity upload format is not a published schema and may
  change.
- Strava's muscle-map visualization may not appear reliably for API-uploaded
  activities.
