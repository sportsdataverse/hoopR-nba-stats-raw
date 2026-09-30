"""Every store dir keys the season END year -- including the season-level half.

The season-level half (``leaguegamelog``, ``leaguedash*``, ...) was filed under the
START year until the 2026-09-30 re-key, while the per-game half used the END year.
Nothing errors when the two disagree: the 2026-09-30 daily passed an END year into a
START-keyed path, fetched NEXT season, indexed 0 games, and exited 0.
"""

from __future__ import annotations

import json

import pytest
from nba_stats_raw_scrape import _capture_runtime as rt
from nba_stats_raw_scrape.period_capture import season_of


def _gamelog(*game_ids: str) -> dict:
    return {
        "resultSets": [
            {"name": "LeagueGameLog", "headers": ["GAME_ID"], "rowSet": [[g] for g in game_ids]}
        ]
    }


def test_game_index_reads_the_end_year_dir(tmp_path) -> None:
    """With both neighbouring captures on disk, END 2026 must index 2025-26 from dir 2026."""
    for year, gid in (("2025", "0022400001"), ("2026", "0022500001")):
        p = tmp_path / "leaguegamelog" / year / "regular-season.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(_gamelog(gid)), encoding="utf-8")
    gids = rt.game_ids_for_season(str(tmp_path), 2026)
    assert gids == {"0022500001"}, "read the neighbouring season's index"
    # cross-half agreement: those ids live in the per-game dir of the same season
    assert {season_of(g) for g in gids} == {2026}


@pytest.mark.parametrize("season", [1997, 2014, 2026])
def test_committed_season_level_dirs_are_end_year(season: int) -> None:
    """``leaguegamelog/{Y}/`` in the real store holds SEASON_ID 2{Y-1} (the START year of season Y)."""
    path = rt.REPO / "nba_stats" / "json" / "leaguegamelog" / str(season) / "regular-season.json"
    if not path.exists():
        pytest.skip(f"no committed capture at {path}")
    rs = json.loads(path.read_text(encoding="utf-8"))["resultSets"][0]
    idx = rs["headers"].index("SEASON_ID")
    starts = {int(str(row[idx])[1:]) for row in rs["rowSet"]}
    assert starts == {season - 1}, f"dir {season} holds START {sorted(starts)}: not END-keyed"


def test_game_index_adds_play_in_and_cup_final_from_the_schedule(tmp_path) -> None:
    """leaguegamelog omits the play-in (5) and Cup final (6); the schedule adds only those."""
    p = tmp_path / "leaguegamelog" / "2026" / "regular-season.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(_gamelog("0022500001")), encoding="utf-8")
    ids = ["0012500001", "0022500001", "0032500001", "0052500101", "0062500001", "0092500001"]
    sched = tmp_path / "scheduleleaguev2" / "2026.json"
    sched.parent.mkdir(parents=True)
    sched.write_text(
        json.dumps({"leagueSchedule": {"gameDates": [{"games": [{"gameId": g} for g in ids]}]}}),
        encoding="utf-8",
    )
    assert rt.game_ids_for_season(str(tmp_path), 2026) == {"0022500001", "0052500101", "0062500001"}
