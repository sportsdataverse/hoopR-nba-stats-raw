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
   ``period_capture.py`` / ``schedule_master.py`` / ``scrape_raw_json.py``)
   and the ``NBA``/``WNBA`` config object ``refill_empty.py`` imports must
   bind the league this repo actually is. A copy-paste from the sibling that
   forgot to flip one of these would silently scrape/report the wrong league,
   or crash on the first real (non-``--check``) run -- exactly the
   ``sportsdataverse.nba.wnba_stats`` incident ``league_config.py`` documents
   in its ``WNBA`` entry.

2. **Transport wiring.** ``scrape_raw_json.py``'s own module docstring states
   the contract: ``SessionTransport`` "owns proxy selection ... so the fetch
   closures pass no proxy_url" -- every live fetch call must route through
   ``transport=session_transport``, never a raw ``proxy_url=rr.next()`` that
   bypasses health recording and the sticky JA3 session. A real regression of
   exactly this kind (one leftover pre-migration call site, in the per-period
   boxscore closure) shipped in one twin and not the other; this guards it in
   both going forward.
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
    assert literals, 'no `LEAGUE_ID = "..."` literal found under python/ -- did the binding pattern move?'


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


def test_refill_empty_binds_the_right_league_config() -> None:
    """``refill_empty.py`` imports NBA/WNBA by name and passes it to ``main()``
    -- the exact shape of the caught incident (importing a module that does
    not exist for this league)."""
    expected = _expected_league()
    source = (PYTHON / "refill_empty.py").read_text(encoding="utf-8")
    imported = re.findall(r"from sportsdataverse\.scrape\.stats\.league_config import (\w+)", source)
    assert imported, "refill_empty.py must import its LeagueConfig from league_config"
    assert imported == [expected.key.upper()], (
        f"refill_empty.py imports {imported}, expected [{expected.key.upper()!r}]"
    )
    assert re.search(rf"main\({expected.key.upper()}\b", source), (
        f"refill_empty.py must call main({expected.key.upper()}, ...)"
    )


def _proxy_url_call_sites(source: str) -> list[int]:
    """Line numbers of any ``proxy_url=`` keyword argument in a call."""
    tree = ast.parse(source)
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "proxy_url"
    ]


def test_scraper_never_bypasses_the_session_transport() -> None:
    """SessionTransport's whole point is to own proxy selection + health
    recording; a stray ``proxy_url=`` call site skips both silently (the
    request still succeeds, it just isn't tracked or session-reused).

    This is the regression guard for the twin-audit finding: one closure in
    this file still called ``proxy_url=rr.next()`` after the rest of the file
    had moved to ``transport=session_transport``.
    """
    source = (PYTHON / "scrape_raw_json.py").read_text(encoding="utf-8")
    sites = _proxy_url_call_sites(source)
    assert not sites, (
        f"scrape_raw_json.py passes proxy_url= directly at line(s) {sites} -- use transport=session_transport instead"
    )
    assert "transport=session_transport" in source, (
        "expected at least one transport=session_transport call site -- did the wiring change shape?"
    )
