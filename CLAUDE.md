# CLAUDE.md — hoopR-nba-stats-raw

**Active** raw cache of NBA Stats API (`stats.nba.com`) JSON for the
SportsDataverse hoopR NBA pipeline. The raw split has landed: this repo holds
the Python scrapers (`python/`), the bash drivers (`scripts/`), ~490k committed
per-game and per-season payloads under `nba_stats/json/`, and the per-season
`.bundles/nba_stats_json_YYYY.tar.gz` release assets (tag `nba-stats-raw-json`)
that let consumers fetch a season without cloning the tree. Scrape + cache +
commit happen HERE; compile/release happens in the sibling
`hoopR-nba-stats-data`. Contact: Saiem Gilani <saiem.gilani@gmail.com>. MIT.

```text
NBA Stats API -> hoopR-nba-stats-raw [HERE: scrape + cache + commit]
                        -> hoopR-nba-stats-data [compile + release]
                        -> sportsdataverse-data releases
                        -> hoopR R package (load_nba_*)
```

Don't confuse with `hoopR-nba-raw` (ESPN NBA cache) or `wehoop-wnba-stats-raw`
(the WNBA analog of this repo — same numbered `*_stats_NN_*` capture-stage shape, its own
period math).

## Layout

`pyproject.toml` + `uv.lock` pin this repo's own `.venv` (`uv sync --dev`).
Every driver resolves the interpreter by sourcing `scripts/_venv.sh`
(`$NBA_VENV_PYTHON` override → repo `.venv`) — deliberately NOT `uv run`,
which would resync the venv under a running multi-hour sweep.

`python/` — the scrape package:

- **Capture stages** — one scope each, independently runnable, resumable from
  disk, sharing `_capture_runtime.py` for the proxy/transport/heartbeat
  plumbing. `01_season_endpoints` persists `leaguegamelog`;
  `02_game_endpoints` reads that index and captures one payload per game per
  endpoint; `03_period_boxscores` sizes each game from its persisted
  `playbyplayv3` and captures the per-period boxscores. `ENDPOINT_MIN_SEASON`
  + `_skip_endpoint()` (now in `_capture_runtime.py`) remain the single owner
  of per-endpoint season floors.
- `endpoints.py` — declarative capture registry; each endpoint's parameter
  matrix is derived from its own wrapper signature, so new upstream endpoints
  are captured without an edit. Drives both this repo and the WNBA sibling.
- `season_capture.py` — season-level writes: `{endpoint}/{season}/{variant}.json`
  or flat `{endpoint}/{season}.json`; atomic, presence-skip resumable,
  sequential (a few hundred calls/season). Refuses to persist an empty `{}`.
- `period_capture.py` — NBA per-period request windows, delegated to sdv-py's
  `nba_lineups._period_start_range` so capture can't drift from the reader.
- `sportsdataverse.scrape.stats.session_transport` (lives in sdv-py since #325;
  was `python/session_transport.py`) — thread-local sticky `curl_cffi` sessions, one proxy
  per session; rotates on `SESSION_MAX_REQUESTS` / `SESSION_MAX_SECS` / any
  fault; retries transient 500s in-session (`SESSION_SERVER_ERR_RETRIES`).
- `sportsdataverse.scrape.stats.proxy` (sdv-py) — ProxyBonanza round-robin pool. `PROXY_ENDPOINT` / `PROXY_KEY` /
  `PROXY_PKG` read from env at call time; `redact()` before logging any URL.
- `sportsdataverse.scrape.stats.observability` (sdv-py) — `Progress` heartbeat (rate + ETA every
  `HEARTBEAT_SECS`), miss classification (`endpoint_absent` / `timeout` /
  `throttled` / `error`), `ProxyHealth` quarantine, `Degradation` alerts.
  Structured fetch log: `logs/errors.jsonl`.
- `nba_stats_20_refill_empty.py` — repair: deletes season-level files ≤2 bytes (exactly
  `{}` / `[]`) and refetches those tuples. See "Repair flow".
- `nba_stats_10_leaguegamelog_player_topup.py` — one-off top-up of the PLAYER `leaguegamelog`
  variant (`{season_type}_p.json` beside the team captures). Complete; kept
  for reference as the pattern for additive variant top-ups.

`scripts/` — **drivers only** (each sources `_venv.sh`): `run_pipeline.sh` (the
one orchestrator), `daily_refresh.sh` and `backfill.sh` (thin shims onto
`-m daily` / `-m backfill`), and `pipeline/NN_*.sh` (the numbered stages).

`ops/` — recurring operational tools that are NOT stages, run by hand:
`supervise_sweep.sh`, `commit_loop.sh`, `commit_raw_json.sh`,
`refill_empty_payloads.sh`, `publish_season_bundles.sh`.

`tests/` — offline unit tests (`uv run pytest`; no network), run by the only
workflow in `.github/workflows/` (`tests.yml`).

## Daily flow — droplet cron, NOT GitHub Actions

