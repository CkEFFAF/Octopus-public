#!/usr/bin/env bash
# upgrade-hub.sh — 0027 S0 skeleton: record version → fetch/checkout → frozen sync → reinstall unit → smoke.
# Spec: docs/specs/0027-ops-host-runtime.md
# S1 will harden auto-rollback on health failure; S0 records N=3 and offers --rollback-on-fail.
#
# Does NOT modify OCTOP_HOME data plane (0027 DEC-S08).
# Does NOT hand-edit .venv (0027 DEC-S05); uses uv sync --frozen by default.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=ops/cloud-hub/_hub_common.sh
source "${SCRIPT_DIR}/_hub_common.sh"

REPO_HINT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

USER_NAME="${OCTOP_HUB_USER:-}"
REPO_DIR="${OCTOP_HUB_REPO:-}"
OCTOP_HOME_DIR="${OCTOP_HUB_HOME:-}"
BIND_HOST="${OCTOP_BIND_HOST:-127.0.0.1}"
PORT="${OCTOP_PORT:-8188}"
UV_BIN="${OCTOP_UV_BIN:-}"
REF="${OCTOP_HUB_REF:-origin/main}"
ALLOW_PUBLIC_BIND=0
ALLOW_ROOT=0
ROLLBACK_ON_FAIL=1
DO_BUILD_DASHBOARD=0
SKIP_INSTALL=0

usage() {
  cat <<'EOFUSAGE'
Usage: upgrade-hub.sh [options]

Options:
  --user NAME            Service account (same rules as install-hub)
  --repo DIR             Repo WorkingDirectory
  --home DIR             OCTOP_HOME (passed through to install; never wiped)
  --host ADDR            OCTOP_BIND_HOST (default: 127.0.0.1)
  --port N               OCTOP_PORT (default: 8188)
  --ref REF              git ref to checkout after fetch (default: origin/main)
  --uv PATH              Path to uv binary
  --allow-public-bind    Permit non-loopback bind
  --allow-root           Permit User=root (bootstrap-only)
  --no-rollback-on-fail  Do not call rollback-hub.sh if smoke fails (S0 default: rollback)
  --build-dashboard      Rebuild dashboard after sync
  --skip-install         Only git+sync; do not rewrite systemd unit
  -h, --help             Show this help

Example:
  sudo ./ops/cloud-hub/upgrade-hub.sh --user octop --repo /home/octop/octopus --ref origin/main
EOFUSAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user) USER_NAME="$2"; shift 2 ;;
    --repo) REPO_DIR="$2"; shift 2 ;;
    --home) OCTOP_HOME_DIR="$2"; shift 2 ;;
    --host) BIND_HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --ref) REF="$2"; shift 2 ;;
    --uv) UV_BIN="$2"; shift 2 ;;
    --allow-public-bind) ALLOW_PUBLIC_BIND=1; shift ;;
    --allow-root) ALLOW_ROOT=1; shift ;;
    --no-rollback-on-fail) ROLLBACK_ON_FAIL=0; shift ;;
    --build-dashboard) DO_BUILD_DASHBOARD=1; shift ;;
    --skip-install) SKIP_INSTALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

hub_require_root

if [[ -z "${USER_NAME}" ]]; then
  USER_NAME="$(hub_pick_default_user)"
fi
hub_validate_service_user "${USER_NAME}" "${ALLOW_ROOT}"
hub_validate_bind_host "${BIND_HOST}" "${ALLOW_PUBLIC_BIND}"

if [[ -z "${REPO_DIR}" ]]; then
  REPO_DIR="${REPO_HINT}"
fi
REPO_DIR="$(cd "${REPO_DIR}" && pwd)"

if [[ -z "${OCTOP_HOME_DIR}" ]]; then
  OCTOP_HOME_DIR="$(hub_default_octop_home "${USER_NAME}")"
fi

ACCOUNT_HOME="$(hub_account_home "${USER_NAME}")"
UV_BIN="$(hub_resolve_uv "${ACCOUNT_HOME}" "${UV_BIN}")"

echo "==> recording pre-upgrade version"
hub_record_version "${REPO_DIR}" "pre-upgrade"

PREV_SHA="$(git -C "${REPO_DIR}" rev-parse HEAD)"

echo "==> git fetch + checkout ${REF}"
git -C "${REPO_DIR}" fetch --prune --tags origin
git -C "${REPO_DIR}" checkout --detach "${REF}"

echo "==> uv sync --frozen (0027 DEC-S05; do not hand-edit .venv)"
(cd "${REPO_DIR}" && "${UV_BIN}" sync --frozen)

if [[ "${DO_BUILD_DASHBOARD}" -eq 1 ]]; then
  echo "==> build dashboard"
  (cd "${REPO_DIR}/dashboard" && npm ci && npm run build)
fi

if [[ "${SKIP_INSTALL}" -eq 0 ]]; then
  INSTALL_ARGS=(
    --user "${USER_NAME}"
    --repo "${REPO_DIR}"
    --home "${OCTOP_HOME_DIR}"
    --host "${BIND_HOST}"
    --port "${PORT}"
    --uv "${UV_BIN}"
  )
  if [[ "${ALLOW_PUBLIC_BIND}" -eq 1 ]]; then
    INSTALL_ARGS+=(--allow-public-bind)
  fi
  if [[ "${ALLOW_ROOT}" -eq 1 ]]; then
    INSTALL_ARGS+=(--allow-root)
  fi
  echo "==> reinstall unit + 90-octop drop-in (clears stale 50-*)"
  "${SCRIPT_DIR}/install-hub.sh" "${INSTALL_ARGS[@]}"
else
  systemctl restart "${HUB_UNIT_NAME}" || true
fi

echo "==> smoke health"
if hub_smoke "127.0.0.1" "${PORT}"; then
  echo "==> upgrade OK; recording post-upgrade version"
  hub_record_version "${REPO_DIR}" "post-upgrade"
  exit 0
fi

echo "ERROR: health check failed after upgrade" >&2
if [[ "${ROLLBACK_ON_FAIL}" -eq 1 ]]; then
  echo "==> invoking rollback-hub.sh to ${PREV_SHA} (S0 skeleton; S1 hardens AC-S03)" >&2
  RB_ARGS=(
    --user "${USER_NAME}"
    --repo "${REPO_DIR}"
    --home "${OCTOP_HOME_DIR}"
    --host "${BIND_HOST}"
    --port "${PORT}"
    --uv "${UV_BIN}"
    --sha "${PREV_SHA}"
  )
  if [[ "${ALLOW_PUBLIC_BIND}" -eq 1 ]]; then
    RB_ARGS+=(--allow-public-bind)
  fi
  if [[ "${ALLOW_ROOT}" -eq 1 ]]; then
    RB_ARGS+=(--allow-root)
  fi
  "${SCRIPT_DIR}/rollback-hub.sh" "${RB_ARGS[@]}"
  exit 1
fi
exit 1
