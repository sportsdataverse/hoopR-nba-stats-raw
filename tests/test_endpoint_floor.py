"""Tests for the per-endpoint season floor (`_skip_endpoint`).

This file was dead for several months: `_skip_endpoint` was refactored into two
inlined comprehensions (4ec4c143a4) and the import here broke, but the repo had
no pyproject and no CI, and the file sat in `scripts/` where nothing collected
it -- so nothing ever reported the failure. Both problems are fixed: the helper
is a named module-level function again, and pytest collects `tests/`.

`pythonpath = ["python"]` in pyproject puts the scraper modules on sys.path;
there is deliberately no sys.path hack here.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from scrape_raw_json import ENDPOINT_MIN_SEASON, _skip_endpoint

# Real NBA seasons the scraper sweeps (start-year encoding).
REAL_SEASONS = (1996, 2005, 2015, 2016, 2020, 2026)


def test_endpoints_without_a_floor_are_never_skipped() -> None:
    """The `.get(endpoint, 0)` default: absent from the table == no floor.

    These two carry data for every season back to 1996, so a regression that
    gave them a floor would silently truncate the archive.
    """
    for season in REAL_SEASONS:
        assert not _skip_endpoint("playbyplayv3", season)
        assert not _skip_endpoint("boxscoretraditionalv3", season)


def test_floor_is_inclusive_at_the_boundary() -> None:
    """Season == floor must be KEPT, not skipped.

    The off-by-one here is the whole risk: boxscorematchupsv3 probes empty
    through 2016-17 and populates from 2017-18, so 2017 is real data. An
    exclusive comparison would drop a full season of matchup box scores.
    """
    floor = ENDPOINT_MIN_SEASON["boxscorematchupsv3"]
    assert floor == 2017
    assert _skip_endpoint("boxscorematchupsv3", floor - 1)
    assert not _skip_endpoint("boxscorematchupsv3", floor)
    assert not _skip_endpoint("boxscorematchupsv3", floor + 1)


def test_gamerotation_floor_is_honoured_whatever_it_is_set_to() -> None:
    """gamerotation is skipped below its floor and kept at/above it.

    Asserted against the CONFIGURED floor rather than a hardcoded number,
    because GAMEROTATION_MIN_SEASON is a supported override -- the documented
    dedicated capture pass sets it to 2016, and a test pinned to the parked
    sentinel would fail during exactly that run.
    """
    floor = ENDPOINT_MIN_SEASON["gamerotation"]
    assert _skip_endpoint("gamerotation", floor - 1)
    assert not _skip_endpoint("gamerotation", floor)


def test_gamerotation_defaults_to_parked() -> None:
    """With no override, the floor sits above any real season so the main sweep
    skips gamerotation entirely.

    It holds real data from 2015-16 but times out under the sweep's concurrency
    and drags every 2016+ season, so it is captured by a separate low-concurrency
    pass. If a future edit drops the sentinel back to 2016, the main sweep
    silently gets slow again -- this is the alarm.

    Read in a subprocess with the override cleared: the module-level dict is
    built at import time, so monkeypatching the environment afterwards would
    prove nothing.
    """
    src = (
        "import os, sys;"
        " os.environ.pop('GAMEROTATION_MIN_SEASON', None);"
        " sys.path.insert(0, 'python');"
        " import scrape_raw_json as s;"
        " print(s.ENDPOINT_MIN_SEASON['gamerotation'])"
    )
    out = subprocess.run(
        [sys.executable, "-c", src],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
        check=True,
    )
    assert int(out.stdout.strip()) > max(REAL_SEASONS)


def test_player_tracking_endpoints_share_the_sportvu_floor() -> None:
    """SportVU tracking begins 2013-14; all six PT endpoints share that floor."""
    pt_endpoints = (
        "leaguedashptstats",
        "leaguedashptdefend",
        "leaguedashplayerptshot",
        "leaguedashoppptshot",
        "leaguedashteamptshot",
        "leaguedashptteamdefend",
    )
    for endpoint in pt_endpoints:
        assert _skip_endpoint(endpoint, 2012)
        assert not _skip_endpoint(endpoint, 2013)


PARKED = ("playercompare",)

DRAFTCOMBINE = (
    "draftcombinestats",
    "draftcombinedrillresults",
    "draftcombineplayeranthro",
    "draftcombinespotshooting",
    "draftcombinenonstationaryshooting",
)


def _floors_in_subprocess(preamble: str, endpoints: tuple[str, ...]) -> list[int]:
    """Import the module in a clean subprocess and read the given floors.

    ``ENDPOINT_MIN_SEASON`` is built at import time, so the environment has to be
    arranged BEFORE the import -- monkeypatching in-process proves nothing. Every
    parked-endpoint override is cleared first, so a shell that has one exported
    for a fixed-parameter run cannot make these tests lie in either direction.
    """
    src = (
        "import os, sys;"
        " [os.environ.pop(k, None) for k in list(os.environ)"
        " if k.endswith('_MIN_SEASON')];"
        f" {preamble}"
        " sys.path.insert(0, 'python');"
        " import scrape_raw_json as s;"
        f" print(*[s.ENDPOINT_MIN_SEASON[e] for e in {endpoints!r}])"
    )
    out = subprocess.run(
        [sys.executable, "-c", src],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
        check=True,
    )
    return [int(v) for v in out.stdout.split()]


def test_nonfunctional_endpoints_are_parked() -> None:
    """playercompare is ENTITY-keyed: it answers when given real PlayerIDList /
    VsPlayerIDList values (probed 2026-08-02), but a season-level sweep has no
    player ids to supply, and its 28 variants/season each cost a full request
    timeout (measured 2026-08-01: 9m18s / 7m51s on seasons carrying it).
    Parked until a per-entity capture design exists -- NOT because the endpoint
    is broken.
    """
    for floor in _floors_in_subprocess("", PARKED):
        assert floor > max(REAL_SEASONS)


@pytest.mark.parametrize("endpoint", PARKED)
def test_parked_endpoints_are_skipped_for_every_real_season(endpoint) -> None:
    """Behaviour against the CONFIGURED floor, so an intentional override in the
    environment does not fail the suite (see test_gamerotation_* for the pair)."""
    floor = ENDPOINT_MIN_SEASON[endpoint]
    for season in REAL_SEASONS:
        assert _skip_endpoint(endpoint, season) == (season < floor)


@pytest.mark.parametrize("endpoint", PARKED)
def test_each_parked_endpoint_is_independently_overridable(endpoint) -> None:
    """Every parked endpoint reads its own <ENDPOINT>_MIN_SEASON, so a
    fixed-parameter run can re-enable exactly one. (When the five draftcombine
    endpoints were parked, a shared variable would have un-parked all five at
    once -- keep the per-endpoint contract even now that only playercompare
    remains.)
    """
    var = f"{endpoint.upper()}_MIN_SEASON"
    others = tuple(e for e in PARKED if e != endpoint)
    floors = _floors_in_subprocess(f" os.environ[{var!r}] = '2015';", (endpoint,) + others)
    assert floors[0] == 2015, f"{var} must set only {endpoint}"
    for other, floor in zip(others, floors[1:]):
        assert floor > max(REAL_SEASONS), f"{var} must not un-park {other}"


def test_endpoints_that_do_work_are_not_parked() -> None:
    """leaguedashptteamdefend returns real data for recent seasons,
    teamgamelogs fails only on its Usage variants, and the draftcombine family
    answers with the sweep's own parameters (probed 2026-08-02) -- parking any
    of them would discard genuine captures."""
    for endpoint in ("leaguedashptteamdefend", "teamgamelogs", "playergamelogs") + DRAFTCOMBINE:
        assert ENDPOINT_MIN_SEASON.get(endpoint, 0) <= max(REAL_SEASONS)


def test_draftcombine_floor_2000() -> None:
    """The combine family answers valid zero-row envelopes for 1996-99 and real
    tables from 2000 on (65 rows probed for 2000); the floor skips only the
    pre-2000 waste."""
    for endpoint in DRAFTCOMBINE:
        assert _skip_endpoint(endpoint, 1999)
        assert not _skip_endpoint(endpoint, 2000)


def test_no_duplicate_endpoint_keys() -> None:
    """A duplicate key in the ENDPOINT_MIN_SEASON literal is invisible at
    runtime -- the later one silently wins.

    That is not hypothetical: the parked `playercompare` floor was overridden by
    a stale `"playercompare": 2014` further down the same literal, which un-parked
    it and cost ~8 minutes per season on requests that cannot succeed. Inspecting
    the built dict cannot detect it (the duplicate is already collapsed), so this
    parses the source.
    """
    import ast

    src = (Path(__file__).resolve().parent.parent / "python" / "scrape_raw_json.py").read_text(
        encoding="utf-8"
    )
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "ENDPOINT_MIN_SEASON" for t in node.targets):
            continue
        assert isinstance(node.value, ast.Dict)
        keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
        dupes = {k for k in keys if keys.count(k) > 1}
        assert not dupes, f"duplicate ENDPOINT_MIN_SEASON keys: {sorted(dupes)}"
        return
    raise AssertionError("ENDPOINT_MIN_SEASON assignment not found")


def test_no_false_ceilings() -> None:
    """ENDPOINT_MAX_SEASON must stay empty until a calm probe shows every later
    season answering a VALID ZERO-ROW envelope. The draftcombine* 2019 ceilings
    that used to live there were false -- probed 2026-08-02: 74/83/83 rows for
    2021/2022/2024; the "NOTHING after 2019" reading dated from the era when
    draftcombinestats was swept with no season parameter at all. The mechanism
    silently discards real seasons, so an entry needs probe-dated evidence."""
    from scrape_raw_json import ENDPOINT_MAX_SEASON

    assert ENDPOINT_MAX_SEASON == {}


def test_lineup_dashboards_floor_2007() -> None:
    """Both lineup dashboards answer a valid zero-row envelope before 2007-08."""
    for ep in ("leaguedashlineups", "leaguelineupviz"):
        assert _skip_endpoint(ep, 2006)
        assert not _skip_endpoint(ep, 2007)


def test_game_log_family_floor_2014() -> None:
    """Post-defaults-fix census: playergamelogs 3.29M rows and teamgamelogs
    247k rows both start 2014 (tracking-era game logs). Pre-2014 the API
    answers contentless; the floor stops re-asking every sweep."""
    for ep in ("playergamelogs", "teamgamelogs"):
        assert _skip_endpoint(ep, 2013)
        assert not _skip_endpoint(ep, 2014)
