"""Schedule master: universe, capture flags, scrape state, coverage roll-up.

Offline, fixture-backed: builds a miniature raw tree in ``tmp_path`` and
asserts the master's schema equals the universe (yearly) schema plus the
documented extras — ``has_<endpoint>`` per game-keyed endpoint and the four
scrape-state columns.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
from nba_stats_raw_scrape.schedule_master import (
    _UNIVERSE_SCHEMA,
    SCRAPE_STATE_COLUMNS,
    build_coverage,
    build_master,
    load_universe,
    reconcile,
    walk_raw_tree,
)

GID_REG_1 = "0022300001"
GID_REG_2 = "0022300002"
GID_PLAYOFF = "0042300101"
GID_ORPHAN = "0022399999"  # in the tree, not in the schedule universe


def _lgl_payload(rows: list[list]) -> str:
    return json.dumps(
        {
            "resource": "leaguegamelog",
            "resultSets": [
                {
                    "name": "LeagueGameLog",
                    "headers": [
                        "SEASON_ID",
                        "TEAM_ID",
                        "TEAM_ABBREVIATION",
                        "GAME_ID",
                        "GAME_DATE",
                        "MATCHUP",
                    ],
                    "rowSet": rows,
                }
            ],
        }
    )


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "json"
    lgl = root / "leaguegamelog" / "2024"
    lgl.mkdir(parents=True)
    (lgl / "regular-season.json").write_text(
        _lgl_payload(
            [
                ["22023", 1610612743, "DEN", GID_REG_1, "2023-10-24", "DEN vs. LAL"],
                ["22023", 1610612747, "LAL", GID_REG_1, "2023-10-24", "LAL @ DEN"],
                ["22023", 1610612744, "GSW", GID_REG_2, "2023-10-24", "GSW vs. PHX"],
                ["22023", 1610612756, "PHX", GID_REG_2, "2023-10-24", "PHX @ GSW"],
            ]
        )
    )
    (lgl / "playoffs.json").write_text(
        _lgl_payload(
            [
                ["42023", 1610612738, "BOS", GID_PLAYOFF, "2024-04-21", "BOS vs. MIA"],
                ["42023", 1610612748, "MIA", GID_PLAYOFF, "2024-04-21", "MIA @ BOS"],
            ]
        )
    )
    # Player-level variant must be skipped, or its game would double in.
    (lgl / "regular-season_p.json").write_text(
        _lgl_payload([["22023", 1, "XXX", "0029999999", "2023-10-24", "XXX vs. YYY"]])
    )

    pbp = root / "playbyplayv3" / "2024"
    pbp.mkdir(parents=True)
    (pbp / f"{GID_REG_1}.json").write_text('{"game": {"actions": [1]}}')  # ok
    (pbp / f"{GID_REG_2}.json").write_text("{}")  # 2 bytes -> error
    (pbp / f"{GID_ORPHAN}.json").write_text('{"game": {}}')  # orphan
    # GID_PLAYOFF absent -> missing

    box = root / "boxscoretraditionalv3" / "2024"
    box.mkdir(parents=True)
    (box / f"{GID_REG_1}.json").write_text("{}")

    # Variant endpoints: no game key, so no has_* flag — endpoint index only.
    tgl = root / "teamgamelogs" / "2024"
    tgl.mkdir(parents=True)
    (tgl / "regular-season_totals.json").write_text("{}")
    draft = root / "drafthistory"
    draft.mkdir(parents=True)
    (draft / "2024.json").write_text("{}")  # flat per-season payload shape
    return root


def test_universe_rows_and_dtypes(tree):
    universe = load_universe(tree)
    assert universe.height == 3
    assert universe.schema["game_id"] == pl.Utf8
    assert universe.schema["game_date"] == pl.Date
    assert set(universe["game_id"].to_list()) == {GID_REG_1, GID_REG_2, GID_PLAYOFF}


def test_season_and_type_come_from_season_id_not_the_dir_label(tree):
    universe = load_universe(tree)
    assert universe["season"].unique().to_list() == ["2023-24"]
    row = universe.filter(pl.col("game_id") == GID_PLAYOFF).to_dicts()[0]
    assert row["season_type"] == "playoffs"
    assert row["home_team_abbreviation"] == "BOS"
    assert row["away_team_abbreviation"] == "MIA"


def test_player_variant_files_are_skipped(tree):
    universe = load_universe(tree)
    assert "0029999999" not in universe["game_id"].to_list()


def test_game_keyed_classification(tree):
    endpoint_gids, _stats, index = walk_raw_tree(tree)
    assert set(endpoint_gids) == {"playbyplayv3", "boxscoretraditionalv3"}
    # Variant endpoints still appear in the per-(endpoint, season) index.
    assert index.filter(pl.col("endpoint") == "teamgamelogs").height == 1
    assert index.filter(pl.col("endpoint") == "drafthistory")["season"].to_list() == ["2024"]


def test_master_schema_is_universe_plus_documented_extras(tree):
    universe = load_universe(tree)
    endpoint_gids, stats, _index = walk_raw_tree(tree)
    master = build_master(universe, endpoint_gids, stats)
    extras = {f"has_{ep}" for ep in endpoint_gids} | set(SCRAPE_STATE_COLUMNS)
    assert set(master.columns) == set(_UNIVERSE_SCHEMA) | extras
    assert master.columns == sorted(master.columns)  # pinned order
    assert master.schema["game_id"] == pl.Utf8


def test_flags_and_scrape_status_reflect_the_tree(tree):
    universe = load_universe(tree)
    endpoint_gids, stats, _index = walk_raw_tree(tree)
    master = build_master(universe, endpoint_gids, stats).sort("game_id")
    by_gid = {r["game_id"]: r for r in master.to_dicts()}
    assert by_gid[GID_REG_1]["has_playbyplayv3"] is True
    assert by_gid[GID_REG_1]["has_boxscoretraditionalv3"] is True
    assert by_gid[GID_REG_1]["scrape_status"] == "ok"
    assert by_gid[GID_REG_2]["scrape_status"] == "error"  # empty-{} payload
    assert by_gid[GID_PLAYOFF]["has_playbyplayv3"] is False
    assert by_gid[GID_PLAYOFF]["scrape_status"] == "missing"
    assert by_gid[GID_PLAYOFF]["json_bytes"] is None
    assert by_gid[GID_REG_1]["json_bytes"] > 2
    assert by_gid[GID_REG_1]["json_captured_at"] is not None
    assert by_gid[GID_REG_1]["last_scraped_at"] == by_gid[GID_REG_1]["json_captured_at"]


def test_coverage_grain_and_rates(tree):
    universe = load_universe(tree)
    endpoint_gids, stats, _index = walk_raw_tree(tree)
    coverage = build_coverage(build_master(universe, endpoint_gids, stats))
    assert coverage.height == 2  # (2023-24, playoffs) + (2023-24, regular_season)
    reg = coverage.filter(pl.col("season_type") == "regular_season").to_dicts()[0]
    assert reg["n_games"] == 2
    assert reg["pct_captured"] == 0.5  # one ok, one empty-{} error
    assert reg["pct_has_playbyplayv3"] == 1.0
    assert str(reg["first_date"]) == "2023-10-24"


def test_reconcile_reports_orphan_files(tree):
    universe = load_universe(tree)
    endpoint_gids, _stats, _index = walk_raw_tree(tree)
    report = reconcile(universe, endpoint_gids)
    pbp = report.filter(pl.col("endpoint") == "playbyplayv3").to_dicts()[0]
    assert pbp["n_orphans"] == 1  # GID_ORPHAN
    assert pbp["n_flagged"] == 2
