"""Per-period boxscore window — NBA time math.

Same interface as wehoop-wnba-stats-raw's ``period_capture`` so the shared
``scrape_raw_json.py`` works unchanged in both repos, but the arithmetic here
delegates to sdv-py rather than restating it: ``nba_lineups._period_start_range``
is already NBA-correct (12-minute quarters, 5-minute overtime) and is the same
function ``_fetch_box_periods`` uses, so the capture window cannot drift from what
the possession engine expects when it reads these payloads back.

The WNBA repo cannot delegate the same way — it plays 10-minute quarters, and two
20-minute halves before 2006 — which is why that side carries its own arithmetic
and this one does not.
"""

from __future__ import annotations

from typing import Any

from sportsdataverse.nba.nba_lineups import (
    _QUARTER_BOX_RANGE_TYPE,
    _period_start_range,
)

#: ``RangeType=2`` selects an explicit Start/EndRange window (pbpstats convention).
QUARTER_BOX_RANGE_TYPE = _QUARTER_BOX_RANGE_TYPE

#: Guard against a malformed payload driving an unbounded fetch loop.
MAX_PERIODS = 12


def period_start_range(period: int, season: int) -> tuple[str, str]:
    """``(StartRange, EndRange)`` in tenths at ``period``'s opening tick.

    ``season`` is accepted for interface parity with the WNBA module and ignored:
    the NBA has used 12-minute quarters throughout the range this store covers.
    """
    return _period_start_range(period)


def periods_in_game(pbp_payload: Any) -> int:
    """Highest period number in a captured ``playbyplayv3`` payload (0 if unknown).

    Reading it off the stored play-by-play means overtime is discovered for free --
    a fixed four-period fetch would truncate every OT game, and probing for it would
    spend a request per game.
    """
    if not isinstance(pbp_payload, dict):
        return 0
    actions = (pbp_payload.get("game") or {}).get("actions") or []
    periods = [a.get("period") for a in actions if isinstance(a, dict)]
    valid = [
        int(p) for p in periods if isinstance(p, (int, float, str)) and str(p).isdigit()
    ]
    return min(max(valid), MAX_PERIODS) if valid else 0


def season_of(game_id: str) -> int:
    """Season **end** year encoded in a 10-digit NBA game id.

    ``0020500469`` -> 2006: digits 3-4 are the season's *start* year and an NBA
    season spans two calendar years, so the store's directory is start + 1. (The
    WNBA plays inside one calendar year, so its equivalent adds nothing -- the two
    leagues genuinely differ here.)
    """
    gid = str(game_id).zfill(10)
    yy = int(gid[3:5])
    start = 1900 + yy if yy >= 90 else 2000 + yy
    return start + 1
