# hoopR-nba-stats-raw Copilot Instructions

## Project Context

This repo is a placeholder in the SportsDataverse `hoopR` NBA Stats
pipeline. The intended role is the raw cache of NBA Stats API
(`stats.nba.com`) payloads for men's professional basketball — sibling to
`hoopR-nba-raw` (ESPN cache) and to `wehoop-wnba-stats-raw` (women's
pro stats placeholder).

Today the repo contains only `README.md`, `.gitignore`, the RStudio
project file, and these governance docs. The NBA Stats API **is** the
raw layer, and the actual scrapers, schedules, and per-game JSON live
in the sibling `hoopR-nba-stats-data` repo. Until a "raw split" lands,
treat this repo as an empty namespace.

Pipeline (current state):

```
NBA Stats API -> hoopR-nba-stats-data [scrape + cache + push]
                        -> sportsdataverse-data releases
                        -> hoopR R package (load_nba_*)
```

Pipeline (intended state, once activated):

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
- The repo currently has no CI, no scrapers, and no release surface.
- Operational scrape work happens in `hoopR-nba-stats-data` — point
  changes there until the raw-split activation lands.
- Do not add Python or R scrapers here without a matching deletion from
  `hoopR-nba-stats-data`; the two cannot run in parallel on the same
  output paths.

## Build & Development Commands

There are no build commands today. When activated, the entry points
would mirror `hoopR-nba-stats-data`:

```sh
# Future state (in this repo):
bash scripts/daily_nba_stats_raw_scraper.sh -s 2025 -e 2025 -r false

Rscript R/nba_stats_01_scrape_schedules.R              -s 2025 -e 2025 -r false
Rscript R/nba_stats_02_scrape_pbp.R                    -s 2025 -e 2025 -r false
Rscript R/nba_stats_03_scrape_boxscoretraditionalv2.R  -s 2025 -e 2025 -r false
```

Current state: run the equivalents in `hoopR-nba-stats-data`.

## Code Style (for future contributions)

- Match the conventions of `hoopR-nba-stats-data`:
  - **R 4.0.0+**, tidyverse style: snake_case, 2-space indent, `%>%` pipes.
  - `optparse` for CLI parsing on every `Rscript` entry point.
  - `purrr::pluck()` chains with `%||%` fallbacks for NBA Stats result-set parsing.
  - `dplyr::select(dplyr::any_of(...))` over bare-name selects (column drift).
  - One file per task under `R/` (e.g., `nba_stats_0X_*.R`).
- **Season encoding**: NBA seasons indexed by **start year**; the
  `years_vec <- (start - 1):(end - 1)` shift inside scrapers is intentional.
- **Proxy support**: NBA Stats rate-limits aggressively — production scrapes
  go through the rotating proxy pool. Never commit proxy
  IPs/credentials; route them through GitHub Actions secrets.

## Activation Plan

When this repo becomes the real raw cache:

1. Move the per-game JSON tree `nba_stats/json/pbp/{season}/{game_id}.json`
   from `hoopR-nba-stats-data` to this repo, and update `hoopR`'s
   `load_nba_pbp()` family to read from
   `raw.githubusercontent.com/sportsdataverse/hoopR-nba-stats-raw/main/nba_stats/...`.
2. Move `R/nba_stats_0[1-3]_*.R` here; keep the compile/release scripts in
   `hoopR-nba-stats-data`.
3. Add `.github/workflows/hoopR_nba_stats_data_trigger.yml` to fire
   `repository_dispatch` (event-type `daily_nba_stats_data`) on every push
   to `main`.
4. Wire the umbrella workflow `daily_nba_stats_raw.yml` with the same
   cadence/inputs as `hoopR-nba-stats-data/daily_nba_stats.yml`, offset
   ~2 hours earlier so the scrape lands before the parser pulls.

## Cross-Repo References

- Active sibling (NBA Stats scrape today): <https://github.com/sportsdataverse/hoopR-nba-stats-data>
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
