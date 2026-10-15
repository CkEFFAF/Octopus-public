# CodeQL triage: authenticated owner execution

Date: 2026-10-15
Reviewed source: main `2d83fa4f`, SDK `22514b4`
Contract: [0015 revision 3](../specs/0015-device-execution-and-context-inspection.md), AC-03/05/16.
Independent reviewer: `gpt-5.6-sol`, high effort; integrating agent verified the referenced gates.

## Findings

The new public repository enables Code Scanning upload. Its first PR analysis
reports four taint findings. These sinks implement the explicitly requested
ability to execute commands and use native OS paths on the authenticated user's
own devices. They do not expose an unauthenticated execution or filesystem API.

| Public alert | Rule | Sink | Triage |
| --- | --- | --- | --- |
| 1 | `py/path-injection` | `infra/devices/acp_process.py:76` | Intentional authorized ACP executable; false positive for an authorization bypass. |
| 2 | `py/path-injection` | `infra/devices/executor.py:433` | Owner native command cwd; restricted mode maps a configured device root. |
| 3 | `py/path-injection` | `infra/devices/executor.py:990` | Native filesystem cwd is available only with applied owner trust and file capability grants. |
| 4 | `py/command-line-injection` | `infra/devices/acp_process.py:76` | Explicit authorized process execution with `create_subprocess_exec` and an argument vector; no shell interpolation. |

## Inspected boundary

1. HTTP execution requires the authenticated current account and loads its
   persisted context. Context lookup rechecks expert, device and thread ownership.
2. Preparation rechecks the frozen policy/grant revision and read-only work mode.
   Device dispatch rechecks current ownership, applied policy and required grants.
3. `DeviceExecutor.execute` calls `_authorize` before these sinks. Native `fs.*`
   requires owner mode; restricted command and ACP resolve the configured local
   root and retain their capability and writable-root checks.
4. Owner mode deliberately permits native absolute paths and OS-account command
   execution. Limiting these sinks to a shared directory would violate AC-05 and
   would not sandbox command execution in any case.

No cross-owner, stale-context, missing-grant or restricted-root bypass was found
in the inspected chains. The independent review approved the named SDK/native
fixes with one unrelated Minor mode-hydration repair, which is being addressed.

Existing behavior regressions include owner read/write outside cwd, native command
cwd without confirmation, another account's policy rejection, pending-policy
execution rejection, read-only Plan enforcement and frozen-context rejection
after policy changes in `tests/unit/devices/test_trusted_execution.py`.

## Disposition

Record these four alerts as false positives with the above authenticated-owner
capability rationale. Keep CodeQL analysis, report retention, upload and future
alert checks enabled. This disposition covers these four sinks and inspected
source only; it is not a blanket suppression of path or process findings.

Production desktop input/reconnect and registered-device acceptance remain
separate from this source review and are not declared passed here.
