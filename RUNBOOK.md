# RUNBOOK — NBA stats raw pipeline

Every operation on this repo is a numbered stage under `scripts/pipeline/`,
sequenced by the single orchestrator `scripts/run_pipeline.sh`. A daily refresh
and a cold backfill are **the same stages with different env**, not two
scripts — that separation is what let the two drivers drift apart previously,
one growing a census gate and a commit loop while the other grew the
schedule-master rebuild, and neither having the other's.

## Stages

| # | Stage | Does | Idempotent? | Needs network |
|---|---|---|---|---|
| 00 | `00_preflight.sh` | Import preflight, proxy env, and a `--check` on each capture stage that sizes the work without fetching | yes | no |
| 10 | `10_season_endpoints.sh` | Season-level payloads. Persists `leaguegamelog`, the game index 11 and 12 read back | yes | **yes** |
| 11 | `11_game_endpoints.sh` | Per-game whole-game payloads | yes | **yes** |
| 12 | `12_period_boxscores.sh` | Per-period boxscores, sized from each game's persisted play-by-play | yes | **yes** |
| 20 | `20_refill_empty.sh` | Deletes payloads persisted as empty and refetches them | yes | **yes** |
| 30 | `30_schedule_master.sh` | Rebuilds the schedule master + coverage index | yes | no |
| 40 | `40_commit.sh` | Commit + push, one commit per season | yes | no |
| 50 | `50_publish_bundles.sh` | Refreshes the per-season tarballs on `nba-stats-raw-json` | yes | no |

Stage 30 is **advisory**: the master is a claim *about* the payloads, so a
failure there does not stop stage 40 from committing the payloads themselves.
Every other stage stops the chain on failure.

The capture stages 10 → 11 → 12 are ordered by a DATA dependency through the
store, not by shared memory: 10 persists the game index, 11 and 12 read it
back. Each can be run, resumed, re-run or skipped on its own.


### Python stages (`python/`)

One scope per stage — the directory listing IS the enumeration, same
convention as the `-data` siblings' `nba_stats_NN_*_creation.py`.

| # | Module | Scope | Reads | Invoked by |
|---|---|---|---|---|
| 01 | `nba_stats_01_season_endpoints.py` | season-level payloads | — | `10_season_endpoints.sh` |
| 02 | `nba_stats_02_game_endpoints.py` | one payload per game per endpoint | `leaguegamelog` on disk | `11_game_endpoints.sh` |
| 03 | `nba_stats_03_period_boxscores.py` | per-period boxscores | `leaguegamelog` + each game's `playbyplayv3` on disk | `12_period_boxscores.sh` |
| 10 | `nba_stats_10_leaguegamelog_player_topup.py` | PLAYER variant of `leaguegamelog` | — | **no mode** — run manually |
| 20 | `nba_stats_20_refill_empty.py` | repair: empty `{}` payloads | the store | `20_refill_empty.sh` |
| 99 | `nba_stats_99_schedule_master_creation.py` | schedule master + coverage index | the whole store | `30_schedule_master.sh` |

Bands, so a new stage never renumbers its neighbours: **01-09** capture scopes,
**10-19** additive top-ups, **20-29** repair, **99** index rebuild. A retired
stage leaves a HOLE — the numbers must mean the same thing in the WNBA twin.

Every capture stage takes the same CLI: `[--check] [--game-ids=FILE] LO:HI`.
`--check` sizes the work and verifies the proxy pool without fetching.

Unnumbered modules are **import seams**, not stages — no `main()`, they capture
nothing:

- `_capture_runtime.py` — the plumbing every capture stage shares: league
  binding, per-endpoint season floors, proxy pool + sticky transport, progress
  heartbeat, health summary, and the game-index read. Kept in one place rather
  than duplicated three ways.
- `endpoints.py`, `period_capture.py`, `season_capture.py` — re-export the
  shared sdv-py engine.
- `schedule_master.py` — the logic stage 99 is a thin entry point over.

## Modes

| Mode | Seasons default | Stages | Workers |
|---|---|---|---|
| `daily` | current END-year season | `10,11,12,30,40` | 4 |
| `backfill` | `1996:current` | `00,10,11,12,20,30,40,50` | 6 |
| `repair` | current season | `20,30,40` | inherited |

```sh
bash scripts/run_pipeline.sh                        # daily, current season
bash scripts/run_pipeline.sh -m backfill            # cold backfill
bash scripts/run_pipeline.sh -m backfill -s 2015:2020
bash scripts/run_pipeline.sh -m repair -s 2019
bash scripts/run_pipeline.sh -k 11,12 -s 2026       # only these stages
DRY_RUN=1 bash scripts/run_pipeline.sh -m backfill  # print the plan, run nothing
```

Watch a run:

```sh
tail -f logs/pipeline_<mode>_<stamp>.log
```

Every run ends with a grep-able `[run] EXIT=<rc>` line. Do not trust an earlier
"complete" message — stages can print one before a later stage fails.

## Season convention

**Season = END year**, on disk, in CLI args and in commit labels: 1995-96 is
`1996`, and `2026` means 2025-26. October rolls the current season
forward, so for three months of the year the current season is not the calendar
year — `current_season()` in the orchestrator owns that math.

## Where it runs

Droplet cron, **not** GitHub Actions: `stats.nba.com` hangs rather than
errors on a datacenter IP, so no hosted runner can do the scrape. The only
in-repo workflow is offline tests. A cold backfill should be run by hand from a
residential IP, under tmux, with `ops/supervise_sweep.sh` as the
crash-restart wrapper and `ops/commit_loop.sh` committing finished seasons
on a timer so a crashed box cannot lose gigabytes of captured work.

## Rate tuning is env-only

Never hardcode pace — every knob is an environment variable so it can be
re-tuned without a code change:

| Env | Default | Meaning |
|---|---|---|
| `SEASONS` | per mode | Season or `LO:HI` range |
| `SCRAPE_WORKERS` | 4 daily / 6 backfill | Per-game fetch threads |
| `SDV_PY_NBA_STATS_TIMEOUT` | 90 | Per-request timeout (s) |
| `REFILL_APPLY` | 1 | `0` = stage 20 censuses only, refetches nothing |
| `DRY_RUN` | 0 | `1` = print the stage plan and exit |

## Layout — drivers vs operational tools

`scripts/` holds **drivers only**, so what is on the daily path is obvious:

| Path | Role |
|---|---|
| `scripts/run_pipeline.sh` | the one orchestrator |
| `scripts/daily_refresh.sh` | shim → `-m daily` (the droplet cron entry) |
| `scripts/backfill.sh` | shim → `-m backfill` |
| `scripts/pipeline/NN_*.sh` | the numbered stages |
| `scripts/_venv.sh` | sourced interpreter resolver |

`ops/` holds recurring operational tools that are **not** pipeline stages and
are run by hand: `supervise_sweep.sh` (crash-restart wrapper),
`commit_loop.sh` (commits a long sweep as it runs), `commit_raw_json.sh`,
`refill_empty_payloads.sh`, `publish_season_bundles.sh`.

## Legacy entry points

`daily_refresh.sh` and `backfill_nba_stats_raw.sh` are kept as thin shims that
delegate to the orchestrator, so the droplet cron entry and any muscle memory
keep working. New work goes in a stage, never in a shim.
