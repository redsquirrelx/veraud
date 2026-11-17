#!/bin/sh
set -u
SUITE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! command -v uv >/dev/null 2>&1; then
  echo "[tallercito] ERROR: 'uv' not found on PATH" >&2
  exit 2
fi
LOCK=""
if [ -f "$SUITE_ROOT/uv.lock" ]; then
  LOCK="--locked"
else
  echo "[tallercito] warning: no resolved uv.lock; dependency resolution is not reproducible" >&2
fi
uv run --project "$SUITE_ROOT" $LOCK python "$SUITE_ROOT/runner.py" "$@"
exit $?
