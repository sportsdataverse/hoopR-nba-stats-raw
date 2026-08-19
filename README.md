# hoopR-nba-stats-raw

Raw cache of NBA Stats API (`stats.nba.com`) JSON. The scrapers here fill
`nba_stats/json/` — per-game payloads (`{endpoint}/{season}/{game_id}.json`),
season-level payloads (`{endpoint}/{season}/{variant}.json` or flat
`{endpoint}/{season}.json`), and per-period boxscores — and commit them to
git, one commit per season. The sibling `hoopR-nba-stats-data` compiles and
releases; it reads this tree and never writes it. Per-season tarballs of the
store are published as GitHub Release assets under the `nba-stats-raw-json`
tag (`.bundles/nba_stats_json_YYYY.tar.gz`).

Seasons are labelled by **END year**: `1996` = 1995-96, `2026` = 2025-26.

## Setup

```sh
uv sync --dev            # this repo's own .venv (sportsdataverse + curl_cffi)
uv run pytest            # offline unit tests, no network
```

Scrape drivers resolve the interpreter via `scripts/_venv.sh` (override with
`NBA_VENV_PYTHON`) — they deliberately do NOT use `uv run`, which would resync
the venv under a running sweep. Scrapes need ProxyBonanza creds
(`PROXY_ENDPOINT` / `PROXY_KEY` / `PROXY_PKG`): the backfill and repair
drivers read them from `~/.Renviron`; the droplet cron sources
`~/.config/sdv/env`. Values are never echoed or committed.

**Run scrapes from a residential IP only** — stats.nba.com *hangs* (never
errors) on datacenter/cloud IPs.

## Run order

Daily flow (runs unattended on the sdv-data **droplet cron**, not GitHub
Actions — deploy details in
`hoopR-nba-stats-data/scripts/P0_DROPLET_RUNBOOK.md`):

```sh
bash scripts/daily_refresh.sh    # current END-year season sweep, then commit+push
```

Backfill flow (manual, in your own terminal):

```sh
bash scripts/backfill_nba_stats_raw.sh 1996:2026        # cold backfill (default range)
SCRAPE_WORKERS=4 bash scripts/backfill_nba_stats_raw.sh # gentler pace

# long ranges: crash-restart wrapper under tmux, + commit loop alongside
tmux new-session -d -s sweepsup 'bash scripts/supervise_sweep.sh 1996:2026'
bash scripts/commit_loop.sh <launcher_pid>              # commit seasons as they finish

bash scripts/commit_raw_json.sh                         # stage+commit+push, one commit/season
bash scripts/publish_season_bundles.sh                  # refresh .bundles/ release assets
```

Repair flow (recurring — run after any large sweep):

```sh
bash scripts/refill_empty_payloads.sh --check           # census of empty {} captures, no network
bash scripts/refill_empty_payloads.sh                   # delete + refetch exactly those
bash scripts/refill_empty_payloads.sh 2015:2026         # or a season range / --endpoint <slug>
```

Watch a running job live:

```sh
tail -f "$(ls -t logs/nba_stats_raw_backfill_*.log | head -1)"   # backfill
tail -f logs/nba_stats_03_refill_empty.log                                    # repair
tail -f "$(ls -t logs/watchdog_*.log | head -1)"                 # supervisor
```

Pace/behavior tuning is env-only: `SCRAPE_WORKERS`,
`SDV_PY_NBA_STATS_TIMEOUT`, `HEARTBEAT_SECS`, `SESSION_MAX_REQUESTS`,
`SESSION_MAX_SECS`, `SESSION_SERVER_ERR_RETRIES` (see `CLAUDE.md` for the
full table and defaults).

## Resume story

Every stage is idempotent and re-runnable:

- **Sweeps** resume by presence: payloads already on disk are skipped, so
  Ctrl-C + rerun only fetches what's missing. Writes are atomic
  (tmp + rename); `*.json.tmp` is gitignored.
- **supervise_sweep.sh** relaunches a died sweep (each restart resumes),
  stops cleanly on "sweep complete", and gives up after `MAX_RESTARTS` so a
  real crash loop surfaces.
- **commit_raw_json.sh / commit_loop.sh** are safe to re-run any time: only
  seasons with new or changed files produce a commit. The commit subject
  `NBA Stats Update (Start: YYYY End: YYYY)` is load-bearing — keep it
  verbatim.
- **Repair** exists because resume-by-presence has one blind spot: a payload
  persisted empty (`{}`) blocks its own refetch forever. The write guard now
  refuses empty payloads; `refill_empty_payloads.sh` repairs files already on
  disk. Deleted files are tracked in git, so `git checkout -- nba_stats/`
  undoes a bad run.
