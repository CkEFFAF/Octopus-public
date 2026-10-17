"""FS isolation gate for scoped ``root_dir`` (0028 DEC-I01 / AC-I02).

On Linux, a non-host ``root_dir`` with ``virtual_mode`` is expected to run under
bubblewrap (or an equivalent jail). Missing ``bwrap`` must not silently write
host-sensitive paths: either reject high-risk local shell use or degrade with
an explicit warning when the require-bwrap policy is off.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

FsMode = Literal["allow", "reject", "degrade"]

_HOST_ROOTS = frozenset({"/", "\\", ""})


@dataclass(frozen=True)
class FsIsolationDecision:
    """Outcome of evaluating a local backend spec against the bwrap gate."""

    mode: FsMode
    reason: str
    requires_bwrap: bool
    bwrap_available: bool

    @property
    def ok(self) -> bool:
        return self.mode != "reject"


def _is_host_root(root: Any) -> bool:
    if root is None:
        return True
    return str(root).strip() in _HOST_ROOTS


def _bwrap_available() -> bool:
    return shutil.which("bwrap") is not None


def require_bwrap_enabled(*, env: dict[str, str] | None = None) -> bool:
    """Whether missing bwrap must reject (production default: on).

    Env knobs (first match wins):
    - ``OCTOP_REQUIRE_BWRAP=1|0`` / true|false — explicit override
    - ``OCTOP_ENV=production`` (or ``prod``) → require
    - ``OCTOP_PRODUCTION=1`` → require
    - otherwise → False (dev/default: degrade with warning, do not hard-fail)
    """
    source = env if env is not None else os.environ
    raw = str(source.get("OCTOP_REQUIRE_BWRAP", "")).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    octop_env = str(source.get("OCTOP_ENV", "")).strip().lower()
    if octop_env in {"production", "prod"}:
        return True
    return str(source.get("OCTOP_PRODUCTION", "")).strip().lower() in {"1", "true", "yes", "on"}


def evaluate_local_fs_isolation(
    spec: Any,
    *,
    platform: str | None = None,
    bwrap_on_path: bool | None = None,
    require_bwrap: bool | None = None,
    env: dict[str, str] | None = None,
) -> FsIsolationDecision:
    """Evaluate whether a local backend may run high-risk file/shell tools.

    Only ``local_shell`` / ``filesystem`` (and composite defaults of those) with
    a non-host ``root_dir`` and ``virtual_mode`` truthy are gated. Host-rooted
    backends and remote sandboxes (docker / opensandbox) are left to their own
    isolation story.
    """
    plat = platform if platform is not None else sys.platform
    linux = str(plat).startswith("linux")
    available = _bwrap_available() if bwrap_on_path is None else bool(bwrap_on_path)
    require = require_bwrap_enabled(env=env) if require_bwrap is None else bool(require_bwrap)

    if not isinstance(spec, dict):
        return FsIsolationDecision(
            mode="allow",
            reason="non-dict backend left to caller",
            requires_bwrap=False,
            bwrap_available=available,
        )

    kind = str(spec.get("type") or "").strip().lower()
    if kind == "composite":
        default = spec.get("default")
        return evaluate_local_fs_isolation(
            default,
            platform=plat,
            bwrap_on_path=available,
            require_bwrap=require,
            env=env,
        )
    if kind not in {"local_shell", "filesystem"}:
        return FsIsolationDecision(
            mode="allow",
            reason=f"backend type {kind or 'unknown'} not subject to bwrap gate",
            requires_bwrap=False,
            bwrap_available=available,
        )

    root = spec.get("root_dir")
    if _is_host_root(root):
        return FsIsolationDecision(
            mode="allow",
            reason="host-rooted backend; bwrap jail not applicable",
            requires_bwrap=False,
            bwrap_available=available,
        )

    virtual = bool(spec.get("virtual_mode", True))
    if not virtual:
        return FsIsolationDecision(
            mode="allow",
            reason="virtual_mode disabled; path rewrite / jail not in scope",
            requires_bwrap=False,
            bwrap_available=available,
        )

    if not linux:
        return FsIsolationDecision(
            mode="degrade",
            reason="non-Linux host: no bubblewrap jail; rely on path rewrite",
            requires_bwrap=True,
            bwrap_available=False,
        )

    if available:
        return FsIsolationDecision(
            mode="allow",
            reason="bwrap available for scoped root_dir",
            requires_bwrap=True,
            bwrap_available=True,
        )

    if require:
        return FsIsolationDecision(
            mode="reject",
            reason="scoped root_dir requires bubblewrap; bwrap missing (OCTOP_REQUIRE_BWRAP)",
            requires_bwrap=True,
            bwrap_available=False,
        )

    logger.warning(
        "fs isolation degrade: scoped root_dir=%s without bwrap; path rewrite only",
        root,
    )
    return FsIsolationDecision(
        mode="degrade",
        reason="bwrap missing; degraded to path rewrite (require-bwrap off)",
        requires_bwrap=True,
        bwrap_available=False,
    )


def assert_local_fs_isolation(spec: Any, **kwargs: Any) -> FsIsolationDecision:
    """Raise ``PermissionError`` when the gate rejects the backend."""
    decision = evaluate_local_fs_isolation(spec, **kwargs)
    if decision.mode == "reject":
        raise PermissionError(decision.reason)
    return decision
