#!/usr/bin/env bash
# rollback-hub.sh — 0027 S0 skeleton: checkout previous git SHA + frozen sync + reinstall unit.
# Spec: docs/specs/0027-ops-host-runtime.md
# Does NOT wipe OCTOP_HOME. Prefer recorded .octop-hub-versions/*.json when --sha omitted.

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
TARGET_SHA=""
ALLOW_PUBLIC_BIND=0
ALLOW_ROOT=0

usage() {
  cat <<'EOFUSAGE'
Usage: rollback-hub.sh [options]

Options:
  --user NAME            Service account
  --repo DIR             Repo WorkingDirectory
  --home DIR             OCTOP_HOME (unchanged)
  --host ADDR            OCTOP_BIND_HOST (default: 127.0.0.1)
  --port N               OCTOP_PORT
  --sha SHA              git commit to restore (default: latest pre-upgrade record)
  --uv PATH              Path to uv binary
  --allow-public-bind    Permit non-loopback bind
  --allow-root           Permit User=root
  -h, --help             Show this help
EOFUSAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user) USER_NAME="$2"; shift 2 ;;
    --repo) REPO_DIR="$2"; shift 2 ;;
    --home) OCTOP_HOME_DIR="$2"; shift 2 ;;
    --host) BIND_HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --sha) TARGET_SHA="$2"; shift 2 ;;
    --uv) UV_BIN="$2"; shift 2 ;;
    --allow-public-bind) ALLOW_PUBLIC_BIND=1; shift ;;
    --allow-root) ALLOW_ROOT=1; shift ;;
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

if [[ -z "${TARGET_SHA}" ]]; then
  meta="$(hub_latest_version_meta "${REPO_DIR}")"
  if [[ -z "${meta}" ]]; then
    echo "no version records under $(hub_versions_dir "${REPO_DIR}"); pass --sha" >&2
    exit 1
  fi
  TARGET_SHA="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["git_sha"])' "${meta}")"
  echo "==> using recorded ${meta} -> ${TARGET_SHA}"
fi

echo "==> checkout ${TARGET_SHA}"
git -C "${REPO_DIR}" fetch --prune --tags origin || true
git -C "${REPO_DIR}" checkout --detach "${TARGET_SHA}"

echo "==> uv sync --frozen"
(cd "${REPO_DIR}" && "${UV_BIN}" sync --frozen)

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

echo "==> reinstall unit + 90-octop drop-in"
"${SCRIPT_DIR}/install-hub.sh" "${INSTALL_ARGS[@]}"

echo "==> smoke health"
hub_smoke "127.0.0.1" "${PORT}"
echo "==> rollback OK"
hub_record_version "${REPO_DIR}" "post-rollback"
