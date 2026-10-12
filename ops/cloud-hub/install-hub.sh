#!/usr/bin/env bash
# install-hub.sh — 0009 S1+S2: optional uv sync, write systemd unit, enable hub.
# Spec: docs/specs/0009-cloud-hub-production.md (Accepted 2026-10-12.2+)
# Ops:  docs/octopus/cloud-hub-ops.md
#
# Defaults: topology B (0.0.0.0:8188), OCTOP_HOME=~/OctopData, system unit octop-hub.
# Does NOT clone with Deploy Key; does NOT write secrets into the unit or git.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_HINT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

USER_NAME="${OCTOP_HUB_USER:-}"
REPO_DIR="${OCTOP_HUB_REPO:-}"
OCTOP_HOME_DIR="${OCTOP_HUB_HOME:-}"
BIND_HOST="${OCTOP_BIND_HOST:-0.0.0.0}"
PORT="${OCTOP_PORT:-8188}"
UV_BIN="${OCTOP_UV_BIN:-}"
DO_SYNC=0
DO_BUILD_DASHBOARD=0
SKIP_ENABLE=0
UNIT_NAME="octop-hub.service"
SYSTEMD_PATH="/etc/systemd/system/${UNIT_NAME}"

usage() {
  cat <<'EOF'
Usage: install-hub.sh [options]

Options:
  --user NAME          Service account (default: sudo user or root)
  --repo DIR           Repo WorkingDirectory (default: repo containing this script)
  --home DIR           OCTOP_HOME data dir (default: ~NAME/OctopData)
  --host ADDR          OCTOP_BIND_HOST (default: 0.0.0.0)
  --port N             OCTOP_PORT (default: 8188)
  --uv PATH            Path to uv binary
  --sync               Run uv sync in --repo before install
  --build-dashboard    Also npm ci && npm run build under dashboard/
  --skip-enable        Write unit + daemon-reload only
  -h, --help           Show this help

Cloud root example:
  sudo ./ops/cloud-hub/install-hub.sh --user root --repo /root/octopus --home /root/OctopData --sync

Ubuntu example:
  sudo ./ops/cloud-hub/install-hub.sh --user ubuntu --repo /home/ubuntu/octopus --home /home/ubuntu/OctopData --sync
EOF
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
    --build-dashboard) DO_BUILD_DASHBOARD=1; shift ;;
    --skip-enable) SKIP_ENABLE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$(id -u)" -ne 0 ]]; then
  echo "install-hub.sh must run as root (systemd system unit)." >&2
  exit 1
fi

if [[ -z "${USER_NAME}" ]]; then
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    USER_NAME="${SUDO_USER}"
  else
    USER_NAME="root"
  fi
fi

if [[ -z "${REPO_DIR}" ]]; then
  REPO_DIR="${REPO_HINT}"
fi
REPO_DIR="$(cd "${REPO_DIR}" && pwd)"

if [[ -z "${OCTOP_HOME_DIR}" ]]; then
  if [[ "${USER_NAME}" == "root" ]]; then
    OCTOP_HOME_DIR="/root/OctopData"
  else
    OCTOP_HOME_DIR="/home/${USER_NAME}/OctopData"
  fi
fi

if [[ "${USER_NAME}" == "root" ]]; then
  ACCOUNT_HOME="/root"
  USER_LINE=""
else
  ACCOUNT_HOME="/home/${USER_NAME}"
  USER_LINE="User=${USER_NAME}"$'\n'
fi

if [[ -z "${UV_BIN}" ]]; then
  if [[ -x "${ACCOUNT_HOME}/.local/bin/uv" ]]; then
    UV_BIN="${ACCOUNT_HOME}/.local/bin/uv"
  elif command -v uv >/dev/null 2>&1; then
    UV_BIN="$(command -v uv)"
  else
    echo "uv not found; install uv or pass --uv /path/to/uv" >&2
    exit 1
  fi
fi
UV_DIR="$(dirname "${UV_BIN}")"

TEMPLATE="${SCRIPT_DIR}/octop-hub.service.in"
if [[ ! -f "${TEMPLATE}" ]]; then
  echo "missing template: ${TEMPLATE}" >&2
  exit 1
fi

mkdir -p "${OCTOP_HOME_DIR}"
if [[ "${USER_NAME}" != "root" ]]; then
  chown -R "${USER_NAME}:${USER_NAME}" "${OCTOP_HOME_DIR}" || true
fi

if [[ "${DO_SYNC}" -eq 1 ]]; then
  echo "==> uv sync in ${REPO_DIR}"
  (cd "${REPO_DIR}" && "${UV_BIN}" sync)
fi

if [[ "${DO_BUILD_DASHBOARD}" -eq 1 ]]; then
  echo "==> build dashboard"
  (cd "${REPO_DIR}/dashboard" && npm ci && npm run build)
fi

tmp="$(mktemp)"
export HUB_USER_LINE="${USER_LINE}"
export HUB_REPO_DIR="${REPO_DIR}"
export HUB_ACCOUNT_HOME="${ACCOUNT_HOME}"
export HUB_OCTOP_HOME="${OCTOP_HOME_DIR}"
export HUB_UV_BIN="${UV_BIN}"
export HUB_UV_DIR="${UV_DIR}"
export HUB_BIND_HOST="${BIND_HOST}"
export HUB_PORT="${PORT}"
python3 - "${TEMPLATE}" "${tmp}" <<'PY'
import os
import pathlib
import sys

template = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])
repl = {
    "@USER_LINE@": os.environ.get("HUB_USER_LINE", ""),
    "@REPO_DIR@": os.environ["HUB_REPO_DIR"],
    "@ACCOUNT_HOME@": os.environ["HUB_ACCOUNT_HOME"],
    "@OCTOP_HOME@": os.environ["HUB_OCTOP_HOME"],
    "@UV_BIN@": os.environ["HUB_UV_BIN"],
    "@UV_DIR@": os.environ["HUB_UV_DIR"],
    "@BIND_HOST@": os.environ["HUB_BIND_HOST"],
    "@PORT@": os.environ["HUB_PORT"],
}
text = template.read_text(encoding="utf-8")
for key, value in repl.items():
    text = text.replace(key, value)
out.write_text(text, encoding="utf-8")
PY

install -m 0644 "${tmp}" "${SYSTEMD_PATH}"
rm -f "${tmp}"

echo "==> wrote ${SYSTEMD_PATH}"
systemctl daemon-reload

if [[ "${SKIP_ENABLE}" -eq 1 ]]; then
  echo "skip enable; run: systemctl enable --now ${UNIT_NAME}"
  exit 0
fi

systemctl enable --now "${UNIT_NAME}"
systemctl status "${UNIT_NAME}" --no-pager || true
echo "==> smoke: curl -sS http://127.0.0.1:${PORT}/api/health"