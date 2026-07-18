#!/usr/bin/env python
"""Scrape stats.nba.com per-game raw JSON into this repo's nba_stats/json tree.

THIS repo owns filling the raw store. hoopR-nba-stats-data's compile jobs
read the tree as pure consumers (``SDV_PY_NBA_RAW_JSON_READONLY=1``) and
never write it — the raw-vs-data separation of concerns.

Game discovery comes from the stats.nba.com season game index; per-game
payloads go through sdv-py's store-routed fetchers (``playbyplayv3``,
``boxscoretraditionalv3``, ``gamerotation``) in read-write mode, so every
fetch persists ``nba_stats/json/{endpoint}/{season}/{game_id}.json`` (atomic
tmp+rename, season = start year decoded from the game id). Idempotent and
resumable: on-disk payloads are skipped without a parse; Ctrl-C and rerun.
``gamerotation`` misses are tolerated — the endpoint has no data for old
seasons. Fetch-only and I/O-bound: threads, not processes, and the worker
count is proxy courtesy, not RAM.

Seasons on the CLI are END years, matching ``compile_nba_season``
(``2024`` = 2023-24), single year or ``lo:hi`` range.

Run with the hoopR-nba-stats-data venv (carries sportsdataverse+curl_cffi;
this repo deliberately has no Python project of its own):

    /mnt/sdv_repos/hoopR-nba-stats-data/python/.venv/bin/python \\
      scripts/scrape_raw_json.py 1996:2025
"""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SEASON_TYPES = ("Regular Season", "Playoffs")
WORKERS = int(os.environ.get("SCRAPE_WORKERS", "6"))


def _log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%F %T')}Z] {msg}", flush=True)


def _parse_seasons(spec: str) -> list[int]:
    if ":" in spec:
        lo, hi = spec.split(":", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(spec)]


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    # Explicit store args (not env) so this writer is immune to ambient
    # config: raw_store_dir pins the tree to THIS checkout and
    # raw_store_readonly=False overrides any leaked READONLY env var.
    store = os.environ.get("SDV_PY_NBA_RAW_JSON_DIR") or str(REPO / "nba_stats" / "json")
    from proxy import RoundRobin, load_proxies
    from sportsdataverse.nba.nba_possessions import (
        _fetch_box,
        _fetch_pbp,
        _fetch_rotation,
        _raw_store_path,
    )
    from sportsdataverse.nba.nba_season_compile import _game_ids_for_season

    endpoints = (
        ("playbyplayv3", _fetch_pbp),
        ("boxscoretraditionalv3", _fetch_box),
        ("gamerotation", _fetch_rotation),
    )
    seasons = _parse_seasons(argv[0])
    rr = RoundRobin(load_proxies())
    _log(f"sweeping {len(seasons)} seasons x {len(SEASON_TYPES)} types, workers={WORKERS}")
    _log(f"store: {store}")

    def _one(gid: str) -> tuple[int, int]:
        fetched = failed = 0
        for ep, fetcher in endpoints:
            path = _raw_store_path(ep, gid, root=store)
            if path is not None and path.exists():
                continue
            try:
                fetcher(gid, proxy_url=rr.next(), raw_store_dir=store, raw_store_readonly=False)
                fetched += 1
            except Exception:  # noqa: BLE001 - a game-local failure must not kill the sweep
                failed += 1
        return fetched, failed

    grand_fetched = grand_failed = 0
    for season in seasons:
        gids: set[str] = set()
        for stype in SEASON_TYPES:
            try:
                gids.update(_game_ids_for_season(season, stype, proxy_url=rr.next()))
            except Exception as exc:  # noqa: BLE001 - index gap shouldn't kill the sweep
                _log(f"season {season} {stype}: game-index fetch failed: {exc}")
        todo = [
            g
            for g in sorted(gids)
            if any(not _raw_store_path(ep, g, root=store).exists() for ep, _ in endpoints)  # type: ignore[union-attr]
        ]
        _log(f"season {season}: {len(gids)} games indexed, {len(todo)} incomplete")
        if not todo:
            continue
        fetched = failed = 0
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for fut in as_completed(pool.submit(_one, g) for g in todo):
                f, x = fut.result()
                fetched += f
                failed += x
        grand_fetched += fetched
        grand_failed += failed
        _log(f"season {season}: done | {fetched} payloads fetched | {failed} endpoint misses")
    _log(
        f"sweep complete: {grand_fetched} payloads persisted, {grand_failed} endpoint misses (rotation gaps expected pre-~2015)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
