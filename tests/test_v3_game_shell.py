"""A per-game v3 placeholder capture is re-fetched, real data is kept (#16)."""

from __future__ import annotations

import json

from nba_stats_raw_scrape._capture_runtime import is_v3_game_shell


def _write(tmp_path, payload) -> object:
    p = tmp_path / "0022600004.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_playertrack_shell_is_detected(tmp_path):
    # Shape of nba_stats/json/boxscoreplayertrackv3/2027/0022600004.json as captured.
    empty = {"teamId": 0, "players": [], "statistics": None}
    p = _write(
        tmp_path, {"meta": {}, "boxScorePlayerTrack": {"homeTeam": empty, "awayTeam": empty}}
    )
    assert is_v3_game_shell(p)


def test_real_capture_is_kept(tmp_path):
    team = {"teamId": 1610612748, "players": [{"personId": 1}]}
    p = _write(tmp_path, {"boxScorePlayerTrack": {"homeTeam": team, "awayTeam": team}})
    assert not is_v3_game_shell(p)


def test_non_boxscore_and_unreadable(tmp_path):
    assert not is_v3_game_shell(_write(tmp_path, {"game": {"actions": []}}))
    bad = tmp_path / "torn.json"
    bad.write_text("{", encoding="utf-8")
    assert is_v3_game_shell(bad)


def _summary(status, home_inactives, away_inactives):
    def team(inactives):
        return {"teamId": 1610612738, "inactives": inactives}

    return {
        "boxScoreSummary": {
            "gameStatus": status,
            "homeTeam": team(home_inactives),
            "awayTeam": team(away_inactives),
        }
    }


def test_final_summary_with_no_inactives_is_a_shell(tmp_path):
    # Shape of boxscoresummaryv3/2027/0022600001.json as captured 2026-10-21.
    assert is_v3_game_shell(_write(tmp_path, _summary(3, [], [])))


def test_summary_with_inactives_or_not_final_is_kept(tmp_path):
    one = [{"personId": 1}]
    assert not is_v3_game_shell(_write(tmp_path, _summary(3, one, [])))
    assert not is_v3_game_shell(_write(tmp_path, _summary(3, [], one)))
    assert not is_v3_game_shell(_write(tmp_path, _summary(2, [], [])))
