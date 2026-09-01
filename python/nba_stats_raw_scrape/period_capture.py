"""NBA binding for the shared per-period window math.

The arithmetic lives in :mod:`sportsdataverse.scrape.stats.periods` (sdv-py
#327), which is league- and era-parameterized. This module binds the NBA league
id so callers keep the one-league signatures: ``period_start_range(period,
season)`` and ``season_of(game_id)``.
"""

from functools import partial

from sportsdataverse.scrape.stats.periods import (  # noqa: F401
    MAX_PERIODS,
    OT_PERIOD_SECONDS,
    QUARTER_BOX_RANGE_TYPE,
    WINDOW_WIDTH_TENTHS,
    periods_in_game,
)
from sportsdataverse.scrape.stats.periods import period_elapsed_seconds as _period_elapsed_seconds
from sportsdataverse.scrape.stats.periods import period_start_range as _period_start_range
from sportsdataverse.scrape.stats.periods import regulation_shape as _regulation_shape
from sportsdataverse.scrape.stats.periods import season_of as _season_of

#: This repo's league. The engine keys every era rule off it.
LEAGUE_ID = "00"

period_start_range = partial(_period_start_range, league_id=LEAGUE_ID)
period_elapsed_seconds = partial(_period_elapsed_seconds, league_id=LEAGUE_ID)
regulation_shape = partial(_regulation_shape, league_id=LEAGUE_ID)
season_of = partial(_season_of, league_id=LEAGUE_ID)
