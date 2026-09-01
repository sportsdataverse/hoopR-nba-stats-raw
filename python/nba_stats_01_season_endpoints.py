#!/usr/bin/env python
"""Stage 01 — season-level payloads for stats.nba.com.

Captures every season-scoped endpoint for the given seasons, one payload per
``{endpoint}/{season}/{variant}.json`` (or flat ``{endpoint}/{season}.json``).

This stage is FIRST because it persists ``leaguegamelog``, which is the game
universe stages 02 and 03 read back off disk. It is cheap next to the per-game
passes -- a few hundred calls per season against thousands -- so re-running it
alone to refresh a season index costs very little.

Independent and resumable: payloads already on disk are skipped, and the write
guard refuses to persist an empty ``{}`` (presence is the resume key, so an
empty payload would block its own refetch forever -- see stage 20).

    python python/nba_stats_01_season_endpoints.py 2026
    python python/nba_stats_01_season_endpoints.py 1996:2026
    python python/nba_stats_01_season_endpoints.py --check 2026   # size it, fetch nothing
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nba_stats_raw_scrape._capture_runtime import (  # noqa: E402
    ENDPOINT_MIN_SEASON,
    LEAGUE_ID,
    STATS_PREFIX,
    _log,
    _skip_endpoint,
    load_stats_module,
    no_proxy_error,
    open_transport,
    parse_common,
    resolve_store,
    summarize_health,
)


def main(argv: list[str]) -> int:
    parsed = parse_common(argv, __doc__)
    if parsed is None:
        return 2
    seasons, targeted, check_only = parsed
    if targeted:
        _log(
            "stage 01: --game-ids names individual games; the season-level pass has no per-game scope"
        )
        return 0

    store = resolve_store()
    stats, _game_endpoints, _season_endpoints = load_stats_module()
    from nba_stats_raw_scrape.endpoints import plan_counts  # noqa: E402
    from nba_stats_raw_scrape.season_capture import capture_season  # noqa: E402

    counts = plan_counts(stats, STATS_PREFIX, LEAGUE_ID)
    _log(f"stage 01 store: {store}")
    _log(
        f"{len(seasons)} seasons | {counts['season_endpoints']} season endpoints"
        f" ({counts['season_calls_per_season']} calls/season)"
    )

    transport, health, pool = open_transport()
    if not pool:
        return no_proxy_error()
    _log(f"proxy pool: {len(pool)} entries")
    if check_only:
        _log("--check: stage sized and proxy pool verified; fetching nothing")
        return 0

    def _season_fetch(endpoint: str, kwargs: dict) -> object:
        fn = getattr(stats, f"{STATS_PREFIX}_{endpoint}")
        return fn(return_parsed=False, transport=transport, **kwargs)

    written = skipped = failed = 0
    for season in seasons:
        skip_eps = {e for e in ENDPOINT_MIN_SEASON if _skip_endpoint(e, season)}
        w, s, f = capture_season(
            season,
            store,
            _season_fetch,
            stats,
            STATS_PREFIX,
            LEAGUE_ID,
            _log,
            skip_endpoints=skip_eps,
        )
        _log(f"season {season}: season-level | {w} written | {s} present | {f} failed")
        written += w
        skipped += s
        failed += f

    summarize_health(health)
    _log(f"stage 01 complete: {written} written, {skipped} already present, {failed} failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
