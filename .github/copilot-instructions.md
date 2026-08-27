# hoopR-nba-stats-raw Copilot Instructions

## Project Context

This repo is the raw cache of NBA Stats API (`stats.nba.com`) payloads
for men's professional basketball — sibling to `hoopR-nba-raw` (ESPN
cache) and to `wehoop-wnba-stats-raw` (women's pro stats).

**The raw split has landed.** This repo now holds the Python scrapers
(`python/`), the bash entry points (`scripts/`), ~490k committed per-game
and per-season JSON payloads under `nba_stats/`, and the per-season
`.bundles/nba_stats_json_YYYY.tar.gz` archives that let consumers fetch a
season without cloning the whole tree. Earlier revisions of this file
described the repo as an empty placeholder; that is no longer true.

Pipeline (current state):

```
NBA Stats API -> hoopR-nba-stats-raw [HERE: scrape + cache + push trigger]
                        -> hoopR-nba-stats-data [compile + release]
                        -> sportsdataverse-data releases
                        -> hoopR R package (load_nba_*)
```

Do not confuse with:

- `hoopR-nba-raw` — ESPN NBA cache (actively maintained Python scrape)
- `hoopR-mbb-raw` — ESPN men's college basketball cache
- `wehoop-wnba-stats-raw` — WNBA Stats placeholder, same shape as this repo

## Repository Workflow

- `main` is the default branch.
- Operational scrape work happens HERE. `hoopR-nba-stats-data` compiles
  and releases; it must not scrape the same output paths in parallel.
- Python lives in `python/`, tests in `tests/`, and `scripts/` holds bash
  entry points only. `pyproject.toml` + `uv.lock` at the repo root pin the
  environment; resolve the interpreter by sourcing `scripts/_venv.sh`
  (never hardcode a path to a sibling repo's venv).

## Build & Development Commands

```sh
uv sync --dev            # create/refresh .venv from uv.lock
uv run pytest            # offline unit tests
uv run ruff check python tests

# Scrape entry points (bash only; each sources scripts/_venv.sh).
bash scripts/daily_refresh.sh                    # current season top-up
bash scripts/backfill.sh 1996:2026               # full cold backfill
bash ops/supervise_sweep.sh 2016:2026        # restart-on-death wrapper
bash ops/publish_season_bundles.sh           # refresh .bundles/*.tar.gz
```

Season encoding is the **end year** (`2026` = 2025-26).

## Code Style

- **Python is the scrape language here.** There is no `R/` directory; the
  R scrapers this repo once planned to inherit were superseded.
- polars 1.x modern API only; fully type-hinted new modules; ruff-clean
  against the pinned rule set in `pyproject.toml`.
- **Season encoding**: NBA seasons are labelled by **end year** (`2026` =
  2025-26) — commit subjects (`commit_raw_json.sh`), `daily_refresh.sh`'s
  current-season math, the per-game store dirs (`season_of()` in
  `python/period_capture.py`), and the sdv-py raw-store convention all use
  it. One exception: the season-level half of the store keys its dirs by
  start year (`{endpoint}/2023/` holds 2023-24 — see the comment in
  `python/nba_stats_10_leaguegamelog_player_topup.py`).
- **TLS fingerprinting**: `stats.nba.com` blocks plain `requests` by JA3 —
  it produces a *silent timeout*, not an error, so a "hang" is usually this.
  All traffic goes through `curl_cffi` with `impersonate="chrome"`; see
  `sportsdataverse.scrape.stats.session_transport` (sdv-py; moved from `python/session_transport.py` in #325).
- **Per-endpoint season floors** live in `ENDPOINT_MIN_SEASON` with
  `_skip_endpoint()` as the single owner of the comparison
  (`python/nba_stats_01_raw_json_scrape.py`). Add a floor there, not at a call site.
- **Proxy support**: NBA Stats rate-limits aggressively — production scrapes
  go through the rotating proxy pool. Never commit proxy
  IPs/credentials; route them through GitHub Actions secrets.

## Cross-Repo References

- Downstream compile/release sibling: <https://github.com/sportsdataverse/hoopR-nba-stats-data>
- Downstream R package: <https://github.com/sportsdataverse/hoopR>
- ESPN NBA pair (same shape this repo would mirror): <https://github.com/sportsdataverse/hoopR-nba-raw>, <https://github.com/sportsdataverse/hoopR-nba-data>
- Release tags: <https://github.com/sportsdataverse/sportsdataverse-data/releases>

## Conventional Commits

Use: `type(scope): description`. Common types: `feat`, `fix`, `chore`,
`ci`, `docs`, `refactor`. Use `type!:` or a `BREAKING CHANGE:` footer
for breaking changes.

When the raw split lands and this repo starts emitting daily scrape
commits, keep the load-bearing subject verbatim:

```
NBA Stats Update (Start: 2025 End: 2025)
```

**Important: Never include AI agents or assistants (e.g., Claude, Copilot, Cursor, GPT, Gemini) as co-authors on commits.** Omit all `Co-Authored-By` trailers referencing AI tools. This applies whether the change was generated, refactored, or reviewed with AI assistance — the human author is the sole attributable contributor.
