"""The May draft combine is filed under NEXT season's END-year key (2027 = the 2026
combine), which the current-season daily never asks for until October. run_pipeline.sh
adds a narrow look-ahead May-Jul; this pins the gate and the key it targets.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _plan(month: str) -> str:
    env = {**os.environ, "DRY_RUN": "1", "PIPELINE_MONTH": month}
    env.pop("COMBINE_LOOKAHEAD_SEASON", None)
    out = subprocess.run(
        ["bash", "scripts/run_pipeline.sh"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout


@pytest.mark.parametrize("month", ["05", "06", "07"])
def test_combine_season_months_look_ahead_one_key(month: str) -> None:
    out = _plan(month)
    seasons = int(out.split("seasons=")[1].split()[0])
    assert f"combine look-ahead: {seasons + 1}" in out


@pytest.mark.parametrize("month", ["01", "04", "08", "10", "12"])
def test_other_months_do_not_look_ahead(month: str) -> None:
    assert "combine look-ahead" not in _plan(month)
