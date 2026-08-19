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
# Import preflight -- the check that makes the ambient-python fallback safe.
#
# The fallback hands back whatever `python3` is on PATH, which may carry a stale
# or entirely different sportsdataverse. On 2026-08-12 a venv sweep removed the
# .venv from nearly every repo on this box; cron's PATH had no /root/.local/bin,
# so the `uv sync` bootstrap could not fire and resolution fell through to
# /usr/bin/python3 -- Python 3.8 with a years-old dist-packages sportsdataverse.
# wehoop-wnba-raw ran that way, red, every morning for six days before anyone
# noticed. This resolver has always documented that its fallback is safe "ONLY
# because every driver runs an import preflight"; this is that preflight.
#
# Call immediately after sourcing, naming the modules the caller imports. Exits 3
# (distinct from the resolver's 2) so a wrong interpreter is one loud stop.
sdv_preflight() {
  local mods=("$@")
  [ "${#mods[@]}" -eq 0 ] && mods=(sportsdataverse)
  local m out
  for m in "${mods[@]}"; do
    if ! out=$("$SDV_PY" -c "import $m" 2>&1); then
      echo "FATAL: preflight failed -- cannot import '$m'." >&2
      echo "       Interpreter: $SDV_PY" >&2
      echo "$out" | sed 's/^/       /' >&2
      echo "       Fix: run 'uv sync' in $_sdv_repo" >&2
      echo "            (no uv? curl -LsSf https://astral.sh/uv/install.sh | sh)" >&2
      exit 3
    fi
  done
}
