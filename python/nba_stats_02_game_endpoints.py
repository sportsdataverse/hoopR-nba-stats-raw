#!/usr/bin/env python
"""Stage 02 — per-game whole-game payloads for stats.nba.com.

One payload per game per endpoint, through sdv-py's read-through raw store
(``{endpoint}/{season}/{game_id}.json``, atomic tmp+rename).

The game universe is READ from the ``leaguegamelog`` payloads stage 01
persisted -- this stage never re-fetches the index. That is what makes it
independently runnable: stage 01 can be days old, or run for a different
season range, and this stage still resumes correctly from what is on disk.

Per-endpoint season floors (``ENDPOINT_MIN_SEASON`` / ``_skip_endpoint``) are
applied per game, so an endpoint below its tracking-era floor is not "missing"
for an old game -- it is out of scope, and the game still counts as complete.

    python python/nba_stats_02_game_endpoints.py 2026
    python python/nba_stats_02_game_endpoints.py 1996:2026
    python python/nba_stats_02_game_endpoints.py --game-ids=ids.txt
    python python/nba_stats_02_game_endpoints.py --check 2026
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _capture_runtime import (  # noqa: E402
    STATS_PREFIX,
    WORKERS,
    Progress,
    _log,
    _skip_endpoint,
    game_ids_for_season,
    load_stats_module,
    no_proxy_error,
    open_transport,
    parse_common,
    resolve_store,
    start_heartbeat,
    summarize_health,
)


def main(argv: list[str]) -> int:
    parsed = parse_common(argv, __doc__)
    if parsed is None:
        return 2
    seasons, targeted, check_only = parsed

    store = resolve_store()
    stats, game_endpoints, _season = load_stats_module()
    from period_capture import season_of  # noqa: E402
    from sportsdataverse.nba.nba_possessions import (  # noqa: E402
        _raw_store_path,
        _through_raw_store,
    )

    _log(f"stage 02 store: {store}")
    if targeted:
        # Named-id mode gets its own summary: the season count comes from the
        # ids themselves, so "2 seasons" here means two seasons of ids, not a
        # requested range. Dropping this line hid which ids a repair run took.
        _log(
            f"targeted mode: {sum(len(v) for v in targeted.values())} game ids"
            f" over {len(seasons)} seasons ({seasons[0]}..{seasons[-1]})"
            f" | {len(game_endpoints)} game endpoints | workers={WORKERS}"
        )
    else:
        _log(f"{len(seasons)} seasons | {len(game_endpoints)} game endpoints | workers={WORKERS}")

    transport, health, pool = open_transport()
    if not pool:
        return no_proxy_error()
    _log(f"proxy pool: {len(pool)} entries")
    if check_only:
        _log("--check: stage sized and proxy pool verified; fetching nothing")
        return 0

    def _endpoints_for(gid: str) -> list:
        """Endpoints in scope for this game's season -- an endpoint below its
        tracking-era floor (gamerotation 500s pre-2016) is out of scope, not
        missing."""
        yr = season_of(gid)
        return [e for e in game_endpoints if not _skip_endpoint(e, yr)]

    def _one(gid: str) -> tuple[int, int]:
        fetched = failed = 0
        for ep in _endpoints_for(gid):
            path = _raw_store_path(ep, gid, root=store)
            if path is not None and path.exists():
                continue
            try:
                _through_raw_store(
                    ep,
                    gid,
                    lambda e=ep, g=gid: getattr(stats, f"{STATS_PREFIX}_{e}")(
                        game_id=g, return_parsed=False, transport=transport
                    ),
                    store_dir=store,
                    readonly=False,
                )
                fetched += 1
            except Exception:  # noqa: BLE001 - a game-local failure must not kill the stage
                failed += 1
        return fetched, failed

    def _incomplete(gid: str) -> bool:
        return any(
            (p := _raw_store_path(ep, gid, root=store)) is not None and not p.exists()
            for ep in _endpoints_for(gid)
        )

    progress = Progress()
    _hb, stop_hb = start_heartbeat(progress, health, len(pool))

    grand_fetched = grand_failed = 0
    for season in seasons:
        gids = set(targeted[season]) if targeted else game_ids_for_season(store, season)
        todo = [g for g in sorted(gids) if _incomplete(g)]
        _log(f"season {season}: {len(gids)} games indexed, {len(todo)} incomplete")
        progress.begin_season(season, len(todo))
        if not todo:
            continue
        fetched = failed = 0
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for fut in as_completed(ex.submit(_one, g) for g in todo):
                f, x = fut.result()
                fetched += f
                failed += x
                progress.tick()
        grand_fetched += fetched
        grand_failed += failed
        snap = health.snapshot()
        c = snap["cat"]
        _log(
            f"season {season}: done | {fetched} payloads fetched | {failed} misses"
            f" | http[ok={c['ok']} blank={c['blank']} 404={c['notfound']}"
            f" blocked={c['blocked']} 5xx={c['server_err']} timeout/err={c['transport_err']}]"
            f" | proxies {snap['quar']} quarantined of {len(pool)}"
        )

    stop_hb.set()
    summarize_health(health)
    _log(
        f"stage 02 complete: {grand_fetched} payloads persisted, {grand_failed} misses"
        " (endpoint gaps are expected in early seasons)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
