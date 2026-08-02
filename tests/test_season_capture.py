"""Offline tests for the registry + season-level capture.

``fetch`` is injected and the endpoint module is a stub, so everything here runs
without touching stats.{nba,wnba}.com.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from endpoints import (
    ENDPOINT_MEASURE_TYPES,
    LEAGUE_NBA,
    LEAGUE_WNBA,
    MEASURE_TYPE_DOMAINS,
    MEASURE_TYPES,
    PER_MODES,
    SEASON_TYPES,
    discover,
    season_string,
    season_variants,
    slug,
)
from season_capture import (
    _ids_from,
    capture_season,
    game_ids_from_gamelog,
    payload_path,
    plan_season,
    write_payload,
)


# -- a stub league module: signatures are what the registry reads --------------
class StubStats:
    @staticmethod
    def stub_leaguedashteamstats(
        season=None,
        season_type_all_star=None,
        measure_type_detailed_defense=None,
        per_mode_detailed=None,
        league_id=None,
        return_parsed=True,
        proxy_url=None,
    ): ...

    @staticmethod
    def stub_leaguedashplayerstats(
        season=None,
        season_type_all_star=None,
        measure_type_detailed_defense=None,
        per_mode_detailed=None,
        league_id=None,
        return_parsed=True,
    ): ...

    @staticmethod
    def stub_leaguedashlineups(
        season=None,
        season_type_all_star=None,
        measure_type_detailed_defense=None,
        per_mode_detailed=None,
        group_quantity=None,
        league_id=None,
        return_parsed=True,
        proxy_url=None,
    ): ...

    @staticmethod
    def stub_leaguestandingsv3(season=None, league_id=None, return_parsed=True, proxy_url=None): ...

    @staticmethod
    def stub_leaguegamelog(
        season=None,
        season_type_all_star=None,
        league_id=None,
        return_parsed=True,
        proxy_url=None,
    ): ...

    @staticmethod
    def stub_commonteamroster(season=None, team_id=None, league_id=None, return_parsed=True): ...

    @staticmethod
    def stub_playergamelogs(
        season_nullable=None,
        season_type_nullable=None,
        measure_type_player_game_logs_nullable=None,
        per_mode_simple_nullable=None,
        league_id=None,
        return_parsed=True,
    ): ...

    @staticmethod
    def stub_leaguedashteamshotlocations(
        season=None,
        season_type_all_star=None,
        measure_type_simple=None,
        per_mode_detailed=None,
        league_id=None,
        return_parsed=True,
    ): ...

    @staticmethod
    def stub_playbyplayv3(game_id=None, return_parsed=True, proxy_url=None): ...

    @staticmethod
    def stub_teamgamelog(team_id=None, season=None, return_parsed=True): ...

    @staticmethod
    def stub_playercareerstats(player_id=None, return_parsed=True): ...


def _team_payload(team_ids=(1611661313, 1611661317)):
    return {
        "resultSets": [
            {
                "name": "LeagueDashTeamStats",
                "headers": ["TEAM_ID", "TEAM_NAME"],
                "rowSet": [[t, f"Team {t}"] for t in team_ids],
            }
        ]
    }


# -- registry ------------------------------------------------------------------


def test_discover_splits_game_from_season_and_drops_team_player() -> None:
    game, season = discover(StubStats, "stub")
    assert game == ["playbyplayv3"]
    assert "leaguestandingsv3" in season
    # team-/player-keyed endpoints are a separate capture decision
    assert "teamgamelog" not in season and "playercareerstats" not in season
    assert "commonteamroster" not in season  # team-keyed; scheduled separately


def test_matrix_is_derived_from_the_signature() -> None:
    """The matrix is the product of each axis's OWN domain, not of MEASURE_TYPES.

    The stub takes `measure_type_detailed_defense`, which does not accept Usage,
    so the product is 7 measure types rather than all 8.
    """
    v = list(season_variants(StubStats.stub_leaguedashteamstats, 2025, LEAGUE_WNBA))
    domain = ENDPOINT_MEASURE_TYPES["leaguedashteamstats"]
    assert len(v) == len(SEASON_TYPES) * len(domain) * len(PER_MODES)
    slugs = [s for s, _k in v]
    assert len(set(slugs)) == len(slugs), "variant slugs must be unique"
    assert "regular-season_base_totals" in slugs
    assert "regular-season_four-factors_totals" in slugs, "Four Factors must be captured"


def test_measure_types_are_narrowed_to_the_parameter_domain() -> None:
    """Sweeping every MEASURE_TYPES value over every measure_type* parameter is
    what produced most of this archive's empty payloads: the endpoint accepts
    the parameter but the API cannot answer the value, and the unparseable body
    was persisted as `{}` and never retried."""
    # Parameter-level default.
    got = {
        k["measure_type_simple"]
        for _s, k in season_variants(StubStats.stub_leaguedashteamshotlocations, 2025, LEAGUE_WNBA)
    }
    assert got == set(MEASURE_TYPE_DOMAINS["measure_type_simple"]) == {"Base", "Opponent"}

    # Endpoint-level override beats it. leaguedashteamstats rejects Usage while
    # leaguedashplayerstats -- same parameter -- accepts it, so keying only by
    # parameter name silently dropped Usage from five endpoints that support it.
    got = {
        k["measure_type_detailed_defense"]
        for _s, k in season_variants(StubStats.stub_leaguedashteamstats, 2025, LEAGUE_WNBA)
    }
    assert got == set(ENDPOINT_MEASURE_TYPES["leaguedashteamstats"])
    assert "Usage" not in got


def test_endpoint_override_does_not_leak_into_other_axes() -> None:
    """_SWEEPS also carries season_type and per_mode. An endpoint override
    applied to those set season_type_all_star="Base" and per_mode_detailed="Misc",
    turning one endpoint's matrix into the cube of its measure types (343
    variants instead of 28)."""
    for _s, kwargs in season_variants(StubStats.stub_leaguedashteamstats, 2025, LEAGUE_WNBA):
        assert kwargs["season_type_all_star"] in SEASON_TYPES
        assert kwargs["per_mode_detailed"] in PER_MODES


def test_endpoints_sharing_a_parameter_keep_their_own_domains() -> None:
    """The archive says leaguedashplayerstats supports Usage and
    leaguedashteamstats does not, though both take measure_type_detailed_defense."""
    player = {
        k["measure_type_detailed_defense"]
        for _s, k in season_variants(StubStats.stub_leaguedashplayerstats, 2025, LEAGUE_WNBA)
    }
    team = {
        k["measure_type_detailed_defense"]
        for _s, k in season_variants(StubStats.stub_leaguedashteamstats, 2025, LEAGUE_WNBA)
    }
    assert "Usage" in player
    assert "Usage" not in team


def test_four_factors_is_in_the_full_measure_type_list() -> None:
    """It was missing entirely, so no endpoint ever captured it."""
    assert "Four Factors" in MEASURE_TYPES


def test_season_is_pinned_even_when_spelled_nullable() -> None:
    """playergamelogs / teamgamelogs spell it `season_nullable`. The pin used to
    test the bare `season` only, so those endpoints were called with NO season
    filter and 100% of their captures came back empty in both leagues."""
    for _v, kwargs in season_variants(StubStats.stub_playergamelogs, 2025, LEAGUE_WNBA):
        assert kwargs.get("season_nullable") == "2025-26", "span string, not a bare year"
        assert "season" not in kwargs, "must not send a parameter the endpoint lacks"


def test_endpoint_without_axes_gets_one_unparameterized_capture() -> None:
    v = list(season_variants(StubStats.stub_leaguestandingsv3, 2025, LEAGUE_WNBA))
    assert len(v) == 1 and v[0][0] is None


def test_only_supported_axes_are_swept() -> None:
    """leaguegamelog has no measure/per-mode, so it must not be swept over them."""
    v = list(season_variants(StubStats.stub_leaguegamelog, 2025, LEAGUE_WNBA))
    assert len(v) == len(SEASON_TYPES)


def test_every_call_pins_season_and_league() -> None:
    for fn in (StubStats.stub_leaguedashteamstats, StubStats.stub_leaguestandingsv3):
        for _v, kwargs in season_variants(fn, 2025, LEAGUE_WNBA):
            assert kwargs["season"] == "2025-26", "span string, not a bare year"
            assert kwargs["league_id"] == LEAGUE_WNBA


def test_pinned_params_are_applied_only_where_accepted() -> None:
    lineups = list(season_variants(StubStats.stub_leaguedashlineups, 2025, LEAGUE_WNBA))
    assert all(k["group_quantity"] == 5 for _v, k in lineups)
    teams = list(season_variants(StubStats.stub_leaguedashteamstats, 2025, LEAGUE_WNBA))
    assert all("group_quantity" not in k for _v, k in teams)


def test_totals_and_pergame_are_both_captured() -> None:
    """Totals is the derivable form; PerGame is what current consumers read."""
    v = list(season_variants(StubStats.stub_leaguedashteamstats, 2025, LEAGUE_WNBA))
    modes = {k["per_mode_detailed"] for _s, k in v}
    assert modes == set(PER_MODES)


def test_slug() -> None:
    assert slug("Regular Season") == "regular-season"
    assert slug("FourFactors") == "fourfactors"


# -- paths + writing -----------------------------------------------------------


def test_payload_path_shape(tmp_path: Path) -> None:
    assert payload_path(tmp_path, "x", 2025, "base_playoffs") == (
        tmp_path / "x" / "2025" / "base_playoffs.json"
    )
    assert payload_path(tmp_path, "x", 2025) == tmp_path / "x" / "2025.json"


def test_write_payload_is_atomic(tmp_path: Path) -> None:
    p = tmp_path / "a" / "b.json"
    write_payload(p, {"a": 1})
    assert json.loads(p.read_text()) == {"a": 1}
    assert not list(tmp_path.rglob(".*.partial"))


def test_plan_keys_are_unique() -> None:
    """A collision would silently overwrite one capture with another."""
    seen = set()
    for endpoint, variant, _k in plan_season(2025, StubStats, "stub", LEAGUE_WNBA):
        assert (endpoint, variant) not in seen
        seen.add((endpoint, variant))


# -- capture -------------------------------------------------------------------


def test_capture_writes_then_skips(tmp_path: Path) -> None:
    calls: list[str] = []

    def fetch(endpoint, kwargs):
        calls.append(endpoint)
        return _team_payload() if endpoint == "leaguedashteamstats" else {"e": endpoint}

    written, skipped, failed = capture_season(2025, tmp_path, fetch, StubStats, "stub", LEAGUE_WNBA)
    planned = len(list(plan_season(2025, StubStats, "stub", LEAGUE_WNBA)))
    assert failed == 0 and skipped == 0
    assert written == planned + 2  # + one commonteamroster per team

    before = len(calls)
    w2, s2, f2 = capture_season(2025, tmp_path, fetch, StubStats, "stub", LEAGUE_WNBA)
    assert (w2, f2) == (0, 0) and s2 == written
    assert len(calls) == before, "a second sweep must not refetch anything"


def test_one_failing_endpoint_does_not_abort_the_season(tmp_path: Path) -> None:
    def fetch(endpoint, kwargs):
        if endpoint == "leaguedashlineups":
            raise RuntimeError("upstream 500")
        return _team_payload() if endpoint == "leaguedashteamstats" else {"ok": True}

    written, _skipped, failed = capture_season(
        2025, tmp_path, fetch, StubStats, "stub", LEAGUE_WNBA
    )
    assert failed == len(list(season_variants(StubStats.stub_leaguedashlineups, 2025, LEAGUE_WNBA)))
    assert written > 0


def test_team_roster_ids_come_from_the_team_stats_capture(tmp_path: Path) -> None:
    def fetch(endpoint, kwargs):
        return _team_payload((99,)) if endpoint == "leaguedashteamstats" else {"ok": True}

    capture_season(2025, tmp_path, fetch, StubStats, "stub", LEAGUE_WNBA)
    assert (tmp_path / "commonteamroster" / "2025" / "99.json").exists()


def test_game_ids_from_gamelog_zero_pads() -> None:
    payload = {"resultSets": [{"headers": ["GAME_ID"], "rowSet": [[1022500001], ["1022500002"]]}]}
    assert game_ids_from_gamelog(payload) == ["1022500001", "1022500002"]
    assert game_ids_from_gamelog(None) == []


# -- against the real league modules ------------------------------------------


def test_real_modules_discover_expected_shapes() -> None:
    from sportsdataverse.nba import nba_stats as N
    from sportsdataverse.wnba import wnba_stats as W

    for mod, pre, n_game in ((W, "wnba_stats", 14), (N, "nba_stats", 13)):
        game, season = discover(mod, pre)
        assert len(game) == n_game
        assert len(season) > 30
        assert "playbyplayv3" in game and "boxscoresummaryv2" in game


@pytest.mark.parametrize("league", ["wnba", "nba"])
def test_real_variant_slugs_never_collide(league: str) -> None:
    import importlib

    pre = f"{league}_stats"
    mod = importlib.import_module(f"sportsdataverse.{league}.{pre}")
    lid = "10" if league == "wnba" else "00"
    seen = set()
    for endpoint, variant, _k in plan_season(2025, mod, pre, lid):
        assert (endpoint, variant) not in seen, f"{endpoint}/{variant}"
        seen.add((endpoint, variant))


# ---------------------------------------------------------------------------
# The empty-payload guard.
#
# hoopR-nba-stats-raw accumulated 3,347 files that are exactly `{}` and
# wehoop-wnba-stats-raw another 3,872, ten endpoints being 100% empty. They are
# permanent: write_payload had no guard, and resume is `path.exists()` --
# presence, not content -- so one empty write is never retried.
#
# A live probe confirmed several are real data when refetched
# (leaguedashptteamdefend 30 rows, matchupsrollup 2,283, shot-locations
# MeasureType=Advanced 30), i.e. those `{}` files were failed fetches that got
# persisted as if they were answers.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", [{}, [], None, "", 0, "not-json"])
def test_contentless_payloads_are_refused(payload, tmp_path: Path) -> None:
    path = tmp_path / "e" / "2024" / "v.json"
    assert write_payload(path, payload) is False
    assert not path.exists(), "a contentless payload must leave NO file behind"


@pytest.mark.parametrize(
    "payload",
    [
        # An envelope with zero rows is a REAL answer -- 1996 playoff leaders
        # legitimately have none. The guard must not eat these.
        {"resource": "leagueleaders", "parameters": {}, "resultSet": {"rowSet": []}},
        {"resource": "x", "parameters": {}, "resultSets": []},
        # v3 with an empty action list: playbyplayv3 pre-1997 really is like this.
        {"meta": {"version": 1}, "game": {"actions": []}},
    ],
)
def test_empty_but_real_answers_are_persisted(payload, tmp_path: Path) -> None:
    path = tmp_path / "e" / "2024" / "v.json"
    assert write_payload(path, payload) is True
    assert json.loads(path.read_text(encoding="utf-8")) == payload


def test_capture_counts_an_empty_payload_as_failed_not_written(tmp_path: Path) -> None:
    """The season summary must not report a refused write as a capture."""

    def fetch(endpoint, kwargs):
        return {}

    written, _skipped, failed = capture_season(
        2025, tmp_path, fetch, StubStats, "stub", LEAGUE_WNBA
    )
    assert written == 0
    assert failed > 0
    assert not list(tmp_path.rglob("*.json")), "no file may be left for a retry to skip"


def test_a_refused_write_is_retried_on_the_next_sweep(tmp_path: Path) -> None:
    """The whole point of the guard: the gap must not become permanent."""
    calls = {"n": 0}

    def flaky(endpoint, kwargs):
        calls["n"] += 1
        # First sweep: everything comes back empty. Second: real payloads.
        if calls["n"] <= 1000 and not flaky.recovered:
            return {}
        return {"resource": endpoint, "parameters": dict(kwargs), "resultSets": [{"rowSet": [[1]]}]}

    flaky.recovered = False
    w1, _s1, f1 = capture_season(2025, tmp_path, flaky, StubStats, "stub", LEAGUE_WNBA)
    assert w1 == 0 and f1 > 0

    flaky.recovered = True
    w2, s2, _f2 = capture_season(2025, tmp_path, flaky, StubStats, "stub", LEAGUE_WNBA)
    assert w2 > 0, "the second sweep must refetch what the first refused to persist"
    assert s2 == 0, "nothing should have been skipped-as-present"


# -- envelope shapes -----------------------------------------------------------
#
# stats.nba.com ships five envelope families (see sdv-py
# sportsdataverse/schemas/raw/nba_stats_*.yaml). _ids_from used to iterate
# payload["resultSets"] directly, which is only correct for one of them.


def test_ids_from_reads_the_plural_list_envelope() -> None:
    assert _ids_from(_team_payload((5, 7)), "TEAM_ID") == ["5", "7"]


def test_ids_from_reads_the_singular_result_set_envelope() -> None:
    """leagueleaders / *estimatedmetrics use `resultSet` (singular, a dict).
    Anything looking only at the plural key sees nothing at all."""
    payload = {
        "resource": "leagueleaders",
        "parameters": {},
        "resultSet": {"name": "x", "headers": ["TEAM_ID"], "rowSet": [[9]]},
    }
    assert _ids_from(payload, "TEAM_ID") == ["9"]


def test_ids_from_survives_the_grouped_dict_envelope() -> None:
    """The shot-locations family keys `resultSets` to a DICT. Iterating it
    yields its keys, so the old code called .get() on a string and raised
    AttributeError."""
    payload = {
        "resource": "leaguedashteamshotlocations",
        "parameters": {},
        "resultSets": {
            "name": "ShotLocations",
            # column-GROUP dicts, not name strings
            "headers": [{"name": "SHOT_CATEGORY", "columnNames": ["Restricted Area"]}],
            "rowSet": [[1610612737, "Atlanta Hawks"]],
        },
    }
    assert _ids_from(payload, "TEAM_ID") == []  # no match, and no exception


def test_ids_from_ignores_v3_payloads() -> None:
    """The v3 family carries no result tables at all."""
    payload = {"meta": {"version": 1}, "boxScoreTraditional": {"gameId": "0029500001"}}
    assert _ids_from(payload, "TEAM_ID") == []


def test_ids_from_tolerates_a_short_row() -> None:
    payload = {"resultSets": [{"headers": ["A", "TEAM_ID"], "rowSet": [[1], [2, 3]]}]}
    assert _ids_from(payload, "TEAM_ID") == ["3"]


# ---------------------------------------------------------------------------
# NBA season string. A BARE year silently returns zero rows on several
# endpoints while others tolerate it, so the sweep looked healthy while seven
# endpoints captured a valid envelope with no data, every season, for years.
# ---------------------------------------------------------------------------


def test_season_string_spans_two_years() -> None:
    assert season_string(2023) == "2023-24"
    assert season_string(1996) == "1996-97"


def test_season_string_zero_pads_the_century_rollover() -> None:
    """1999 -> "1999-00", not "1999-0" or "1999-100"."""
    assert season_string(1999) == "1999-00"
    assert season_string(2009) == "2009-10"


def test_span_string_is_sent_for_the_season_parameter() -> None:
    for _v, kwargs in season_variants(StubStats.stub_leaguedashteamstats, 2023, LEAGUE_NBA):
        assert kwargs["season"] == "2023-24"


def test_span_string_is_sent_for_season_nullable_too() -> None:
    """playergamelogs/teamgamelogs spell it season_nullable and need the span
    just as much -- measured: leaguedashptstats 0 -> 572 rows."""
    for _v, kwargs in season_variants(StubStats.stub_playergamelogs, 2023, LEAGUE_NBA):
        assert kwargs["season_nullable"] == "2023-24"


def test_season_year_stays_a_bare_year() -> None:
    """`season_year` on draftcombine* is a DRAFT year, a genuine single year.
    Spanning it would break those endpoints."""

    class DraftStub:
        @staticmethod
        def stub_draftcombinestats(season_year=None, league_id=None, return_parsed=True): ...

    variants = list(season_variants(DraftStub.stub_draftcombinestats, 2023, LEAGUE_NBA))
    assert variants, "expected one unparameterized capture"
    for _v, kwargs in variants:
        assert kwargs["season_year"] == "2023", "draft year must not be spanned"
