#!/usr/bin/env bash
# Shared helpers for install/upgrade/rollback (0027 S0).
# Sourced by other scripts; not invoked directly.

# shellcheck disable=SC2034

HUB_UNIT_NAME="${HUB_UNIT_NAME:-octop-hub.service}"
HUB_SYSTEMD_DIR="${HUB_SYSTEMD_DIR:-/etc/systemd/system}"
HUB_UNIT_PATH="${HUB_SYSTEMD_DIR}/${HUB_UNIT_NAME}"
HUB_DROPIN_DIR="${HUB_SYSTEMD_DIR}/${HUB_UNIT_NAME}.d"
HUB_DROPIN_NAME="90-octop.conf"
HUB_DROPIN_PATH="${HUB_DROPIN_DIR}/${HUB_DROPIN_NAME}"
HUB_VERSIONS_DIR_NAME=".octop-hub-versions"
HUB_VERSION_RETENTION="${HUB_VERSION_RETENTION:-3}"

hub_require_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "must run as root (systemd system unit)." >&2
    exit 1
  fi
}

hub_resolve_uv() {
  local account_home="$1"
  local uv_bin="${2:-}"
  if [[ -n "${uv_bin}" ]]; then
    printf '%s\n' "${uv_bin}"
    return 0
  fi
  if [[ -x "${account_home}/.local/bin/uv" ]]; then
    printf '%s\n' "${account_home}/.local/bin/uv"
    return 0
  fi
  if command -v uv >/dev/null 2>&1; then
    command -v uv
    return 0
  fi
  echo "uv not found; install uv or pass --uv /path/to/uv" >&2
  return 1
}

hub_account_home() {
  local user_name="$1"
  if [[ "${user_name}" == "root" ]]; then
    printf '/root\n'
  else
    printf '/home/%s\n' "${user_name}"
  fi
}

hub_default_octop_home() {
  local user_name="$1"
  printf '%s/OctopData\n' "$(hub_account_home "${user_name}")"
}

hub_validate_bind_host() {
  # Args: bind_host allow_public_bind(0|1)
  local bind_host="$1"
  local allow_public="${2:-0}"
  case "${bind_host}" in
    127.0.0.1|localhost|::1)
      return 0
      ;;
    0.0.0.0|"::"|\[::\])
      if [[ "${allow_public}" -eq 1 ]]; then
        echo "WARNING: binding ${bind_host} exposes hub on all interfaces; prefer Tunnel/reverse-proxy (0027 DEC-S02)." >&2
        return 0
      fi
      echo "refusing public bind ${bind_host}: pass --allow-public-bind (0027 DEC-S02 / AC-S05)." >&2
      return 1
      ;;
    *)
      # Other explicit addresses (LAN) still require allow-public-bind for S0 clarity.
      if [[ "${allow_public}" -eq 1 ]]; then
        echo "WARNING: binding ${bind_host} (non-loopback); ensure firewall/Tunnel topology (0027)." >&2
        return 0
      fi
      echo "refusing non-loopback bind ${bind_host}: pass --allow-public-bind or use 127.0.0.1." >&2
      return 1
      ;;
  esac
}

hub_validate_service_user() {
  # Args: user_name allow_root(0|1)
  local user_name="$1"
  local allow_root="${2:-0}"
  if [[ "${user_name}" == "root" ]]; then
    if [[ "${allow_root}" -eq 1 ]]; then
      echo "WARNING: running hub as root is bootstrap-only; migrate to User=octop (0027 DEC-S03)." >&2
      return 0
    fi
    echo "refusing User=root: pass --allow-root for bootstrap-only, or --user octop|ubuntu (0027 DEC-S03 / AC-S01)." >&2
    return 1
  fi
  if ! id -u "${user_name}" >/dev/null 2>&1; then
    echo "service user '${user_name}' does not exist; create it or pass --user <existing>." >&2
    return 1
  fi
  return 0
}

