"""Tests for the per-endpoint season floor (`_skip_endpoint`).

This file was dead for several months: `_skip_endpoint` was refactored into two
inlined comprehensions (4ec4c143a4) and the import here broke, but the repo had
no pyproject and no CI, and the file sat in `scripts/` where nothing collected
it -- so nothing ever reported the failure. Both problems are fixed: the helper
is a named module-level function again, and pytest collects `tests/`.

`pythonpath = ["python"]` in pyproject puts the scraper modules on sys.path;
there is deliberately no sys.path hack here.
"""

from __future__ import annotations

from scrape_raw_json import ENDPOINT_MIN_SEASON, _skip_endpoint

# Real NBA seasons the scraper sweeps (start-year encoding).
REAL_SEASONS = (1996, 2005, 2015, 2016, 2020, 2026)


def test_endpoints_without_a_floor_are_never_skipped() -> None:
    """The `.get(endpoint, 0)` default: absent from the table == no floor.

    These two carry data for every season back to 1996, so a regression that
    gave them a floor would silently truncate the archive.
    """
    for season in REAL_SEASONS:
        assert not _skip_endpoint("playbyplayv3", season)
        assert not _skip_endpoint("boxscoretraditionalv3", season)


def test_floor_is_inclusive_at_the_boundary() -> None:
    """Season == floor must be KEPT, not skipped.

    The off-by-one here is the whole risk: boxscorematchupsv3 probes empty
    through 2016-17 and populates from 2017-18, so 2017 is real data. An
    exclusive comparison would drop a full season of matchup box scores.
    """
    floor = ENDPOINT_MIN_SEASON["boxscorematchupsv3"]
    assert floor == 2017
    assert _skip_endpoint("boxscorematchupsv3", floor - 1)
    assert not _skip_endpoint("boxscorematchupsv3", floor)
    assert not _skip_endpoint("boxscorematchupsv3", floor + 1)


def test_gamerotation_is_parked_for_every_real_season() -> None:
    """gamerotation's floor is set ABOVE any real season to park it entirely.

    It holds real data from 2015-16 but times out under the main sweep's
    concurrency, so it is captured by a dedicated low-concurrency pass that
    overrides GAMEROTATION_MIN_SEASON. If a future edit drops the sentinel back
    to 2016, the main sweep silently gets slow again -- this test is the alarm.
    """
    assert ENDPOINT_MIN_SEASON["gamerotation"] > max(REAL_SEASONS)
    for season in REAL_SEASONS:
        assert _skip_endpoint("gamerotation", season)


def test_player_tracking_endpoints_share_the_sportvu_floor() -> None:
    """SportVU tracking begins 2013-14; all six PT endpoints share that floor."""
    pt_endpoints = (
        "leaguedashptstats",
        "leaguedashptdefend",
        "leaguedashplayerptshot",
        "leaguedashoppptshot",
        "leaguedashteamptshot",
        "leaguedashptteamdefend",
    )
    for endpoint in pt_endpoints:
        assert _skip_endpoint(endpoint, 2012)
        assert not _skip_endpoint(endpoint, 2013)