`daily_refresh.sh` is the cron entry point, and the cron lives OUT of this
repo: it runs on the **sdv-data droplet** (stats.nba.com hangs — never errors
— on datacenter/cloud IPs, so no GHA job can host the scrape; the only in-repo
workflow is offline tests). Droplet setup, the `~/.config/sdv/env` secrets
file the scripts source, the egress canary, and the cron entries are
documented in the sibling repo:
`hoopR-nba-stats-data/scripts/P0_DROPLET_RUNBOOK.md`.

The script computes the current END-year season (October rolls to the next
year), sweeps it idempotently, and only runs `commit_raw_json.sh` when the
sweep exits 0 — a failed sweep never publishes a partial season.

## Backfill flow

`scripts/backfill.sh [LO:HI]` (default `1996:2026`) is the cold-backfill
entry point — a compatibility shim over `run_pipeline.sh -m backfill`, kept so
existing invocations keep working (it was `backfill_nba_stats_raw.sh` before
the sweep was split into numbered stages). Run it YOURSELF in a terminal on a
residential IP. It exports
`PROXY_*` from `~/.Renviron` (R reads that file; Python does not) and fails
fast if they're missing. Resumable — on-disk payloads are skipped, Ctrl-C +
rerun is always safe. `supervise_sweep.sh` is the crash-restart wrapper
(relaunches on abnormal death, stops on "sweep complete", gives up after
`MAX_RESTARTS`); launch it under tmux. `commit_loop.sh <launcher_pid>` runs
alongside a long sweep and commits finished seasons on a timer (`INTERVAL`,
default 300s) so a crashed box can't lose gigabytes of captured work.

`commit_raw_json.sh` stages both store shapes
(`{endpoint}/{season}/*.json` and flat `{endpoint}/{season}.json`), one
commit per season. The subject `NBA Stats Update (Start: YYYY End: YYYY)` is
load-bearing verbatim — downstream tooling parses the years.
`publish_season_bundles.sh` refreshes the per-season tarballs on the
`nba-stats-raw-json` release (`DRY_RUN=1` to build without uploading).

## Repair flow (recurring, not one-off)

Resume is `path.exists()` — presence, not content — so any payload persisted
empty blocks its own refetch forever. The write guard now refuses empty `{}`
payloads, but files already on disk must be repaired:
`bash ops/refill_empty_payloads.sh` (`--check` = census only, no network;
optional `LO:HI` / `--endpoint <slug>`). Run it after any large sweep;
residential IP, same proxy requirements as the backfill. Deleted files are
tracked in git, so `git checkout -- nba_stats/` restores them if a run goes
wrong.

## Conventions & gotchas

- **Season = END year** on disk and in CLI args (1995-96 ⇒ `1996`;
  `2026` = 2025-26). Disk dirs and commit labels use it verbatim.
- **TLS/JA3**: `stats.nba.com` blocks plain `requests` with a *silent
  timeout*, not an error — a "hang" is usually this. All traffic goes through
  `curl_cffi` `impersonate="chrome"` (`sportsdataverse.scrape.stats.session_transport`).
- **Rate tuning is env-only** — never hardcode pace. The knobs:

  | Env | Default | Meaning |
  | --- | --- | --- |
  | `SCRAPE_WORKERS` | 6 (daily: 4) | per-game fetch threads |
  | `SDV_PY_NBA_STATS_TIMEOUT` | 30 (drivers set 90) | per-request timeout (s) |
  | `HEARTBEAT_SECS` | 60 | progress/IP-health log cadence |
  | `SESSION_MAX_REQUESTS` / `SESSION_MAX_SECS` | 120 / 300 | sticky-session rotation |
  | `SESSION_SERVER_ERR_RETRIES` | 2 | in-session 500 retries |
  | `PROXY_ENDPOINT` / `PROXY_KEY` / `PROXY_PKG` | — | ProxyBonanza creds (required) |
  | `<ENDPOINT>_MIN_SEASON` | per-endpoint | floor override / un-park |

- Never commit proxy IPs/credentials; creds come from `~/.Renviron` (manual
  runs) or `~/.config/sdv/env` (droplet). `redact()` proxy URLs in logs.
- Writes are atomic (tmp + rename); `*.json.tmp` is gitignored — a commit can
  never catch a half-written file.
- Raw repos commit raw JSON to git (the intentional SDV pattern) — don't warn
  about repo bloat.
- Code/infra commits: Conventional Commits (`feat(scrape):`, `chore:`). Never
  add AI co-author trailers.

## Cross-repo

- Compile/release sibling: <https://github.com/sportsdataverse/hoopR-nba-stats-data>
- WNBA analog: <https://github.com/sportsdataverse/wehoop-wnba-stats-raw>
- Downstream R package: <https://github.com/sportsdataverse/hoopR>
- ESPN siblings: <https://github.com/sportsdataverse/hoopR-nba-raw> · <https://github.com/sportsdataverse/hoopR-nba-data>
- Release tags: <https://github.com/sportsdataverse/sportsdataverse-data/releases>
