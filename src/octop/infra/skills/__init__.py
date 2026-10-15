"""Skills facade; pure package inspection does not load host install services."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from octop.infra.skills.install import (
        SkillAlreadyExistsError,
        SkillInstallTarget,
        commit_skill_install,
        install_skill_from_skillhub,
        install_skill_from_url,
        prepare_skillhub_package,
        resolve_url_import,
    )
    from octop.infra.skills.skill_package_store import SkillPackageStore
    from octop.infra.skills.skill_packages import (
        ResolvedSkillPackage,
        SkillPackageError,
        SkillPackageTooLarge,
        normalize_skill_files,
        resolve_skill_package,
        resolve_workspace_uploads,
        validate_skill_slug,
    )

_EXPORTS = {
    "SkillAlreadyExistsError": "install",
    "SkillInstallTarget": "install",
    "commit_skill_install": "install",
    "install_skill_from_skillhub": "install",
    "install_skill_from_url": "install",
    "prepare_skillhub_package": "install",
    "resolve_url_import": "install",
    "ResolvedSkillPackage": "skill_packages",
    "SkillPackageError": "skill_packages",
    "SkillPackageTooLarge": "skill_packages",
    "normalize_skill_files": "skill_packages",
    "resolve_skill_package": "skill_packages",
    "resolve_workspace_uploads": "skill_packages",
    "validate_skill_slug": "skill_packages",
    "SkillPackageStore": "skill_package_store",
}


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(name)
    value = getattr(import_module(f"octop.infra.skills.{module}"), name)
    globals()[name] = value
    return value


__all__ = [
    "ResolvedSkillPackage",
    "SkillAlreadyExistsError",
    "SkillInstallTarget",
    "SkillPackageError",
    "SkillPackageStore",
    "SkillPackageTooLarge",
    "commit_skill_install",
    "install_skill_from_skillhub",
    "install_skill_from_url",
    "normalize_skill_files",
    "prepare_skillhub_package",
    "resolve_skill_package",
    "resolve_url_import",
    "resolve_workspace_uploads",
    "validate_skill_slug",
]
