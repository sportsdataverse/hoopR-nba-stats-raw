"""Offline tests for the official-injury-report stage (python/nba_stats_04_injury_report.py).

``fetch`` is injected, so nothing here touches ak-static.cms.nba.com.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path

import polars as pl
import pytest
from sportsdataverse.errors import NoDataError

_SPEC = importlib.util.spec_from_file_location(
    "inj", Path(__file__).resolve().parent.parent / "python" / "nba_stats_04_injury_report.py"
)
inj = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(inj)

DAY = dt.date(2026, 1, 15)  # quarter-hourly era: 96 slots


def _frame(status: str, at: dt.datetime = dt.datetime(2026, 1, 15, 17, 30)) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "report_datetime": [at],  # differs per slot, like the real parser
            "game_date": [DAY],
            "team": ["Memphis Grizzlies"],
            "player_name": ["Clarke, Brandon"],
            "current_status": [status],
        }  # fmt: skip
    )


def _fetcher(published: dict):
    calls: list = []

    def fetch(slot: dt.datetime) -> pl.DataFrame:
        calls.append(slot)
        if slot not in published:
            raise NoDataError(str(slot))
        return published[slot]

    return fetch, calls


def test_keeps_only_changed_slots_and_records_every_probe(tmp_path: Path) -> None:
    t = dt.datetime.combine(DAY, dt.time())
    slots = (t.replace(hour=12), t.replace(hour=13), t.replace(hour=17, minute=30))
    published = {
        s: _frame(st, at=s) for s, st in zip(slots, ("Questionable", "Questionable", "Out"))
    }
    fetch, calls = _fetcher(published)
    c = inj.capture_date(DAY, tmp_path, fetch=fetch, delay=0, now=t.replace(hour=18))
    doc = json.loads((tmp_path / "injury_report" / "2026" / "2026-01-15.json").read_text())
    assert c == {
        "asked": 73,
        "kept": 2,
        "missing": 70,
    }  # 00:00..18:00 every 15 min; 3 published, 2 distinct
    assert [s["report_time"] for s in doc["slots"]] == ["2026-01-15T12:00", "2026-01-15T17:30"]
    assert doc["slots"][1]["rows"][0]["current_status"] == "Out" and len(doc["probed"]) == 73


def test_rerun_asks_only_new_slots(tmp_path: Path) -> None:
    t = dt.datetime.combine(DAY, dt.time())
    fetch, calls = _fetcher({t.replace(hour=12): _frame("Out")})
    inj.capture_date(DAY, tmp_path, fetch=fetch, delay=0, now=t.replace(hour=12))
    calls.clear()
    c = inj.capture_date(DAY, tmp_path, fetch=fetch, delay=0, now=t.replace(hour=13))
    assert calls == [t.replace(hour=12, minute=m) for m in (15, 30, 45)] + [t.replace(hour=13)]
    assert c["kept"] == 0  # nothing new published, the 12:00 slot is not re-asked


def test_future_slots_are_never_asked_and_nothing_is_written_when_idle(tmp_path: Path) -> None:
    fetch, calls = _fetcher({})
    c = inj.capture_date(DAY, tmp_path, fetch=fetch, delay=0, now=dt.datetime(2026, 1, 14, 23))
    assert c["asked"] == 0 and not calls and not (tmp_path / "injury_report").exists()


@pytest.mark.parametrize(
    ("day", "season"),
    [
        (dt.date(2025, 12, 1), 2026),
        (dt.date(2026, 4, 1), 2026),
        (dt.date(2026, 9, 15), 2026),  # rolls forward in October, like run_pipeline.sh
        (dt.date(2026, 10, 25), 2027),
        (dt.date(2020, 8, 15), 2020),  # bubble restart
        (dt.date(2020, 10, 11), 2020),  # bubble Finals game 6
        (dt.date(2020, 12, 22), 2021),
    ],
)
def test_season_key_is_the_end_year(day: dt.date, season: int) -> None:
    assert inj.end_year(day) == season


def test_a_failed_fetch_is_not_recorded_as_probed(tmp_path: Path) -> None:
    """Only a NoDataError (S3 403 AccessDenied) is a miss; any other error must abort
    without marking the slot probed, or a re-run would never retry it."""
    from sportsdataverse.errors import AssetFetchError

    def boom(slot: dt.datetime) -> pl.DataFrame:
        raise AssetFetchError("CDN block")

    with pytest.raises(AssetFetchError):
        inj.capture_date(DAY, tmp_path, fetch=boom, delay=0, now=dt.datetime(2026, 1, 15, 0, 30))
    assert not (tmp_path / "injury_report").exists()


def test_a_failed_injury_stage_does_not_stop_the_daily_chain() -> None:
    """Stage 15 is advisory: its failure must not cost the day's stats capture."""
    import os
    import shutil
    import subprocess

    repo = Path(__file__).resolve().parent.parent
    env = {**os.environ, "NBA_VENV_PYTHON": shutil.which("false") or "/bin/false"}
    out = subprocess.run(
        ["bash", "scripts/run_pipeline.sh", "-m", "daily", "-k", "15"],
        cwd=repo, env=env, capture_output=True, text=True,
    )  # fmt: skip
    assert "15_injury_report.sh failed" in out.stdout and "advisory, continuing" in out.stdout
    assert out.returncode == 0


def test_a_later_fetch_error_keeps_the_slots_already_probed(tmp_path: Path) -> None:
    from sportsdataverse.errors import AssetFetchError

    t = dt.datetime.combine(DAY, dt.time())

    def flaky(slot: dt.datetime) -> pl.DataFrame:
        if slot >= t.replace(hour=0, minute=30):
            raise AssetFetchError("CDN block")
        raise NoDataError(str(slot))

    with pytest.raises(AssetFetchError):
        inj.capture_date(DAY, tmp_path, fetch=flaky, delay=0, now=t.replace(hour=1))
    doc = json.loads((tmp_path / "injury_report" / "2026" / "2026-01-15.json").read_text())
    assert doc["probed"] == ["2026-01-15T00:00", "2026-01-15T00:15"]  # 00:30 failed: not recorded
