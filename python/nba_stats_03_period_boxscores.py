#!/usr/bin/env python
"""Stage 03 — per-period boxscores for stats.nba.com.

One payload per game keyed by period (``boxscoretraditionalv3_period``) -- the
shape the ``-data`` repos already consume. A file per period would mean 4-6x
the objects for no gain, and every reader would have to reassemble them.

**The period count is read from the game's persisted ``playbyplayv3``**, so
overtime is discovered without a request and a fixed count cannot truncate an
OT game. In the monolith this payload was still in memory from the per-game
pass; as a separate stage it is read back off disk instead. Same number, same
source, one extra read -- and in exchange this stage no longer has to run in
the same process as stage 02, or at all.

A game with no pbp on disk is SKIPPED, not failed: its period count is
unknowable, and stage 02 is the thing that owes it a playbyplayv3.

    python python/nba_stats_03_period_boxscores.py 2026
    python python/nba_stats_03_period_boxscores.py --game-ids=ids.txt
    python python/nba_stats_03_period_boxscores.py --check 2026
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nba_stats_raw_scrape._capture_runtime import (  # noqa: E402
    PERIOD_ENDPOINT,
    STATS_PREFIX,
    WORKERS,
    Progress,
    _log,
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
    stats, _game_endpoints, _season = load_stats_module()
    from nba_stats_raw_scrape.period_capture import (  # noqa: E402
        QUARTER_BOX_RANGE_TYPE,
        period_start_range,
        periods_in_game,
        season_of,
    )
    from sportsdataverse.nba.nba_possessions import (  # noqa: E402
        _raw_store_path,
        _through_raw_store,
    )

    _log(f"stage 03 store: {store}")
    _log(f"{len(seasons)} seasons | endpoint={PERIOD_ENDPOINT} | workers={WORKERS}")

    transport, health, pool = open_transport()
    if not pool:
        return no_proxy_error()
    _log(f"proxy pool: {len(pool)} entries")
    if check_only:
        _log("--check: stage sized and proxy pool verified; fetching nothing")
        return 0

    def _period_count(gid: str) -> int:
        """Periods for this game, from its persisted play-by-play. 0 = unknown."""
        p = _raw_store_path("playbyplayv3", gid, root=store)
        if p is None or not p.exists():
            return 0
        try:
            return periods_in_game(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return 0

    def _one(gid: str) -> tuple[int, int]:
        n = _period_count(gid)
        if not n:
            return 0, 0  # no pbp yet -> stage 02 owes it one; not a failure here

        def _all_periods(g: str = gid, k: int = n) -> dict:
            """Every period for one game as a {period: payload} mapping.

            Written through the store as a SINGLE object, so a partially-fetched
            game leaves nothing behind: any period failing aborts the whole game
            rather than persisting a half-captured mapping that later looks
            complete to the presence check.
            """
            season = season_of(g)
            out: dict[str, object] = {}
            for period in range(1, k + 1):
                start_range, end_range = period_start_range(period, season)
                out[str(period)] = getattr(stats, f"{STATS_PREFIX}_boxscoretraditionalv3")(
                    game_id=g,
                    start_period=period,
                    end_period=period,
                    range_type=QUARTER_BOX_RANGE_TYPE,
                    start_range=start_range,
                    end_range=end_range,
                    return_parsed=False,
                    transport=transport,
                )
            return out

        try:
            _through_raw_store(PERIOD_ENDPOINT, gid, _all_periods, store_dir=store, readonly=False)
            return 1, 0
        except Exception:  # noqa: BLE001 - a period gap must not kill the stage
            return 0, 1

    def _incomplete(gid: str) -> bool:
        p = _raw_store_path(PERIOD_ENDPOINT, gid, root=store)
        return p is not None and not p.exists()

    progress = Progress()
    _hb, stop_hb = start_heartbeat(progress, health, len(pool))

    grand_fetched = grand_failed = grand_nopbp = 0
    for season in seasons:
        gids = set(targeted[season]) if targeted else game_ids_for_season(store, season)
        todo = [g for g in sorted(gids) if _incomplete(g)]
        _log(f"season {season}: {len(gids)} games indexed, {len(todo)} without periods")
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
        # Games still without periods and without a fetch or a failure had no
        # pbp to size them -- reported separately so "skipped" is never read as
        # "captured".
        nopbp = len(todo) - fetched - failed
        grand_fetched += fetched
        grand_failed += failed
        grand_nopbp += nopbp
        _log(
            f"season {season}: done | {fetched} games captured | {failed} misses"
            f" | {nopbp} skipped (no playbyplayv3 on disk yet)"
        )

    stop_hb.set()
    summarize_health(health)
    _log(
        f"stage 03 complete: {grand_fetched} games captured, {grand_failed} misses,"
        f" {grand_nopbp} skipped for missing pbp"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
