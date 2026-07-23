"""Tests for the per-endpoint season floor."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scrape_raw_json import ENDPOINT_MIN_SEASON, _skip_endpoint  # noqa: E402


def test_gamerotation_is_skipped_below_the_floor() -> None:
    assert _skip_endpoint("gamerotation", 2015)
    assert _skip_endpoint("gamerotation", 1997)


def test_gamerotation_runs_at_and_above_the_floor() -> None:
    floor = ENDPOINT_MIN_SEASON["gamerotation"]
    assert not _skip_endpoint("gamerotation", floor)
    assert not _skip_endpoint("gamerotation", floor + 5)


def test_other_endpoints_are_never_skipped() -> None:
    for season in (1997, 2015, 2026):
        assert not _skip_endpoint("playbyplayv3", season)
        assert not _skip_endpoint("boxscoretraditionalv3", season)
