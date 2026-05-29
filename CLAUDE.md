# CLAUDE.md — hoopR-nba-stats-raw Development Guide

## Repo Overview

`hoopR-nba-stats-raw` is a placeholder slot in the SportsDataverse `hoopR`
NBA Stats pipeline. The intended role is the "raw" cache of NBA Stats API
(`stats.nba.com`) payloads for men's professional basketball — sibling to
`hoopR-nba-raw` (ESPN) on the men's pro side and to `wehoop-wnba-stats-raw`
on the women's pro side.

At the moment the repo is intentionally near-empty (only `README.md`,
`.gitignore`, and the RStudio project file). The NBA Stats API
*is* the raw layer for that data source, and the actual scrapers, schedule
files, per-game JSON, and play-by-play snapshots all live in the sibling
**`hoopR-nba-stats-data`** repo. Until per-game JSON is split out into a
dedicated cache, downstream consumers should read from `hoopR-nba-stats-data`
directly.

- **Repo type:** raw cache placeholder (no R package, no Python module)
- **Data source:** NBA Stats API (`stats.nba.com`)
- **Active sibling:** `hoopR-nba-stats-data` — the R-side scrapers + cache
- **Contact:** Saiem Gilani <saiem.gilani@gmail.com>

## Pipeline Position

```
NBA Stats API (stats.nba.com)
        |
        v
  hoopR-nba-stats-data   <-- scrape + cache happens HERE today
        | push to main
        v
  sportsdataverse-data releases
        | piggyback
        v
  hoopR R package (load_nba_*)
```

The slot `hoopR-nba-stats-raw` exists for symmetry with the ESPN-side pair:

| Source       | Raw cache                | Parser / release builder      |
| ------------ | ------------------------ | ----------------------------- |
| ESPN (NBA)   | `hoopR-nba-raw`          | `hoopR-nba-data`              |
| NBA Stats    | `hoopR-nba-stats-raw` *  | `hoopR-nba-stats-data`        |
| ESPN (MBB)   | `hoopR-mbb-raw`          | `hoopR-mbb-data`              |
| KenPom       | (none)                   | `hoopR-kp-data`               |

\* placeholder only — see "Activation Plan" below for the split that would
   move per-game JSON into this repo.

## Build & Development Commands

There are no scrapers, no R package, no `DESCRIPTION`, and no `requirements.txt`
in this repo today. Operational commands belong in `hoopR-nba-stats-data`:

```sh
# Run the active NBA Stats daily scrape (in hoopR-nba-stats-data, not here)
bash scripts/daily_nba_stats_scraper.sh -s 2025 -e 2025 -r false

# Direct R entry points (also in hoopR-nba-stats-data)
Rscript R/nba_stats_01_scrape_schedules.R              -s 2025 -e 2025 -r false
Rscript R/nba_stats_02_scrape_pbp.R                    -s 2025 -e 2025 -r false
Rscript R/nba_stats_03_scrape_boxscoretraditionalv2.R  -s 2025 -e 2025 -r false
```

If/when the raw split lands here, the scrape entry point will mirror the
wehoop-wbb-raw pattern: `scripts/daily_nba_stats_raw_scraper.sh -s ... -e ...
-r <true|false>` with one umbrella workflow that commits the cumulative
`nba_stats/` output and fires a `repository_dispatch` against
`hoopR-nba-stats-data`.

## Repo Layout (current)

```
README.md                     # one-line stub
.gitignore                    # standard R ignore set
hoopR-nba-stats-raw.Rproj     # RStudio project shell
.github/
  ISSUE_TEMPLATE/             # bug + feature templates (this PR)
  pull_request_template.md
CLAUDE.md                     # this file
CONTRIBUTING.md
CODE_OF_CONDUCT.md
LICENSE / LICENSE.md          # MIT
```

There is intentionally no `R/`, no `python/`, no `scripts/`, no
`requirements.txt`, no `DESCRIPTION`, and no workflows yet — keeping the
placeholder clean lets the activation step be a single PR.

## Activation Plan (if/when this repo gains a real job)

The expected shape, mirrored on `hoopR-nba-raw` and `wehoop-wbb-raw`:

1. Move the per-game JSON tree (`nba_stats/json/pbp/{season}/{game_id}.json`)
   from `hoopR-nba-stats-data` to a `nba_stats/` tree here. Downstream readers
   would shift from `raw.githubusercontent.com/sportsdataverse/hoopR-nba-stats-data/main/nba_stats/json/...`
   to `raw.githubusercontent.com/sportsdataverse/hoopR-nba-stats-raw/main/nba_stats/json/...`.
