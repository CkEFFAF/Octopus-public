# 0022 Expert storage and execution permissions

Status: Accepted
Date: 2026-10-17

## Summary

Expert memory and skills belong to the controller. Project commands belong to the selected execution device. The GPU chat misdiagnosed controller storage failures using the GPU user's Linux permissions. The installed harness also denied normal expert files under `/root/**` while accidentally allowing hidden `.octop` descendants.

## Requirements

1. AC1: An expert can read, edit and read back its own MEMORY.md, AGENTS.md and USER.md when controller storage is under a sensitive host directory. No device command or privilege change is needed.
2. AC2: Storage access cannot cross into another expert or escape through traversal or a local symlink. Explicit configured skill sources outside the workspace are read only.
3. AC3: Authentication, session records, memory databases and checkpoint databases remain managed by the host, including configured declarative SQLite and transcript locations. Recursive search results receive per path authorization before rendering or offloading. Storage delete permits confirmed individual content files; host management owns directory removal. Sensitive path rules cover hidden descendants and Windows local aliases.
4. AC4: Native project paths continue to use the immutable execution context and the device policy. Expert storage failures identify the storage policy and preserve the original `/.agent/` address.
5. AC5: Prompts identify controller storage and device execution separately. A note file is not represented as guaranteed future recall. Missing optional legacy skills directories are not advertised as load failures.
6. AC6: The management application consumes the exact tested harness revision. The GPU device transport and protocol remain compatible with existing devices.

## Decision

Keep expert files on the controller. Authorize `/.agent/` addresses against the current expert workspace and approved skill sources. Evaluate content rules against workspace relative paths, retaining explicit rules that target the full owned storage key. Protect runtime state independently of user content policy. Preserve stored addresses and data layout for existing conversations.

Moving the controller's `/root/OctopData` into the GPU user's home would mix two hosts and break ownership. Disabling `/root/**` globally would expose unrelated controller files. Neither is part of the fix.

## Build plan

1. Reproduce the policy conflict and hidden path mismatch with failing tests (AC1, AC3).
2. Scope storage authorization, protect runtime state and preserve native execution routing (AC1 to AC4).
3. Clarify prompts and optional skill fallback discovery (AC5).
4. Pin the tested harness source in the management application and verify integration (AC6).
5. Run formatting, static checks, complete suites and review the integrated change. Push isolated branches and create linked GitHub PRs.

## Consequences

No data migration, operating system permission change, GPU reinstall or production restart is required to prepare the code. Deployment must upgrade the controller's harness dependency. Existing mistaken notes and extracted memories need a separate, explicit correction through the normal application tools after deployment; this code change does not rewrite user history.

## References

Production chat `thr_01M52N1Z4WQVVVC9E1WWZ40KBC`, GPU expert `27N3HD`. Read only inspection used SQLite mode=ro. No credentials or raw chat contents are included in this specification.

Harness implementation: [PR 3](https://github.com/CkEFFAF/octop-harness/pull/3), source revision `d30b36cbb17e9e8403d01555a4f399667228263b`. The management dependency uses that immutable source archive and its lockfile hash, so it does not depend on a future unpublished wheel.

Verification: harness normal commit gate passed Ruff, mypy and 1740 tests (31 platform or external service skips). Its GitHub Linux Python 3.12 and CodeQL checks passed. Management full non live validation passed 4765 tests (153 skips); final pinned dependency integration checks cover the changed entry points. The implementation and subsequent review corrections were independently rechecked with no remaining actionable findings.
