#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${ROOT}/runtime/bin/python3"
[[ -x "$PY" ]] || PY="${ROOT}/runtime/bin/python"
export PYTHONNOUSERSITE=1
unset PYTHONPATH || true
if [[ $# -eq 0 ]]; then
  exec "$PY" "${ROOT}/launch.py" device setup --state "${ROOT}/device-state"
fi
exec "$PY" "${ROOT}/launch.py" device "$@" --state "${ROOT}/device-state"
