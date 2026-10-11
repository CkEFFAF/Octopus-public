#!/usr/bin/env bash
# Copy beside launch.py and runtime/ in the portable package.
# First launch guides enrollment; later launches reuse saved identity.
set -euo pipefail
DEVICE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -x "${DEVICE_ROOT}/runtime/bin/python3" ]]; then
  DEVICE_PY="${DEVICE_ROOT}/runtime/bin/python3"
elif [[ -x "${DEVICE_ROOT}/runtime/bin/python" ]]; then
  DEVICE_PY="${DEVICE_ROOT}/runtime/bin/python"
else
  echo "start-device.sh: portable Python is missing beside this launcher." >&2
  exit 1
fi
[[ -f "${DEVICE_ROOT}/launch.py" ]] || { echo "start-device.sh: launch.py is missing." >&2; exit 1; }
export PYTHONNOUSERSITE=1
unset PYTHONPATH || true
if [[ $# -eq 0 ]]; then
  exec "$DEVICE_PY" "${DEVICE_ROOT}/launch.py" device join --state "${DEVICE_ROOT}/device-state"
fi
exec "$DEVICE_PY" "${DEVICE_ROOT}/launch.py" device connect --state "${DEVICE_ROOT}/device-state" "$@"
