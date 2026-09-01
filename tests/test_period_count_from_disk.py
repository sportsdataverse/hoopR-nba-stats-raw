"""Stage 03 reads its period count from the persisted play-by-play.

In the monolith the per-game and per-period captures shared one pass, so the
period count came from the ``playbyplayv3`` payload still in memory. Split into
its own stage, 03 reads that payload back off disk instead.

Same number, same source — but the read is now the seam between two stages, so
it gets its own test. The failure this guards against is silent: a stage that
reads 0 periods for every game captures nothing and still exits 0.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "python"))

from nba_stats_raw_scrape.period_capture import periods_in_game  # noqa: E402


def _some_pbp_on_disk(limit: int = 3) -> list[Path]:
    """A few real playbyplayv3 payloads from the committed store, if present."""
    root = REPO / "nba_stats" / "json" / "playbyplayv3"
    if not root.is_dir():
        return []
    out: list[Path] = []
    for season_dir in sorted(root.iterdir(), reverse=True):
        if not season_dir.is_dir():
            continue
        for f in sorted(season_dir.glob("*.json")):
            out.append(f)
            if len(out) >= limit:
                return out
    return out


def test_regulation_game_reports_at_least_four_periods() -> None:
    """The count must come out of the payload, not a constant.

    A regulation basketball game has 4 periods and an OT game more; anything
    reporting fewer means the reader is not seeing the payload's period field,
    which would make stage 03 skip every game as 'unknown'.
    """
    files = _some_pbp_on_disk()
    if not files:
        pytest.skip("no playbyplayv3 payloads in the committed store")

    counts = []
    for f in files:
        payload = json.loads(f.read_text(encoding="utf-8"))
        counts.append(periods_in_game(payload))

    assert all(c >= 4 for c in counts), f"period counts {counts} from {[f.name for f in files]}"


def test_a_missing_or_unparseable_payload_reports_zero_not_a_default() -> None:
    """0 means 'unknown', and stage 03 SKIPS on 0 rather than guessing.

    Returning a default of 4 here would silently truncate every overtime game
    it was applied to, which is exactly why the count is derived and not fixed.
    """
    assert periods_in_game(None) == 0
    assert periods_in_game({}) == 0
