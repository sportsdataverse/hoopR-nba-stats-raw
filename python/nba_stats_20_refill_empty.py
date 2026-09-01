"""Refill the season-level payloads that were persisted as empty ``{}``.

The repair logic (census, delete-only-with-a-replacement-in-hand, atomic
rewrite) lives in :mod:`sportsdataverse.scrape.stats.refill` (sdv-py #327);
this is the NBA binding and entry point. See that module for the incident
background and the safety contract.

Usage
-----
    python python/nba_stats_20_refill_empty.py --check          # census only, no network
    python python/nba_stats_20_refill_empty.py                  # refill everything
    python python/nba_stats_20_refill_empty.py 2015:2026        # season range
    python python/nba_stats_20_refill_empty.py --endpoint matchupsrollup
"""

import sys

from nba_stats_raw_scrape._capture_runtime import REPO, STORE_SUBDIR
from sportsdataverse.scrape.stats.league_config import NBA
from sportsdataverse.scrape.stats.refill import main

if __name__ == "__main__":
    sys.exit(main(NBA, default_root=REPO.joinpath(*STORE_SUBDIR)))
