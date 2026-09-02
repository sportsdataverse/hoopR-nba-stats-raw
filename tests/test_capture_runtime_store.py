"""The store root every capture stage writes to.

``resolve_store()`` is derived from this file's own location, so it silently
follows a move. It already did: the 2026-09-01 packaging move (903d504b26) took
``_capture_runtime.py`` from ``python/`` down into ``python/nba_stats_raw_scrape/``
and kept ``REPO = Path(__file__).resolve().parent.parent``, which then answered
``<repo>/python`` instead of ``<repo>``.

Nothing raises on that. Capture resume is ``path.exists()``, so a wrong root
makes every payload read as absent: a sweep would re-fetch the whole archive
into ``python/nba_stats/json/`` -- thousands of requests against stats.nba.com
-- while the real store gained nothing and the commit step found nothing to
commit. A wrong path here is expensive and invisible, which is why it is
asserted against the repo layout rather than against a hardcoded string.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from nba_stats_raw_scrape import _capture_runtime as rt

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_repo_root_is_the_repo_not_the_python_dir() -> None:
    assert rt.REPO == REPO_ROOT
    # The tell-tale of the regression: the package dir, not the repo.
    assert rt.REPO.name != "python"


def test_resolve_store_points_at_the_committed_store(monkeypatch) -> None:
    """The default store path is the tracked ``nba_stats/json`` tree.

    ``resolve_store()`` returns ``$SDV_PY_NBA_RAW_JSON_DIR`` when it is set, so
    the override has to be cleared or this asserts against the developer's
    environment instead of against the code under test -- and the bug it exists
    to catch (a wrong derived root, silently triggering a full re-scrape) is
    exactly the one an exported override hides.
    """
    monkeypatch.delenv(rt.STORE_ENV, raising=False)
    assert Path(rt.resolve_store()) == REPO_ROOT / "nba_stats" / "json"


@pytest.mark.archive
def test_the_store_root_actually_exists(monkeypatch) -> None:
    """Path equality alone would still pass if BOTH sides moved together.

    Marked ``archive``: CI checks out code only, so this runs on the runner that
    holds the committed tree.
    """
    monkeypatch.delenv(rt.STORE_ENV, raising=False)
    store = Path(rt.resolve_store())
    assert store.is_dir(), f"{store} is not a directory -- resolve_store() is off the repo"


def test_env_override_still_wins(monkeypatch) -> None:
    """An explicit store root beats the derived one (how a worktree redirects it)."""
    monkeypatch.setenv(rt.STORE_ENV, "D:/elsewhere/json")
    assert rt.resolve_store() == "D:/elsewhere/json"
