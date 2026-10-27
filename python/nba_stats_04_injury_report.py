#!/usr/bin/env python
"""Capture the official NBA injury report into the raw store, one JSON per report date.

Source: ``ak-static.cms.nba.com/referee/injury/Injury-Report_{date}_{slot}.pdf`` (static
S3 behind Akamai -- not stats.nba.com, so no proxy). The fetch + parse live in sdv-py
(``sportsdataverse.nba.nba_official_injury``); this stage only decides which slots to
probe and what to keep.

Layout: ``{store}/injury_report/{END_YEAR}/{YYYY-MM-DD}.json``::

    {"date": "2026-01-15", "probed": ["2026-01-15T00:00", ...],   # every slot asked, hit or miss
     "slots": [{"report_time": "...", "url": "...", "rows": [...]}, ...]}

Only a slot whose rows differ from the previous KEPT slot is stored (the report is
re-published every 15 minutes, mostly unchanged), so a season is ~180 small files, not
~17k. ``probed`` makes a re-run skip every slot already asked -- resumable, and a
killed backfill restarts where it stopped. A date's later slots are probed on a later
run (today's future slots are never asked).

    python python/nba_stats_04_injury_report.py                     # yesterday..today (ET)
    python python/nba_stats_04_injury_report.py 2026-01-01:2026-01-31
    python python/nba_stats_04_injury_report.py --check 2018-12-17:2026-06-30   # size it, no fetch

Env: ``INJ_RATE_DELAY`` seconds between requests (default 0.5); the store root follows
the repo's ``resolve_store()``.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nba_stats_raw_scrape._capture_runtime import resolve_store  # noqa: E402


def _now_et() -> dt.datetime:
    return dt.datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)


def end_year(day: dt.date) -> int:
    """END-year season key, rolling forward in October like run_pipeline.sh's
    current_season(). The 2020 bubble ran the 2019-20 Finals to 2020-10-11."""
    if day.month < 10 or (day.year == 2020 and day <= dt.date(2020, 10, 11)):
        return day.year
    return day.year + 1


def _dates(spec: str | None) -> list[dt.date]:
    if not spec:
        today = _now_et().date()
        return [today - dt.timedelta(days=1), today]
    lo, _, hi = spec.partition(":")
    a, b = dt.date.fromisoformat(lo), dt.date.fromisoformat(hi or lo)
    return [a + dt.timedelta(days=i) for i in range((b - a).days + 1)]


def _write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":"), default=str), encoding="utf-8")
    os.replace(tmp, path)


def _rows(df) -> list[dict]:
    return [
        {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()}
        for r in df.iter_rows(named=True)
    ]


def _content(rows: list[dict] | None) -> list[dict] | None:
    """Rows minus the per-slot timestamp, so a re-published report compares equal."""
    return (
        None
        if rows is None
        else [{k: v for k, v in r.items() if k != "report_datetime"} for r in rows]
    )


def capture_date(day: dt.date, store: Path, *, fetch, delay: float, now: dt.datetime) -> dict:
    """Probe every not-yet-asked, already-published slot of ``day``; returns counts."""
    from sportsdataverse.errors import NoDataError
    from sportsdataverse.nba.nba_official_injury import (
        nba_injury_report_slots,
        nba_injury_report_url,
    )

    path = store / "injury_report" / str(end_year(day)) / f"{day.isoformat()}.json"
    doc = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.exists()
        else {"date": day.isoformat(), "probed": [], "slots": []}
    )
    asked = set(doc["probed"])
    counts = {"asked": 0, "kept": 0, "missing": 0}
    try:
        for slot in nba_injury_report_slots(day):
            key = slot.isoformat(timespec="minutes")
            if key in asked or slot > now:
                continue
            try:
                rows = _rows(fetch(slot))
            except NoDataError:
                rows = None
                counts["missing"] += 1
            counts["asked"] += 1
            doc["probed"].append(key)
            last = doc["slots"][-1]["rows"] if doc["slots"] else None
            if rows is not None and _content(rows) != _content(last):
                doc["slots"].append(
                    {"report_time": key, "url": nba_injury_report_url(slot), "rows": rows}
                )
                counts["kept"] += 1
            time.sleep(delay)
    finally:  # a later fetch error keeps the slots already probed; the failed one is not recorded
        if counts["asked"]:
            doc["probed"].sort()
            _write_atomic(path, doc)
    return counts


def _check(days: list[dt.date], store: Path, now: dt.datetime) -> int:
    """Size the work without fetching: slots not yet probed, per the store."""
    from sportsdataverse.nba.nba_official_injury import nba_injury_report_slots

    todo = 0
    for day in days:
        path = store / "injury_report" / str(end_year(day)) / f"{day.isoformat()}.json"
        asked = (
            set(json.loads(path.read_text(encoding="utf-8"))["probed"]) if path.exists() else set()
        )
        todo += sum(
            1
            for s in nba_injury_report_slots(day)
            if s <= now and s.isoformat(timespec="minutes") not in asked
        )
    delay = float(os.environ.get("INJ_RATE_DELAY", "0.5"))
    print(
        f"[check] {len(days)} dates, {todo} slots to probe (~{todo * (delay + 0.3) / 3600:.1f} h at INJ_RATE_DELAY={delay})"
    )
    return 0


def main(argv: list[str]) -> int:
    from sportsdataverse.nba.nba_official_injury import nba_injury_report

    store = Path(resolve_store())
    delay = float(os.environ.get("INJ_RATE_DELAY", "0.5"))
    now = _now_et()
    args = [a for a in argv[1:] if a != "--check"]
    days = _dates(args[0] if args else None)
    if "--check" in argv:
        return _check(days, store, now)
    total = {"asked": 0, "kept": 0, "missing": 0}
    for day in days:
        c = capture_date(
            day,
            store,
            fetch=lambda s: nba_injury_report(report_time=s),
            delay=delay,
            now=now,
        )
        for k in total:
            total[k] += c[k]
        if c["asked"]:
            print(
                f"[{time.strftime('%H:%M:%S')}] {day} asked={c['asked']} kept={c['kept']} missing={c['missing']}",
                flush=True,
            )
    print(f"[{time.strftime('%H:%M:%S')}] done {len(days)} dates {total}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
