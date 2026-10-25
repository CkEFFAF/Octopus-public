#!/usr/bin/env bash
# Build a device-only Linux archive from current source and the existing PBS runtime.
# No dashboard, account database, controller keys or Windows binaries are copied.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "${REPO_ROOT}/desktop/portable/_common.sh"

usage() {
  cat <<'USAGE'
Usage: bash desktop/portable/package-device-linux.sh linux-amd64|linux-arm64
       bash desktop/portable/package-device-linux.sh linux-amd64|linux-arm64 --docker

Native Linux builds verify the bundled interpreter and device CLI before packing.
Other hosts may assemble binary wheels for Linux, but the result remains unverified
until its runtime and commands are exercised on that Linux architecture.
Set OCTOP_GREEN_OFFLINE=1 to require cached runtime and dependency wheels.
USAGE
}

PLAT="${1:-}"
if [[ "$PLAT" == "-h" || "$PLAT" == "--help" ]]; then usage; exit 0; fi
case "$PLAT" in
  linux-amd64) EXPECTED_MACHINE=x86_64; DOCKER_PLATFORM=linux/amd64; WHEEL_PLATFORM=x86_64-manylinux_2_28 ;;
  linux-arm64) EXPECTED_MACHINE=aarch64; DOCKER_PLATFORM=linux/arm64; WHEEL_PLATFORM=aarch64-manylinux_2_28 ;;
  *) usage >&2; exit 2 ;;
