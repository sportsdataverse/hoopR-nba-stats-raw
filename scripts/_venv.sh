#!/usr/bin/env bash
# Shared interpreter resolution. Sourced (not executed) by the scrape scripts.
#
# Sets SDV_PY to the python that carries sportsdataverse + curl_cffi. Before
# this repo had its own pyproject.toml, all three callers reached across to the
# SIBLING repo's venv (hoopR-nba-stats-data/python/.venv) -- and because each
# one open-coded that path, they drifted: two hardcoded an absolute
# /mnt/sdv_repos/... with no override, one had a relative path plus an env knob.
# One definition, so the next move updates a single line.
#
# Resolution order: $NBA_VENV_PYTHON -> this repo's .venv (Windows, then POSIX).
# Callers that had their own override name keep it by exporting NBA_VENV_PYTHON
# before sourcing.

_sdv_repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -n "${NBA_VENV_PYTHON:-}" ]; then
  SDV_PY="$NBA_VENV_PYTHON"
elif [ -x "$_sdv_repo/.venv/Scripts/python.exe" ]; then
  SDV_PY="$_sdv_repo/.venv/Scripts/python.exe"      # Windows
else
  SDV_PY="$_sdv_repo/.venv/bin/python"              # POSIX
fi

if [ ! -x "$SDV_PY" ]; then
  echo "FATAL: venv python not found at $SDV_PY" >&2
  echo "       run 'uv sync' in $_sdv_repo, or set NBA_VENV_PYTHON" >&2
  exit 2
fi

# Deliberately NOT `uv run`: that resyncs the venv to the lockfile mid-sweep,
# which can swap sportsdataverse under a running multi-hour scrape.
export SDV_PY
