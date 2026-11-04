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
