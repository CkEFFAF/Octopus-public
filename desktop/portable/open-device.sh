#!/usr/bin/env bash
# 0006: first-run entry; GUI when DISPLAY is set, else text UU join.
set -euo pipefail
DEVICE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -x "${DEVICE_ROOT}/runtime/bin/python3" ]]; then
  DEVICE_PY="${DEVICE_ROOT}/runtime/bin/python3"
elif [[ -x "${DEVICE_ROOT}/runtime/bin/python" ]]; then
  DEVICE_PY="${DEVICE_ROOT}/runtime/bin/python"
else
  echo "open-device.sh: portable Python is missing beside this launcher." >&2
  exit 1
fi
[[ -f "${DEVICE_ROOT}/launch.py" ]] || { echo "open-device.sh: launch.py is missing." >&2; exit 1; }
export PYTHONNOUSERSITE=1
unset PYTHONPATH || true
exec "$DEVICE_PY" "${DEVICE_ROOT}/launch.py" device first-run --state "${DEVICE_ROOT}/device-state" "$@"
