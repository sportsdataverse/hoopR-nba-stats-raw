"""Stage 99 — schedule master + coverage index (runs LAST in the daily scrape).

Thin entry point over ``python/schedule_master.py``: builds the game universe
from the ``leaguegamelog`` payloads, walks the raw tree once for the
``has_<endpoint>`` capture flags + ``playbyplayv3`` scrape state, and writes

* ``nba_stats/nba_stats_schedule_master.parquet``  — one row per game (D36).
* ``nba_stats/nba_stats_schedule_coverage.parquet`` — one row per
  (season, season_type) with capture rates.
* ``nba_stats/nba_stats_endpoint_coverage.parquet`` — one row per
  (endpoint, season dir) for every endpoint, including the variant/aggregate
  endpoints that have no game key and therefore no ``has_*`` flag.

Example:
    Rebuild everything from the committed tree::

        .venv/bin/python python/nba_stats_99_schedule_master_creation.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

from schedule_master import (
    build_coverage,
    build_master,
    load_universe,
    reconcile,
    walk_raw_tree,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
LEAGUE = "nba_stats"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(REPO_ROOT / LEAGUE / "json"))
    parser.add_argument("--out", default=str(REPO_ROOT / LEAGUE))
    args = parser.parse_args(argv)

    root, out = Path(args.root), Path(args.out)
    universe = load_universe(root)
    if universe.is_empty():
        print(f"::error ::no leaguegamelog payloads under {root}")
        return 1

    endpoint_gids, primary_stats, endpoint_index = walk_raw_tree(root)
    master = build_master(universe, endpoint_gids, primary_stats)
    coverage = build_coverage(master)

    master.write_parquet(out / f"{LEAGUE}_schedule_master.parquet")
    coverage.write_parquet(out / f"{LEAGUE}_schedule_coverage.parquet")
    endpoint_index.write_parquet(out / f"{LEAGUE}_endpoint_coverage.parquet")

    print(f"master:   {master.height} games (schedule source: leaguegamelog)")
    print(f"coverage: {coverage.height} (season, season_type) rows")
    print(
        f"endpoint index: {endpoint_index.height} rows across {len(endpoint_gids)} game-keyed endpoints"
    )
    for flag in sorted(c for c in master.columns if c.startswith("has_")):
        print(f"  {flag}: {master[flag].sum()}")
    report = reconcile(universe, endpoint_gids)
    orphans = report.filter(report["n_orphans"] > 0)
    if orphans.height:
        # Report-only: files for games the schedule does not know mean the
        # leaguegamelog capture is behind the tree, not that this step failed.
        print("::warning ::game files not in the schedule universe:")
        for row in orphans.to_dicts():
            print(f"  {row['endpoint']}: {row['n_orphans']} orphan file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
