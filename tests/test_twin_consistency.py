"""Twin-consistency gate: league binding + shared-transport wiring.

This repo is a league-binding shim over the shared sweep engine in
``sportsdataverse.scrape.stats`` (sdv-py #327 extraction removed ~2,200 lines
of duplicated engine code from this repo and its NBA/WNBA twin). What is left
for THIS repo to get wrong is narrow but real: which league it binds, and
whether it still routes every fetch through the shared session/health object
rather than a leftover pre-migration code path. Both are self-contained,
in-repo checks -- no cross-repo read of the sibling twin.

Portability: this file derives the league it should see from
``pyproject.toml``'s package name (never hardcoded), so it is byte-identical
in the sibling twin. Any diff between the two copies is drift, not a league
difference.

1. **League binding.** ``LEAGUE_ID = "00"/"10"`` literals (in
   ``period_capture.py`` / ``schedule_master.py`` / ``_capture_runtime.py``)
   and the ``NBA``/``WNBA`` config object ``nba_stats_20_refill_empty.py`` imports must
   bind the league this repo actually is. A copy-paste from the sibling that
   forgot to flip one of these would silently scrape/report the wrong league,
   or crash on the first real (non-``--check``) run -- exactly the
   ``sportsdataverse.nba.wnba_stats`` incident ``league_config.py`` documents
   in its ``WNBA`` entry.

2. **Transport wiring.** ``_capture_runtime.py``'s own module docstring states
   the contract: ``SessionTransport`` "owns proxy selection ... so the fetch
   closures pass no proxy_url" -- every live fetch call, in EVERY script under
   ``python/``, must route through ``transport=...``, never a raw
   ``proxy_url=rr.next()`` that bypasses health recording and the sticky JA3
   session. Two real regressions of exactly this kind have shipped: one
   leftover pre-migration call site in ``_capture_runtime.py``'s per-period
   boxscore closure, and a second in ``backfill_leaguegamelog_player.py``
   masked by a bare ``except ImportError: return None`` around a cross-repo
   import (see 3). The first check used to scan only ``_capture_runtime.py``;
   that narrow scope is exactly how the second one survived, so it now scans
   every script.

3. **No cross-repo import.** A ``-raw`` script importing ``nba_data_build`` /
   ``wnba_data_build`` -- the sibling ``-data`` repo's package -- is not
   installed here and cannot resolve; the only way it "worked" before was by
   silently swallowing the ``ImportError`` and disabling whatever depended on
   it. That should never typecheck as correct again.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

from sportsdataverse.scrape.stats.league_config import NBA, WNBA, LeagueConfig

REPO = Path(__file__).resolve().parents[1]
PYTHON = REPO / "python"


def _expected_league() -> LeagueConfig:
    """The ``LeagueConfig`` this repo owns, derived from the package name."""
    name = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["name"]
    if "wnba" in name:
        return WNBA
    if "nba" in name:
        return NBA
    raise AssertionError(f"pyproject [project].name {name!r} names neither nba nor wnba")


def _league_id_literals() -> dict[Path, object]:
    """``LEAGUE_ID = "..."`` module-level assignments under ``python/``."""
    found: dict[Path, object] = {}
    for path in sorted(PYTHON.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id == "LEAGUE_ID" for t in node.targets):
                continue
            if isinstance(node.value, ast.Constant):
                found[path] = node.value.value
    return found


def test_layout_is_discoverable() -> None:
    """Guard the guard: if the parser finds nothing, every check below passes
    vacuously without having checked anything."""
    assert _expected_league()
    literals = _league_id_literals()
    assert literals, (
        'no `LEAGUE_ID = "..."` literal found under python/ -- did the binding pattern move?'
    )


def test_league_id_literals_match_this_repo() -> None:
    expected = _expected_league()
    wrong = {
        str(path.relative_to(REPO)): value
        for path, value in _league_id_literals().items()
        if value != expected.league_id
    }
    assert not wrong, (
        f"expected LEAGUE_ID == {expected.league_id!r} ({expected.key}) everywhere "
        f"under python/, found mismatches: {wrong}"
    )


def test_nba_stats_20_refill_empty_binds_the_right_league_config() -> None:
    """``nba_stats_20_refill_empty.py`` imports NBA/WNBA by name and passes it to ``main()``
    -- the exact shape of the caught incident (importing a module that does
    not exist for this league)."""
    expected = _expected_league()
    source = (PYTHON / "nba_stats_20_refill_empty.py").read_text(encoding="utf-8")
    imported = re.findall(
        r"from sportsdataverse\.scrape\.stats\.league_config import (\w+)", source
    )
    assert imported, "nba_stats_20_refill_empty.py must import its LeagueConfig from league_config"
    assert imported == [expected.key.upper()], (
        f"nba_stats_20_refill_empty.py imports {imported}, expected [{expected.key.upper()!r}]"
    )
    assert re.search(rf"main\({expected.key.upper()}\b", source), (
        f"nba_stats_20_refill_empty.py must call main({expected.key.upper()}, ...)"
    )


def _all_python_sources() -> dict[Path, str]:
    return {path: path.read_text(encoding="utf-8") for path in sorted(PYTHON.glob("*.py"))}


def _call_sites_with_kwarg(source: str, kwarg: str) -> list[int]:
    """Line numbers of any call passing the keyword argument ``kwarg``."""
    tree = ast.parse(source)
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == kwarg
    ]


def test_no_script_bypasses_the_session_transport() -> None:
    """SessionTransport's whole point is to own proxy selection + health
    recording; a stray ``proxy_url=`` call site skips both silently (the
    request still succeeds, it just isn't tracked or session-reused).

    Scans every ``python/*.py``, not just ``_capture_runtime.py`` -- that
    narrower scope is exactly how a second bypass (in
    ``backfill_leaguegamelog_player.py``) survived the first version of this
    check. One closure called ``proxy_url=rr.next()`` after the rest of
    ``_capture_runtime.py`` had moved to ``transport=``; the other built its
    own ``RoundRobin`` and called ``proxy_url=provider()`` because the
    provider it meant to build (a ``SessionTransport``) came from an import
    that silently failed (see ``test_no_script_imports_the_data_repo_package``).
    """
    offenders = {
        str(path.relative_to(REPO)): sites
        for path, source in _all_python_sources().items()
        if (sites := _call_sites_with_kwarg(source, "proxy_url"))
    }
    assert not offenders, (
        f"proxy_url= passed directly (bypasses SessionTransport's health "
        f"recording + session reuse): {offenders} -- use transport=... instead"
    )
    transport_users = [
        str(path.relative_to(REPO))
        for path, source in _all_python_sources().items()
        if _call_sites_with_kwarg(source, "transport")
    ]
    assert transport_users, (
        "expected at least one python/*.py call site to pass transport=... -- "
        "did the wiring change shape?"
    )


def test_no_script_imports_the_data_repo_package() -> None:
    """A ``-raw`` script importing ``nba_data_build`` / ``wnba_data_build`` --
    either league, since the wrong one is just as broken as the sibling's own
    -- reaches into the ``-data`` repo's package. It is not a dependency of
    this repo and cannot resolve here.

    This is the root cause of the twin-audit finding above: a bare
    ``except ImportError: return None`` around exactly this import masked the
    failure as "no proxies configured" instead of "this import cannot work".
    """
    offenders = {
        str(path.relative_to(REPO)): sorted(set(hits))
        for path, source in _all_python_sources().items()
        if (hits := re.findall(r"^\s*(?:from|import)\s+(\w*_data_build)\b", source, re.MULTILINE))
    }
    assert not offenders, f"-raw scripts must not import the -data repo's package: {offenders}"
