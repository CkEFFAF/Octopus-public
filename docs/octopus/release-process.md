# Octopus fork releases

Production tags belong to a merged `main` commit. The private Octopus fork uses
hotfix PRs into `main`; it currently has no `develop` branch. Complete Linux and
Windows CI before merging, then let `auto-tag-on-release.yml` read the version
from the merged tree and dispatch release builds.

## Default artifacts

The private fork creates a GitHub Release containing the Python distribution,
Windows x64 portable UI/client, Linux x64 portable management UI and Linux x64
headless device client. Portable dependencies are exported from `uv.lock`.
Updating the package version does not imply updating the harness dependency.

PyPI, Docker/GHCR, FnOS builds and develop synchronization remain enabled by
default for `TencentCloud/Octop`. Forks must explicitly opt in with repository
variables `OCTOP_PUBLISH_PYPI`, `OCTOP_PUBLISH_DOCKER`, `OCTOP_PUBLISH_FNOS` or
`OCTOP_SYNC_DEVELOP`, each set to `true`, and configure the required credentials
and branches. `OCTOP_RELEASE_PLATFORMS` can override the fork's default
`windows-amd64,linux-amd64` portable matrix.

Fork builds keep CI validation independent of Actions artifact storage quotas.
Each native package runner builds the dashboard from the same checkout. PRs
build and smoke-test packages without uploading temporary binaries. On a merged
version tag, Python distributions and native packages attach directly to the
same GitHub Release; upstream artifact/PyPI paths remain available. Historical
`attach_from_run` still supports previously retained artifacts.

CodeQL analysis remains mandatory. A readable finding summary and complete
gzip/base64 SARIF copies are retained in the job summary, independently of the
optional artifact copy. Missing or oversized reports fail the retention step
instead of silently losing results. This does not enable or bypass private
repository Code Scanning permissions.

The Linux device package now requires glibc 2.28 for its locked native
dependencies (including greenlet), rather than assuming the PBS interpreter's
2.17 baseline covers every dependency. Ubuntu 20.04's glibc 2.31 meets that
baseline; native runtime/CLI/connection checks are still required on target.

Private repositories without Code Security still run CodeQL analysis and retain
SARIF as an Actions artifact. Set `OCTOP_CODEQL_UPLOAD=true` only after enabling
Code Scanning. This changes result upload, not which queries run.

## Upgrading a hub

1. Download assets from this repository's release and verify checksums. Unpack
   into a new versioned directory; preserve the previous installation.
2. Rehearse database migrations on a protected server-local copy. For migration
   025, verify provider IDs/credentials, resource counts, foreign keys and the
   single legacy owner or explicit `PRIMARY_OWNER_USER_ID`. See
   [configuration ownership](configuration-ownership.md).
3. Stop the hub briefly. Back up its entire data directory and service unit,
   including environment, authentication and device authorization files. Keep
   the backup private; do not attach it to GitHub Releases.
4. Point the service at the new installation while retaining its existing data
   directory, account, bind address and port. Start it and check the health
   endpoint, application version, schema version and resource preservation.
5. For rollback, stop the new service and restore both the earlier installation
   and its pre-migration data. Switching binaries alone is insufficient after a
   schema upgrade. Preserve the failed state separately for investigation.

Existing device credentials survive a hub upgrade. Updating an execution client
is a separate operation: stop that client, install the new package and reuse its
existing device state; do not enroll a duplicate device merely to update code.
