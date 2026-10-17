#!/usr/bin/env bash
# install-hub.sh — 0027 S0 / 0009: write systemd unit + 90-octop drop-in, enable hub.
# Spec: docs/specs/0027-ops-host-runtime.md (Ready 2026-10-17.1)
# Ops:  docs/octopus/cloud-hub-ops.md
#
# Production defaults (0027):
#   OCTOP_BIND_HOST=127.0.0.1   (public bind requires --allow-public-bind)
#   User=octop|ubuntu (non-root); root requires --allow-root (bootstrap-only)
#   Truth source: octop-hub.service + octop-hub.service.d/90-octop.conf
# Does NOT clone with Deploy Key; does NOT write secrets into the unit or git.

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
DO_SYNC=0
DO_FROZEN=0
DO_BUILD_DASHBOARD=0
SKIP_ENABLE=0
ALLOW_PUBLIC_BIND=0
ALLOW_ROOT=0

usage() {
  cat <<'EOFUSAGE'
Usage: install-hub.sh [options]

Options:
  --user NAME            Service account (default: octop, else ubuntu, else SUDO_USER)
  --repo DIR             Repo WorkingDirectory (default: repo containing this script)
  --home DIR             OCTOP_HOME data dir (default: ~NAME/OctopData)
  --host ADDR            OCTOP_BIND_HOST (default: 127.0.0.1)
  --port N               OCTOP_PORT (default: 8188)
  --uv PATH              Path to uv binary
  --sync                 Run uv sync in --repo before install
  --frozen               With --sync: uv sync --frozen (preferred for production)
  --build-dashboard      Also npm ci && npm run build under dashboard/
  --allow-public-bind    Permit non-loopback bind (e.g. 0.0.0.0); prints warning
  --allow-root           Permit User=root (bootstrap-only; migrate to octop)
  --skip-enable          Write unit + drop-in + daemon-reload only
  -h, --help             Show this help

Production (topology A / 0027):
  sudo ./ops/cloud-hub/install-hub.sh \
    --user octop \
    --repo /home/octop/octopus \
    --home /home/octop/OctopData \
    --sync --frozen

Bootstrap-only root (discouraged):
  sudo ./ops/cloud-hub/install-hub.sh --user root --allow-root \
    --repo /root/octopus --home /root/OctopData --sync --frozen
EOFUSAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user) USER_NAME="$2"; shift 2 ;;
    --repo) REPO_DIR="$2"; shift 2 ;;
    --home) OCTOP_HOME_DIR="$2"; shift 2 ;;
    --host) BIND_HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --uv) UV_BIN="$2"; shift 2 ;;
    --sync) DO_SYNC=1; shift ;;
    --frozen) DO_FROZEN=1; shift ;;
    --build-dashboard) DO_BUILD_DASHBOARD=1; shift ;;
    --allow-public-bind) ALLOW_PUBLIC_BIND=1; shift ;;
    --allow-root) ALLOW_ROOT=1; shift ;;
    --skip-enable) SKIP_ENABLE=1; shift ;;
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
if [[ "${USER_NAME}" == "root" ]]; then
  USER_LINE=""
  GROUP_LINE=""
else
  USER_LINE="User=${USER_NAME}"$'\n'
  GROUP_LINE="Group=${USER_NAME}"$'\n'
fi

UV_BIN="$(hub_resolve_uv "${ACCOUNT_HOME}" "${UV_BIN}")"
UV_DIR="$(dirname "${UV_BIN}")"

UNIT_TEMPLATE="${SCRIPT_DIR}/octop-hub.service.in"
DROPIN_TEMPLATE="${SCRIPT_DIR}/90-octop.conf.in"
if [[ ! -f "${UNIT_TEMPLATE}" ]]; then
  echo "missing template: ${UNIT_TEMPLATE}" >&2
  exit 1
fi
if [[ ! -f "${DROPIN_TEMPLATE}" ]]; then
  echo "missing template: ${DROPIN_TEMPLATE}" >&2
  exit 1
fi

mkdir -p "${OCTOP_HOME_DIR}"
if [[ "${USER_NAME}" != "root" ]]; then
  chown -R "${USER_NAME}:${USER_NAME}" "${OCTOP_HOME_DIR}" || true
fi

if [[ "${DO_SYNC}" -eq 1 ]]; then
  if [[ "${DO_FROZEN}" -eq 1 ]]; then
    echo "==> uv sync --frozen in ${REPO_DIR}"
    (cd "${REPO_DIR}" && "${UV_BIN}" sync --frozen)
  else
    echo "==> uv sync in ${REPO_DIR} (prefer --frozen in production; 0027 DEC-S05)"
    (cd "${REPO_DIR}" && "${UV_BIN}" sync)
  fi
fi

if [[ "${DO_BUILD_DASHBOARD}" -eq 1 ]]; then
  echo "==> build dashboard"
  (cd "${REPO_DIR}/dashboard" && npm ci && npm run build)
fi

export HUB_USER_LINE="${USER_LINE}"
export HUB_GROUP_LINE="${GROUP_LINE}"
export HUB_REPO_DIR="${REPO_DIR}"
export HUB_ACCOUNT_HOME="${ACCOUNT_HOME}"
export HUB_OCTOP_HOME="${OCTOP_HOME_DIR}"
export HUB_UV_BIN="${UV_BIN}"
export HUB_UV_DIR="${UV_DIR}"
export HUB_BIND_HOST="${BIND_HOST}"
export HUB_PORT="${PORT}"

tmp_unit="$(mktemp)"
tmp_dropin="$(mktemp)"
hub_render_unit "${UNIT_TEMPLATE}" "${tmp_unit}"
hub_render_unit "${DROPIN_TEMPLATE}" "${tmp_dropin}"

install -m 0644 "${tmp_unit}" "${HUB_UNIT_PATH}"
mkdir -p "${HUB_DROPIN_DIR}"
# Archive stale drop-ins (50-*, etc.) before installing authoritative 90-octop.conf
ARCHIVE_ROOT="$(hub_versions_dir "${REPO_DIR}")"
hub_archive_stale_dropins "${HUB_DROPIN_DIR}" "${ARCHIVE_ROOT}"
install -m 0644 "${tmp_dropin}" "${HUB_DROPIN_PATH}"
rm -f "${tmp_unit}" "${tmp_dropin}"

echo "==> wrote ${HUB_UNIT_PATH}"
echo "==> wrote ${HUB_DROPIN_PATH} (sole ExecStart override drop-in)"
systemctl daemon-reload

if [[ "${SKIP_ENABLE}" -eq 1 ]]; then
  echo "skip enable; run: systemctl enable --now ${HUB_UNIT_NAME}"
  exit 0
fi

systemctl enable --now "${HUB_UNIT_NAME}"
systemctl status "${HUB_UNIT_NAME}" --no-pager || true
echo "==> smoke: curl -sS http://127.0.0.1:${PORT}/api/health"
