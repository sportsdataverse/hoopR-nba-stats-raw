"""League-agnostic capture registry — re-exported from the shared engine.

The registry itself lives in :mod:`sportsdataverse.scrape.stats.endpoints`
(sdv-py #327). This module is the import seam so drivers and tests in this repo
keep importing ``endpoints`` unchanged; there is no logic here.
"""

from sportsdataverse.scrape.stats.endpoints import (  # noqa: F401
    DEFENSE_CATEGORIES,
    ENDPOINT_MEASURE_TYPES,
    EXCLUDED_SEASON_ENDPOINTS,
    LEAGUE_NBA,
    LEAGUE_WNBA,
    LINEUP_GROUP_QUANTITY,
    MEASURE_TYPE_DOMAINS,
    MEASURE_TYPES,
    PER_MODES,
    PLAY_TYPES,
    PT_MEASURE_TYPES,
    SEASON_TYPES,
    TYPE_GROUPINGS,
    discover,
    measure_types_for,
    plan_counts,
    season_string,
    season_variants,
    slug,
)
