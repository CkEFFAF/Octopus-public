"""Workspace skill installation for authenticated native operations."""

from __future__ import annotations

from typing import Any

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.skills.skill_packages import validate_skill_slug
from octop.infra.utils.frontmatter import parse_frontmatter


class AgentWorkspaceSkillTarget:
    """Use the Harness workspace and preserve mounted/locked package ownership."""

    def __init__(self, manager: Any, agent_id: str, user: Any) -> None:
        self.manager = manager
        self.agent_id = agent_id
        self.user = user
        self.workspace = manager.get_agent(agent_id).workspace

    async def skill_exists(self, slug: str) -> bool:
        validate_skill_slug(slug)
        return any(
            item.get("slug") == slug
            for item in await self.manager.list_skill_summaries(self.agent_id)
        )

    async def write_files(self, slug: str, files: list[tuple[str, bytes]]) -> None:
        validate_skill_slug(slug)
        summaries = await self.manager.list_skill_summaries(self.agent_id)
        entry = next((item for item in summaries if item.get("slug") == slug), None)
        if entry and entry.get("kind") in {"package", "builtin"}:
            raise OctopError(
                ErrorCode.FORBIDDEN, "copy the supplied skill to a new slug before editing"
            )
        manifest = await self.workspace.aread_text(f"skills/{slug}/SKILL.md")
        if manifest:
            metadata, _ = parse_frontmatter(manifest)
            origin = str(metadata.get("origin") or "").strip()
            if metadata.get("locked") and origin:
                package = self.manager._repos.skill_package_repo.get(origin)
                if self.user.role != "admin" and (
                    package is None or package.created_by != str(self.user.id)
                ):
                    raise OctopError(
                        ErrorCode.SKILL_PACKAGE_LOCKED, "skill was copied from a locked package"
                    )
            await self.workspace.adelete(f"skills/{slug}")
        for path, _ in files:
            if path.endswith("/"):
                await self.workspace.amkdir(f"skills/{slug}/{path}".rstrip("/"))
        await self.workspace.aupload_many(
            [(f"skills/{slug}/{path}", data) for path, data in files if not path.endswith("/")]
        )

    async def after_install(self, slug: str, *, enable: bool | None = None) -> None:
        if enable is None:
            return
        from octop_harness.skills.catalog import skill_identity_keys

        disabled = set(self.manager.get_config(self.agent_id).get("skills_disabled") or [])
        manifest = await self.workspace.aread_text(f"skills/{slug}/SKILL.md")
        meta, _ = parse_frontmatter(manifest or "")
        keys = skill_identity_keys(
            {"slug": slug, "name": meta.get("name", slug), "path": f"skills/{slug}/SKILL.md"}
        )
        disabled = disabled - keys if enable else disabled | keys
        await self.manager.persist_skills_disabled(self.agent_id, disabled)