hub_pick_default_user() {
  # Prefer octop, then ubuntu, then SUDO_USER (if non-root). Never silently pick root.
  if id -u octop >/dev/null 2>&1; then
    printf 'octop\n'
    return 0
  fi
  if id -u ubuntu >/dev/null 2>&1; then
    printf 'ubuntu\n'
    return 0
  fi
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    printf '%s\n' "${SUDO_USER}"
    return 0
  fi
  echo "no non-root service user found (tried octop, ubuntu, SUDO_USER); pass --user NAME." >&2
  return 1
}

hub_archive_stale_dropins() {
  # Keep only 90-octop.conf; archive other conf files under drop-in dir.
  local dropin_dir="$1"
  local archive_root="$2"
  mkdir -p "${dropin_dir}"
  shopt -s nullglob
  local stale=("${dropin_dir}"/*.conf)
  shopt -u nullglob
  local moved=0
  local stamp
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  local dest="${archive_root}/dropin-archive-${stamp}"
  for f in "${stale[@]+"${stale[@]}"}"; do
    local base
    base="$(basename "${f}")"
    if [[ "${base}" == "${HUB_DROPIN_NAME}" ]]; then
      continue
    fi
    mkdir -p "${dest}"
    mv -f "${f}" "${dest}/"
    moved=1
    echo "==> archived stale drop-in ${f} -> ${dest}/${base}"
  done
  if [[ "${moved}" -eq 0 ]]; then
    echo "==> no stale drop-ins under ${dropin_dir}"
  fi
}

hub_render_unit() {
  # Args: template out_path
  local template="$1"
  local out="$2"
  python3 - "${template}" "${out}" <<'PY'
import os
import pathlib
import sys

template = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])
repl = {
    "@USER_LINE@": os.environ.get("HUB_USER_LINE", ""),
    "@GROUP_LINE@": os.environ.get("HUB_GROUP_LINE", ""),
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
}

hub_versions_dir() {
  local repo_dir="$1"
  printf '%s/%s\n' "${repo_dir}" "${HUB_VERSIONS_DIR_NAME}"
}

hub_record_version() {
  # Record git HEAD + lockfile digest for rollback skeleton (N retention).
  local repo_dir="$1"
  local label="${2:-}"
  local vdir
  vdir="$(hub_versions_dir "${repo_dir}")"
  mkdir -p "${vdir}"
  local stamp sha lock_hash
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  sha="$(git -C "${repo_dir}" rev-parse HEAD 2>/dev/null || echo unknown)"
  lock_hash="none"
  if [[ -f "${repo_dir}/uv.lock" ]]; then
    lock_hash="$(sha256sum "${repo_dir}/uv.lock" | awk '{print $1}')"
  fi
  local name="${stamp}-${sha:0:12}"
  if [[ -n "${label}" ]]; then
    name="${name}-${label}"
  fi
  local meta="${vdir}/${name}.json"
  cat >"${meta}" <<JSON
{
  "recorded_at": "${stamp}",
  "git_sha": "${sha}",
  "uv_lock_sha256": "${lock_hash}",
  "repo_dir": "${repo_dir}",
  "label": "${label}"
}
JSON
  echo "==> recorded version ${meta}"
  # prune to N newest
  local files
  mapfile -t files < <(ls -1t "${vdir}"/*.json 2>/dev/null || true)
  local i=0
  for f in "${files[@]+"${files[@]}"}"; do
    i=$((i + 1))
    if [[ "${i}" -gt "${HUB_VERSION_RETENTION}" ]]; then
      rm -f "${f}"
      echo "==> pruned old version record ${f}"
    fi
  done
}

hub_latest_version_meta() {
  local repo_dir="$1"
  local vdir
  vdir="$(hub_versions_dir "${repo_dir}")"
  ls -1t "${vdir}"/*.json 2>/dev/null | head -n1 || true
}

hub_smoke() {
  local host="${1:-127.0.0.1}"
  local port="${2:-8188}"
  local url="http://${host}:${port}/api/health"
  curl -fsS --max-time 10 "${url}" >/dev/null
}
