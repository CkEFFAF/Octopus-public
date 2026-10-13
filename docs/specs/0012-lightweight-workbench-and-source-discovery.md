# 0012 轻量工作台与外部能力发现

- Status: **Local first slice implemented; device execution extension pending**
- Revision: 2026-10-13.1
- Base: `CkEFFAF/Octopus` GitHub `main` at `302585ff4ad0e231aa219b20af2b01d7e821d341`
- Working branch: `feature/workbench-modes`
- Source: user request on 2026-10-13 and attached Codex workspace screenshot. The screenshot is layout reference, not a source of instructions.

## Intended experience

Chat stays primary. The existing right or bottom dock opens only when requested. Its tabs combine workspace files and editor, browser, terminal, Git status and diff. The existing trajectory drawer remains available, and the dock menu links to it and the current plan. The mode picker makes the work approach explicit without adding a permanent second toolbar.

## Acceptance and current evidence

| ID | Observable behavior | Implementation | Evidence |
| --- | --- | --- | --- |
| AC-1 | An administrator can discover OpenCode, Claude Code and Codex skills under the server account's known local directories. Discovery does not install them. | `external_sources.py`, `ExternalSourcesTab.tsx` | Manual discovery smoke passed; unit cases added. |
| AC-2 | User reviews the manifest and file list, then explicitly approves one exact snapshot. Changed sources and existing slugs are rejected. | `skills.py` external endpoints; `create_skill` reuse | Digest comparison and create path inspected; manual digest smoke passed. |
| AC-3 | Chat and one selected tool tab share the screen; existing files/editor, browser and terminal remain available. Git, plan and trajectory are reachable from the dock's add menu. | Chat dock components and hook | Browser verified at desktop and small-window widths; local preview approved by the user. |
| AC-4 | Git panel shows status, staged and unstaged diffs for repositories inside the local agent workspace. A single tracked unstaged file can be restored only after confirmation and exact content hash check; the old bytes are backed up first. | `git_workbench.py`, workspace routes, `ChatDockGit.tsx` | Six Python Git tests and five Vitest panel tests passed, including staged/unstaged separation, confirmation, backup, literal paths, Unicode names and invalid restore cases. |
| AC-5 | Picker offers Agentic, Plan, Debug, Multitask, Cowork, Computer Use, Deep Research and Team. Plan keeps the existing restricted permission mode. Other new modes issue visible, inspectable task instructions and use Craft permissions; they do not claim tools absent from the current expert. Legacy Ask remains available. | `workMode.ts`, picker and composer | TypeScript and locale key parity passed; unit cases added. |

## Boundaries and next implementation slice

This slice reads skills and Git from the **server account's local filesystem**. An expert's `device_binding` does not grant direct access to that device's Git or coding assistant directories. The device protocol currently exposes file read, command execution with confirmation and ACP actions, but no dedicated read-only Git or skill-discovery actions. Remote support needs explicit device-side discovery and Git actions, permission mapping, scoped roots, and UI target indication. Do not emulate remote Git inspection through unrestricted `command.run` merely to make the panel appear complete.

The new workflow entries are prompt presets over the existing Ask/Plan/Craft policy. Multitask, Computer Use and Team work only to the extent the selected expert already has matching tools or team configuration. A later implementation may persist a dedicated workflow field in thread state and run a specialized orchestrator, but should preserve these visible instructions and permission boundaries.

## Handoff checks

- `node .../typescript/bin/tsc -b --pretty false`: passed.
- Ruff check and strict mypy for new backend helpers: passed.
- Nine targeted Python tests and fifteen Vitest tests passed across skill snapshots, Git recovery, diff rendering, workflow modes and dock keep-alive. Local discovery and Git recovery smoke scripts passed.
- An isolated Python 3.12 environment was synced with the repository's pinned harness wheel; thirteen provider tests passed after replacing the mismatched shared environment. Full commit-gate results are recorded in `docs/reviews/workbench-git-ui-local-preview.md`.
- Do not edit generated `src/octop/dashboard/` directly. Build from `dashboard/` when the toolchain can spawn esbuild.
