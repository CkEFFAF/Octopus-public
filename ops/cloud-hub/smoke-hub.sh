#!/usr/bin/env bash
# smoke-hub.sh — 0009 S1 local health check (AC-003).
set -euo pipefail
HOST="${1:-127.0.0.1}"
PORT="${2:-8188}"
URL="http://${HOST}:${PORT}/api/health"
echo "GET ${URL}"
curl -fsS --max-time 10 "${URL}"
echo