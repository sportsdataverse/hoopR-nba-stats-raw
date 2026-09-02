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

Two flags narrow a run to a single family's backfill:

    --endpoints=a,b   capture ONLY these season endpoints (floors still apply)
    --no-proxy        go direct instead of through the rotating pool

``--no-proxy`` is opt-in and never the default. The pool exists because the
per-game sweep is thousands of calls per season and gets rate-limited; a
season-endpoint backfill is tens of calls and does not. Measured 2026-09-02
from a residential IP: leaguehustlestatsplayer 2024-25 direct through curl_cffi
answered HTTP 200 in 2.91 s with no throttle, and the full 88-call hustle
backfill ran with zero faults. Do NOT reach for it on stages 02/03, and do not
use it from a datacenter IP -- there the un-proxied call HANGS rather than
failing, which is the behaviour the pool requirement was written against.

    python python/nba_stats_01_season_endpoints.py --no-proxy \
        --endpoints=leaguehustlestatsplayer,leaguehustlestatsteam 2015:2025
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


def _only_endpoints(argv: list[str]) -> set[str] | None:
    """``--endpoints=a,b`` -> ``{"a", "b"}``; ``None`` when the flag is absent.

    An EMPTY value (``--endpoints=``) returns an empty set, not ``None``: "capture
    nothing" is a legitimate no-op, while silently widening it back to the full
    sweep would be the opposite of what was asked.
    """
    raw = next((a.split("=", 1)[1] for a in argv if a.startswith("--endpoints=")), None)
    if raw is None:
        return None
    return {e.strip() for e in raw.split(",") if e.strip()}


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

    only = _only_endpoints(argv)
    store = resolve_store()
    stats, _game_endpoints, season_endpoints = load_stats_module()
    if only is not None:
        unknown = sorted(only - set(season_endpoints))
        if unknown:
            _log(f"stage 01: --endpoints names no season endpoint: {', '.join(unknown)}")
            return 2
    from nba_stats_raw_scrape.endpoints import plan_counts  # noqa: E402
    from nba_stats_raw_scrape.season_capture import capture_season  # noqa: E402

    counts = plan_counts(stats, STATS_PREFIX, LEAGUE_ID)
    _log(f"stage 01 store: {store}")
    _log(
        f"{len(seasons)} seasons | {counts['season_endpoints']} season endpoints"
        f" ({counts['season_calls_per_season']} calls/season)"
    )

    direct = "--no-proxy" in argv
    if direct:
        transport, health, pool = None, None, []
        _log("proxy pool: BYPASSED (--no-proxy) -- calls go direct from this IP")
    else:
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
        if only is not None:
            # The allowlist NARROWS; it never un-parks. An endpoint below its
            # floor stays skipped even when named, so a typo'd backfill cannot
            # quietly resume hammering a parked endpoint.
            skip_eps |= set(season_endpoints) - only
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

    if health is not None:  # --no-proxy has no pool to report on
        summarize_health(health)
    _log(f"stage 01 complete: {written} written, {skipped} already present, {failed} failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
