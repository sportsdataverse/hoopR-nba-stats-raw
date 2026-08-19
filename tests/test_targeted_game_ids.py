"""`--game-ids=FILE` mode: capture a named list instead of a season sweep.

Why the mode exists: game discovery reads ``leaguegamelog``, which indexes
regular season + playoffs ONLY. Preseason (``001``), All-Star (``003``),
play-in (``005``) and NBA Cup final (``006``) games are invisible to the season
sweep no matter how many times it is rerun, so they have to be named.

These run the real CLI in a subprocess with NO proxy credentials, so
``load_proxies()`` returns an empty pool and the process exits 1 *before* any
network call. That exit code is the assertion: reaching the no-proxy guard
proves arg parsing, the ids-file read, and season derivation all succeeded.
Exit 2 is the usage error, i.e. the flag was not understood.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRAPER = REPO / "python" / "nba_stats_02_game_endpoints.py"

# Inherit the real environment (HOME / SYSTEMROOT / ssl certs are all needed) and
# blank ONLY the proxy creds, so load_proxies() returns an empty pool and the
# process exits at the guard instead of making a request.
NO_PROXY_ENV = {
    **os.environ,
    "PROXY_ENDPOINT": "",
    "PROXY_KEY": "",
    "PROXY_PKG": "",
    "PYTHONPATH": str(REPO / "python"),
}


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRAPER), *args],
        capture_output=True,
        text=True,
        timeout=180,
        env=NO_PROXY_ENV,
        cwd=str(REPO),
    )


def test_game_ids_file_is_accepted_without_a_season_argument(tmp_path: Path) -> None:
    """A season range is normally required; --game-ids supplies the universe instead."""
    ids = tmp_path / "ids.txt"
    ids.write_text("0012300001\n0032300001\n", encoding="utf-8")

    r = _run(f"--game-ids={ids}")

    assert r.returncode == 1, (
        f"expected the no-proxy guard (1), got {r.returncode}: {r.stderr[-400:]}"
    )
    assert "targeted mode: 2 game ids" in r.stdout, r.stdout[-600:]


def test_ids_are_grouped_into_the_season_the_id_encodes(tmp_path: Path) -> None:
    """0012300001 -> 2023-24 -> END year 2024; 0010000001 -> 2000-01 -> 2001."""
    ids = tmp_path / "ids.txt"
    ids.write_text("0012300001\n0010000001\n", encoding="utf-8")

    r = _run(f"--game-ids={ids}")

    assert "over 2 seasons (2001..2024)" in r.stdout, r.stdout[-600:]


def test_blank_lines_do_not_become_game_ids(tmp_path: Path) -> None:
    ids = tmp_path / "ids.txt"
    ids.write_text("0012300001\n\n  \n0012300002\n", encoding="utf-8")

    r = _run(f"--game-ids={ids}")

    assert "targeted mode: 2 game ids" in r.stdout, r.stdout[-600:]


def test_an_all_blank_ids_file_is_a_usage_error_not_a_traceback(tmp_path: Path) -> None:
    """No ids means no work; it used to reach the summary log and die on seasons[0]."""
    ids = tmp_path / "ids.txt"
    ids.write_text("\n  \n\n", encoding="utf-8")

    r = _run(f"--game-ids={ids}")

    assert r.returncode == 2, f"expected the usage error (2), got {r.returncode}"
    assert "IndexError" not in r.stderr, r.stderr[-600:]


def test_a_bare_season_range_still_works(tmp_path: Path) -> None:
    """The season sweep must be untouched by the new flag."""
    r = _run("2024")

    assert r.returncode == 1, f"expected the no-proxy guard (1), got {r.returncode}"
    assert "1 seasons" in r.stdout, r.stdout[-600:]


def test_no_arguments_at_all_is_still_a_usage_error() -> None:
    assert _run().returncode == 2
