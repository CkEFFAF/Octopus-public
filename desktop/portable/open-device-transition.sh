#!/usr/bin/env bash
# 0010 transition wrapper: filing-period hub via OCTOP_DEVICE_SERVER.
# Product DEFAULT stays https://octop.effaf.me — do not hardcode IP into package constants.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export OCTOP_DEVICE_SERVER="http://111.228.42.228:8188"
exec "${ROOT}/open-device.sh" "$@"
