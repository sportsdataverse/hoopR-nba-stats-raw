"""Season-level captures — re-exported from the shared engine.

Logic lives in :mod:`sportsdataverse.scrape.stats.season_capture` (sdv-py
#327); this module is the import seam for this repo's drivers and tests.
"""

from sportsdataverse.scrape.stats.season_capture import (  # noqa: F401
    _ids_from,
    _result_tables,
    capture_season,
    game_ids_from_gamelog,
    is_contentless,
    payload_path,
    plan_season,
    slug,
    write_payload,
)