esac
if [[ $# -gt 2 || ( $# -eq 2 && "$2" != "--docker" ) ]]; then usage >&2; exit 2; fi

if [[ "${2:-}" == "--docker" ]]; then
  command -v docker >/dev/null || { echo "Docker is unavailable." >&2; exit 1; }
  docker info >/dev/null 2>&1 || { echo "Docker daemon is unavailable." >&2; exit 1; }
  # --platform is essential: GREEN_HOST_PLAT alone cannot emulate ARM64 Python.
  exec docker run --rm -i --platform "$DOCKER_PLATFORM" \
    -e OCTOP_GREEN_OFFLINE="${OCTOP_GREEN_OFFLINE:-0}" \
    -e PBS_TAG="$PBS_TAG" -e PBS_PY="$PBS_PY" -e PBS_BASE_URL="$PBS_BASE_URL" \
    -v "${REPO_ROOT}:/src" -w /src "${OCTOP_DEVICE_LINUX_IMAGE:-python:3.12-bookworm}" \
    bash -s -- "$PLAT" <<'CONTAINER'
set -euo pipefail
if ! command -v uv >/dev/null; then
  [[ "${OCTOP_GREEN_OFFLINE:-0}" != 1 ]] || {
    echo "Offline Docker build requires an image with uv already installed." >&2; exit 1
  }
  python -m pip install uv
fi
bash desktop/portable/package-device-linux.sh "$1"
CONTAINER
fi

require_uv
HOST="$(host_plat)"
RUNTIME="${GREEN_RUNTIMES}/${PLAT}"
RUNTIME_ARCHIVE=""
if [[ "$HOST" == windows-* ]]; then
  # NTFS/Git Bash cannot reliably materialize Linux symlinks. Preserve the PBS
  # tar metadata directly in the result instead of extracting Linux on Windows.
  RUNTIME_ARCHIVE="${GREEN_CACHE}/$(pbs_archive_name "$PLAT")"
  if [[ ! -s "$RUNTIME_ARCHIVE" ]]; then
    [[ "${OCTOP_GREEN_OFFLINE:-0}" != 1 ]] || {
      echo "Offline runtime archive missing: ${RUNTIME_ARCHIVE}" >&2; exit 1
    }
    mkdir -p "$GREEN_CACHE"
    curl -fL --retry 3 --retry-delay 2 \
      -o "${RUNTIME_ARCHIVE}.partial" "${PBS_BASE_URL}/$(basename "$RUNTIME_ARCHIVE")"
    mv "${RUNTIME_ARCHIVE}.partial" "$RUNTIME_ARCHIVE"
  fi
else
  if [[ ! -d "$RUNTIME" ]]; then
    [[ "${OCTOP_GREEN_OFFLINE:-0}" != 1 ]] || {
      echo "Offline runtime missing: ${RUNTIME}" >&2; exit 1
    }
    bash "${REPO_ROOT}/desktop/portable/bootstrap-runtime.sh" "$PLAT"
  fi
  [[ -f "${RUNTIME}/bin/python3" || -f "${RUNTIME}/bin/python" ]] || {
    echo "Linux runtime is missing under ${RUNTIME}/bin; refusing another platform's runtime." >&2
    exit 1
  }
fi

if [[ "$HOST" == "$PLAT" ]]; then
  BUILD_PY="$(runtime_python "$RUNTIME")"
else
  BUILD_PY="${OCTOP_DEVICE_BUILD_PYTHON:-$(uv python find 3.12)}"
fi
if [[ "$HOST" == windows-* ]]; then
  BUILD_PY="$(cygpath -u "$BUILD_PY")"
fi
VERSION="$(octop_version)"
mkdir -p "$GREEN_RELEASE"
STAGE="$(mktemp -d "${GREEN_RELEASE}/.device-${PLAT}.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
PACKAGE_NAME="Octop-device-${PLAT}"
PAYLOAD="${STAGE}/${PACKAGE_NAME}"
mkdir -p "${PAYLOAD}/packages/octop/cli" "${PAYLOAD}/packages/octop/infra/devices" \
  "${PAYLOAD}/packages/octop/infra/utils" "${PAYLOAD}/packages/octop/i18n/domains" "${PAYLOAD}/packages/octop/infra/skills" \
  "${PAYLOAD}/packages/octop/infra/desktop"
if [[ -z "$RUNTIME_ARCHIVE" ]]; then cp -a "$RUNTIME" "${PAYLOAD}/runtime"; fi

# Explicit module allowlist: copying the whole workspace can leak runtime data.
MODULES=(
  __init__.py infra/__init__.py infra/utils/__init__.py
  infra/utils/httpx_proxy.py infra/utils/process_lock.py cli/__init__.py
  cli/device_cmd.py cli/device_startup_cmd.py infra/devices/client.py
  infra/devices/executor.py infra/devices/network.py infra/devices/autostart.py
  infra/devices/acp_process.py infra/devices/protocol.py
  infra/devices/first_run.py
  infra/devices/consent.py infra/utils/locale.py
  infra/devices/filesystem.py
  infra/devices/transfers.py
  infra/devices/jobs.py infra/devices/job_worker.py infra/devices/process_scope.py
  infra/devices/terminal.py infra/devices/terminal_worker.py
  infra/devices/capabilities.py infra/skills/__init__.py
  infra/devices/browser.py
  infra/devices/resources.py
  infra/devices/state_io.py
  infra/devices/updater.py infra/devices/update_policy.py
  infra/devices/desktop.py infra/desktop/__init__.py infra/desktop/capture.py infra/desktop/input.py
  infra/skills/external_sources.py infra/skills/skill_packages.py infra/utils/frontmatter.py
  infra/utils/git_workbench.py
  i18n/__init__.py i18n/loader.py i18n/domains/__init__.py
  i18n/domains/channel.py i18n/domains/errors.py i18n/domains/skills.py i18n/domains/tools.py
  i18n/domains/agents.py i18n/domains/attachment.py i18n/domains/slash.py i18n/domains/stream.py
)
for module in "${MODULES[@]}"; do
  cp "${REPO_ROOT}/src/octop/${module}" "${PAYLOAD}/packages/octop/${module}"
done
DATA_FILES=(i18n/en.json i18n/zh.json)
for data in "${DATA_FILES[@]}"; do
  cp "${REPO_ROOT}/src/octop/${data}" "${PAYLOAD}/packages/octop/${data}"
done
cp "${REPO_ROOT}/desktop/portable/start-device.sh" "${PAYLOAD}/start-device.sh"
cp "${REPO_ROOT}/desktop/portable/open-device.sh" "${PAYLOAD}/open-device.sh"
cp "${REPO_ROOT}/desktop/portable/open-device-transition.sh" "${PAYLOAD}/open-device-transition.sh"
chmod +x "${PAYLOAD}/open-device.sh" "${PAYLOAD}/open-device-transition.sh"
cp "${REPO_ROOT}/desktop/portable/setup-device.sh" "${PAYLOAD}/setup-device.sh"
cp "${REPO_ROOT}/desktop/portable/linux-device/README.md" "${PAYLOAD}/README.md"
cp "${REPO_ROOT}/LICENSE" "${PAYLOAD}/LICENSE"
chmod +x "${PAYLOAD}/start-device.sh" "${PAYLOAD}/setup-device.sh" "${PAYLOAD}/open-device.sh"

cat > "${PAYLOAD}/launch.py" <<'PYTHON'
"""Device-only portable entry; no Web UI or Octop account server is started."""
from pathlib import Path
import site

root = Path(__file__).resolve().parent
site.addsitedir(str(root / "packages"))
import click
from octop.cli.device_cmd import device

if __name__ == "__main__":
    click.Group(name="octop-device", commands={"device": device})()
PYTHON

REQ="${STAGE}/requirements.txt"
"$BUILD_PY" - "$REPO_ROOT" "$REQ" <<'PYTHON'
import pathlib, sys, tomllib
root, output = map(pathlib.Path, sys.argv[1:])
lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
wanted = {"click", "websockets", "psutil", "ptyprocess", "pyyaml", "playwright", "pyee", "greenlet", "typing-extensions"}
dependencies = {p["name"]: p for p in lock["package"] if p["name"] in wanted}
if set(dependencies) != wanted:
    raise SystemExit("Device dependencies missing from uv.lock")
requirements = []
for name, package in sorted(dependencies.items()):
    hashes = sorted({wheel["hash"] for wheel in package["wheels"]})
    if not hashes or any(not value.startswith("sha256:") for value in hashes):
        raise SystemExit("Device wheel hashes missing from uv.lock")
    requirements.append(f"{name}=={package['version']} " + " ".join(f"--hash={h}" for h in hashes))
output.write_text("\n".join(requirements) + "\n", encoding="utf-8")
PYTHON
INSTALL_ARGS=(--target "${PAYLOAD}/packages" --python-platform "$WHEEL_PLATFORM" \
  --python-version 3.12 --python "$BUILD_PY" --only-binary :all: --require-hashes \
  --cache-dir "${GREEN_CACHE}/uv" --link-mode copy)
if [[ "${OCTOP_GREEN_OFFLINE:-0}" == 1 ]]; then
  INSTALL_ARGS+=(--offline)
fi
# This subset is already pinned and hashed from uv.lock. Project resolver
# constraints are ranges, which are invalid additional hash-mode requirements.
uv --no-config pip install "${INSTALL_ARGS[@]}" -r "$REQ"
cp "$REQ" "${PAYLOAD}/requirements-device.txt"

VERIFICATION=not-run-cross-assembled
if [[ "$HOST" == "$PLAT" ]]; then
  DEVICE_PY="$(runtime_python "${PAYLOAD}/runtime")"
  "$DEVICE_PY" - "$PAYLOAD" "$EXPECTED_MACHINE" <<'PYTHON'
import pathlib, platform, site, ssl, sys
root = pathlib.Path(sys.argv[1])
if platform.system() != "Linux" or platform.machine() != sys.argv[2]:
    raise SystemExit("Bundled interpreter does not match requested Linux architecture")
site.addsitedir(str(root / "packages"))
import click, websockets
from octop.infra.devices.network import DeviceNetwork
from octop.infra.devices.client import DeviceClient
from octop.infra.devices.update_policy import DeviceUpdatePolicy, WindowLocal, may_cutover
from octop.infra.devices.updater import DeviceUpdater, detect_busy, resolve_software_version
print("native device imports OK", platform.machine(), ssl.OPENSSL_VERSION)
PYTHON
  "$DEVICE_PY" "${PAYLOAD}/launch.py" device --help >/dev/null
  "$DEVICE_PY" "${PAYLOAD}/launch.py" device run --help >/dev/null
  VERIFICATION=native-import-and-cli-smoke-passed
fi
{
  echo "platform=${PLAT}"
  echo "kind=headless-device-client"
  echo "octop_version=${VERSION}"
  echo "python=${PBS_PY}"
  echo "pbs_tag=${PBS_TAG}"
  echo "minimum_glibc=2.28 (device dependencies; PBS runtime baseline is 2.17; verify on target)"
  echo "verification=${VERIFICATION}"
} > "${PAYLOAD}/VERSION.txt"

ARCHIVE="${GREEN_RELEASE}/Octop-device-${PLAT}-${VERSION}.tar.gz"
"$BUILD_PY" - "$PAYLOAD" "$PACKAGE_NAME" "${ARCHIVE}.partial" "$RUNTIME_ARCHIVE" <<'ARCHIVE_PYTHON'
import copy, pathlib, posixpath, sys, tarfile
payload, package_name, output_path, runtime_archive = sys.argv[1:]

def distributable(info):
    # uv on a Windows build host creates Windows console launchers even when
    # wheels target Linux; PBS pip also carries unused distlib Windows stubs.
    if info.name.lower().endswith((".exe", ".dll", ".pyd")):
        return None
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    if info.name.endswith(("/setup-device.sh", "/start-device.sh", "/open-device.sh", "/open-device-transition.sh")):
        info.mode = 0o755
    return info

with tarfile.open(output_path, "w:gz") as output:
    output.add(payload, arcname=package_name, filter=distributable)
    if runtime_archive:
        with tarfile.open(runtime_archive, "r:gz") as runtime:
            for original in runtime:
                parts = pathlib.PurePosixPath(original.name).parts
                if not parts or parts[0] not in {"python", "install"} or ".." in parts:
                    raise SystemExit("Unsafe or unexpected PBS archive member")
                if not (original.isdir() or original.isfile() or original.issym() or original.islnk()):
                    raise SystemExit("Unexpected PBS archive file type")
                member = copy.copy(original)
                relative = "/".join(parts[1:])
                member.name = f"{package_name}/runtime" + (f"/{relative}" if relative else "")
                if member.issym():
                    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(relative), member.linkname))
                    if resolved.startswith(("/", "../")) or resolved == "..":
                        raise SystemExit("PBS symlink escapes runtime")
                elif member.islnk():
                    link_parts = pathlib.PurePosixPath(member.linkname).parts
                    if not link_parts or link_parts[0] != parts[0] or ".." in link_parts:
                        raise SystemExit("PBS hardlink escapes runtime")
                    member.linkname = f"{package_name}/runtime/" + "/".join(link_parts[1:])
                member = distributable(member)
                if member is not None:
                    output.addfile(member, runtime.extractfile(original) if member.isfile() else None)
ARCHIVE_PYTHON
mv "${ARCHIVE}.partial" "$ARCHIVE"
if command -v sha256sum >/dev/null; then
  (cd "$GREEN_RELEASE" && sha256sum "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256")
fi
echo "[device-linux] wrote ${ARCHIVE} (${VERIFICATION})"
