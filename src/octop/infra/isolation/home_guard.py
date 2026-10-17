"""Dev / production ``OCTOP_HOME`` separation (0028 DEC-I05 / AC-I03).

Production homes carry a marker file. A development process that points at the
same path (or a home marked production while ``OCTOP_ENV=development``) fails
the check so JWT / connector credentials are not shared by mistake.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

PRODUCTION_MARKER_NAME = ".octop_production"

HomeSeparationStatus = Literal["ok", "warn", "fail"]


@dataclass(frozen=True)
class HomeSeparationResult:
    status: HomeSeparationStatus
    detail: str
    home: Path
    production_marked: bool
    env_label: str

    @property
    def ok(self) -> bool:
        return self.status != "fail"


def is_production_home(home: Path | str) -> bool:
    """True when *home* contains the production marker file."""
    root = Path(home).expanduser()
    return (root / PRODUCTION_MARKER_NAME).is_file()


def write_production_marker(home: Path | str) -> Path:
    """Create the production marker (ops helper; not called automatically)."""
    root = Path(home).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / PRODUCTION_MARKER_NAME
    if not marker.is_file():
        marker.write_text(
            "# Octop production home marker (0028). Do not point a dev instance here.\n",
            encoding="utf-8",
        )
    return marker


def check_dev_prod_home_separation(
    home: Path | str | None = None,
    *,
    env: dict[str, str] | None = None,
    strict: bool | None = None,
) -> HomeSeparationResult:
    """Check that a development runtime is not using a production-marked home.

    * ``OCTOP_ENV=production|prod`` with a marked home → ok
    * ``OCTOP_ENV=development|dev|local`` (or unset treated as non-prod) against
      a marked home → **fail** (or warn when ``OCTOP_HOME_GUARD=warn``)
    * Unmarked home → ok (dev or unmarked prod both allowed; ops should mark)
    """
    source = env if env is not None else os.environ
    if home is None:
        raw = str(source.get("OCTOP_HOME", "")).strip()
        root = Path(raw).expanduser() if raw else Path.home() / ".octop"
    else:
        root = Path(home).expanduser()

    env_label = str(source.get("OCTOP_ENV", "")).strip().lower() or "unset"
    marked = is_production_home(root)
    guard = str(source.get("OCTOP_HOME_GUARD", "")).strip().lower()
    if strict is None:
        if guard in {"0", "off", "false", "no"}:
            return HomeSeparationResult(
                status="ok",
                detail="home guard disabled via OCTOP_HOME_GUARD",
                home=root,
                production_marked=marked,
                env_label=env_label,
            )
        strict_mode = guard not in {"warn"}
    else:
        strict_mode = bool(strict)

    is_dev = env_label in {"", "unset", "development", "dev", "local", "test"}
    is_prod_env = env_label in {"production", "prod"}

    if marked and is_dev:
        detail = (
            f"OCTOP_HOME={root} is marked production ({PRODUCTION_MARKER_NAME}) "
            f"but OCTOP_ENV={env_label!r}; refuse shared prod data from a dev process"
        )
        if strict_mode:
            return HomeSeparationResult(
                status="fail",
                detail=detail,
                home=root,
                production_marked=True,
                env_label=env_label,
            )
        return HomeSeparationResult(
            status="warn",
            detail=detail,
            home=root,
            production_marked=True,
            env_label=env_label,
        )

    if is_prod_env and not marked:
        return HomeSeparationResult(
            status="warn",
            detail=(
                f"OCTOP_ENV={env_label!r} but {PRODUCTION_MARKER_NAME} missing under {root}; "
                "ops should mark production homes"
            ),
            home=root,
            production_marked=False,
            env_label=env_label,
        )

    return HomeSeparationResult(
        status="ok",
        detail="dev/prod home separation check passed",
        home=root,
        production_marked=marked,
        env_label=env_label,
    )
