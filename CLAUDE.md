# CLAUDE.md — hoopR-nba-stats-raw

Placeholder "raw" slot in the SportsDataverse **hoopR** NBA Stats pipeline — the intended
home for a raw cache of NBA Stats API (`stats.nba.com`) per-game JSON, mirroring the
ESPN-side `hoopR-nba-raw` / `hoopR-nba-data` split. **Not active today**: scrapers,
schedules, per-game JSON, and the proxy/rate-limit helpers all live in the sibling
**`hoopR-nba-stats-data`** repo, which both scrapes stats.nba.com and commits the cache.
Downstream consumers read from `hoopR-nba-stats-data` directly until/unless this repo is
activated. Contact: Saiem Gilani <saiem.gilani@gmail.com>. License MIT.

## Current contents (verified)

Governance + project shell only — no `R/`, no `scripts/`, no `DESCRIPTION`, no
`requirements.txt`, no `.github/workflows/`:

```
README.md                  # one-line stub
.gitignore  .Rproj         # RStudio project shell
.github/                   # ISSUE_TEMPLATE/ + pull_request_template.md + copilot-instructions.md
CLAUDE.md  CONTRIBUTING.md  CODE_OF_CONDUCT.md
LICENSE  LICENSE.md        # MIT
```

There are no commands to run here. Operational scrape commands live in
`hoopR-nba-stats-data` (`bash scripts/daily_nba_stats_scraper.sh -s YYYY -e YYYY -r <bool>`).

## Conventions (for if/when code lands)

- Mirror `hoopR-nba-stats-data`: R >= 4.0.0, one-file-per-task optparse R scripts, magrittr
  `%>%`, snake_case, 2-space indent. Raw repos commit raw JSON to git (the intentional SDV
  pattern) — don't warn about repo bloat.
- **Season = start year** on disk; scrapers shift internally `(start-1):(end-1)` to hit NBA
  Stats' season-end param. Preserve that asymmetry when porting.
- Daily scrape commit subject must stay verbatim `NBA Stats Update (Start: YYYY End: YYYY)`
  — downstream tooling parses years from it (`scraper_commit_format_loadbearing`).
- Code/infra commits: Conventional Commits (`feat(scrape):`, `ci:`). Never add AI co-author
  trailers to commits.

## Gotchas — NBA Stats API + activation

- **This is not the scrape entry point today** — wire CI/cron against `hoopR-nba-stats-data`.
- NBA Stats requests are issued by hoopR (`hoopR::nba_pbp()` / `nba_schedule()`), which own
  the UA/referer/headers; the data repo adds the rotating proxy + a trailing-window
  `rate_limit()` token bucket (`STATS_RATE_MAX/WINDOW/HITS`, sequential-only, no `furrr`).
  Any scraper added here must reuse that proxy/rate-limit discipline. Never commit proxy
  IPs/credentials (`PROXY_KEY`/`PROXY_PKG`/`PROXY_ENDPOINT` are GitHub secrets only).
- NBA Stats schema drift is fixed in the **hoopR SDK**, not in scrapers landed here.
- Don't confuse with `hoopR-nba-raw` (ESPN cache, actively maintained) or
  `wehoop-wnba-stats-raw` (the women's-pro placeholder analog).
- Activation, if it happens (mirror `hoopR-nba-raw` / `wehoop-wbb-raw`): move
  `nba_stats/json/pbp/{game_id}.json` here, split scrape vs compile/publish, add a
  `repository_dispatch` trigger workflow against `hoopR-nba-stats-data`, and bring the
  proxy/rate-limit helpers along. Coordinate every add here with the matching delete in
  `hoopR-nba-stats-data`.

## Cross-repo

- Active sibling: <https://github.com/sportsdataverse/hoopR-nba-stats-data>
- Downstream R package: <https://github.com/sportsdataverse/hoopR>
- ESPN siblings: <https://github.com/sportsdataverse/hoopR-nba-raw> · <https://github.com/sportsdataverse/hoopR-nba-data>
- Release tags: <https://github.com/sportsdataverse/sportsdataverse-data/releases>
