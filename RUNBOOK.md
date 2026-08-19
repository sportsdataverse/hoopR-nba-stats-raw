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
| 00 | `00_preflight.sh` | Import preflight, proxy env, and a `--check` census that sizes the sweep without fetching | yes | no |
| 10 | `10_sweep.sh` | The scrape. Resume is presence-on-disk, so Ctrl-C + rerun is safe | yes | **yes** |
| 20 | `20_refill_empty.sh` | Deletes payloads persisted as empty and refetches them | yes | **yes** |
| 30 | `30_schedule_master.sh` | Rebuilds the schedule master + coverage index | yes | no |
| 40 | `40_commit.sh` | Commit + push, one commit per season | yes | no |
| 50 | `50_publish_bundles.sh` | Refreshes the per-season tarballs on `nba-stats-raw-json` | yes | no |

Stage 30 is **advisory**: the master is a claim *about* the payloads, so a
failure there does not stop stage 40 from committing the payloads themselves.
Every other stage stops the chain on failure.

### Python stages (`python/`)

The shell stages above are the pipeline's *steps*; these are the numbered
Python entry points they invoke. The directory listing IS the enumeration —
same convention as the `-data` siblings' `nba_stats_NN_*_creation.py`.

| # | Module | Does | Invoked by |
|---|---|---|---|
| 01 | `nba_stats_01_raw_json_scrape.py` | The sweep: discovery, season-level and per-game captures | `10_sweep.sh`, and `00_preflight.sh` via `--check` |
| 02 | `nba_stats_02_leaguegamelog_player_topup.py` | PLAYER variant of `leaguegamelog`, landing additively beside the sweep's team rows | **no mode** — run manually |
| 03 | `nba_stats_03_refill_empty.py` | Census + refill of payloads persisted as empty `{}` | `20_refill_empty.sh` |
| 99 | `nba_stats_99_schedule_master_creation.py` | Schedule master + coverage index | `30_schedule_master.sh` |

The numbers are **intended build order, not run order** — 02 is a real stage
that no mode currently lists, and that is deliberate rather than an omission.
A retired stage leaves a HOLE; successors are never renumbered, because the
numbers mean the same thing across the twin repos.

Unnumbered modules beside them are **import seams**, not stages: `endpoints.py`,
`period_capture.py`, `season_capture.py` re-export the shared engine from
sdv-py, and `schedule_master.py` holds the logic that stage 99 is a thin entry
point over.

## Modes

| Mode | Seasons default | Stages | Workers |
|---|---|---|---|
| `daily` | current END-year season | `10,30,40` | 4 |
| `backfill` | `1996:current` | `00,10,20,30,40,50` | 6 |
| `repair` | current season | `20,30,40` | inherited |

```sh
bash scripts/run_pipeline.sh                        # daily, current season
bash scripts/run_pipeline.sh -m backfill            # cold backfill
bash scripts/run_pipeline.sh -m backfill -s 2015:2020
bash scripts/run_pipeline.sh -m repair -s 2019
bash scripts/run_pipeline.sh -k 10,40 -s 2026       # only these stages
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
residential IP, under tmux, with `scripts/supervise_sweep.sh` as the
crash-restart wrapper and `scripts/commit_loop.sh` committing finished seasons
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

## Legacy entry points

`daily_refresh.sh` and `backfill_nba_stats_raw.sh` are kept as thin shims that
delegate to the orchestrator, so the droplet cron entry and any muscle memory
keep working. New work goes in a stage, never in a shim.