2. Split the scrape into `R/` (or `python/`) here and the
   compile/publish step into `hoopR-nba-stats-data`.
3. Add `.github/workflows/hoopR_nba_stats_data_trigger.yml` to fire
   `repository_dispatch` (event-type `daily_nba_stats_data`) at
   `hoopR-nba-stats-data` on every push to `main`.
4. Update `R/utils.R` proxy helpers to live alongside the scrape side
   (`get_proxy_ips()`, `select_proxy()` are currently in the `-data` repo).

Until step 1 ships, treat this repo as an empty namespace placeholder —
PRs that add scrapers here should be coordinated with the corresponding
deletion from `hoopR-nba-stats-data`.

## Key Conventions (when code lands here)

- **R 4.0.0+** to match `hoopR-nba-stats-data` and `hoopR`.
- **Season encoding**: NBA seasons are indexed by **start year** on disk
  (`nba_stats_schedule_2024.parquet` = 2024-25 season). The CLI flags
  `-s`/`-e` are *start year inclusive*; the scrapers internally shift via
  `years_vec <- (start - 1):(end - 1)` to align with NBA Stats' season-end
  parameter format. Preserve that asymmetry when porting code from
  `hoopR-nba-stats-data`.
- **JSON-on-disk is load-bearing**: any move of `nba_stats/json/pbp/...`
  has to be coordinated with `hoopR` loaders (`load_nba_pbp()` and family)
  and with the daily `NBA Stats Update (Start: YYYY End: YYYY)` commit
  format that downstream tooling parses.
- **Proxy support**: NBA Stats rate-limits aggressively. Production scrapes
  must go through the rotating proxy pool wired in via GitHub Actions secrets
  (`PROXY_KEY`, `PROXY_PKG`, `PROXY_ENDPOINT`). Local dry-runs without the
  secrets fall back to direct calls and will 429 eventually.
- **No secrets in tree**. Proxy IPs/credentials never get committed.

## Cross-Repo References

- Active sibling (NBA Stats scrape + cache): <https://github.com/sportsdataverse/hoopR-nba-stats-data>
- Downstream R package: <https://github.com/sportsdataverse/hoopR>
- ESPN NBA raw cache (the shape this repo would mirror): <https://github.com/sportsdataverse/hoopR-nba-raw>
- ESPN NBA parser sibling: <https://github.com/sportsdataverse/hoopR-nba-data>
- Release tags: <https://github.com/sportsdataverse/sportsdataverse-data/releases>

## Project-Specific Gotchas

- This is **not** the NBA Stats scrape entry point today. Anyone wiring up
  CI or cron should target `hoopR-nba-stats-data` instead.
- Do not confuse with `hoopR-nba-raw` — that's the ESPN cache and is
  actively maintained.
- Do not confuse with `wehoop-wnba-stats-raw` — also a placeholder, also
  paired with an active `*-stats-data` sibling.
- If/when the raw split happens, the canonical daily-scrape commit subject
  must be preserved: `NBA Stats Update (Start: YYYY End: YYYY)`. Downstream
  daily-update tooling parses the years out of the subject line (see SDV
  `scraper_commit_format_loadbearing` memory note).
- NBA Stats schema drift (column renames, dropped fields) should be handled
  in the `hoopR` SDK's parsing helpers, not in scrapers that land here.

## Commit Convention

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(scrape): add nba_stats_03_scrape_boxscoresummaryv2.R
fix(scrape): retry HTTP 429s in nba_stats_02_scrape_pbp with proxy rotation
chore(docs): expand CLAUDE.md with activation plan
ci: add hoopR_nba_stats_data_trigger.yml on push to main
```

When/if the raw split lands and this repo starts emitting daily scrape
commits, keep the load-bearing subject verbatim:

```
NBA Stats Update (Start: 2025 End: 2025)
```

Use `type!:` or a `BREAKING CHANGE:` footer for breaking changes. Split
unrelated work into separate commits for reviewability.

**Important: Never include AI agents or assistants (e.g., Claude, Copilot, Cursor, GPT, Gemini) as co-authors on commits.** Omit all `Co-Authored-By` trailers referencing AI tools. This applies whether the change was generated, refactored, or reviewed with AI assistance — the human author is the sole attributable contributor.
