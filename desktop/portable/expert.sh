#!/usr/bin/env bash
set -euo pipefail
EXPERT_ROOT="$(cd "$(dirname "$0")" && pwd)"
EXPERT_PY="$EXPERT_ROOT/runtime/bin/python3"
[[ -x "$EXPERT_PY" ]] || EXPERT_PY="$EXPERT_ROOT/runtime/bin/python"
export PYTHONNOUSERSITE=1 PYTHONUTF8=1
unset PYTHONPATH || true
exec "$EXPERT_PY" "$EXPERT_ROOT/launch.py" device expert --state "$EXPERT_ROOT/device-state" "$@"
