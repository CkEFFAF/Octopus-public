# Review — execution architecture foundation — 2026-10-14

**Reviewed by**: independent Codex review agent; did not author implementation.
**Scope**: current uncommitted first-chain implementation in octop-workbench and octop-harness-execution, against spec 0015 revision 2. Source inspection only, plus isolated synthetic probes; no Git operations, real device approvals, release or deployment.
**Verdict**: Changes requested

## Summary

Owner policy acknowledgements, persisted context ownership and storage/execution separation are substantive foundations. Three correctness problems remain in saved-directory recovery and native filesystem semantics. This is not acceptance of all 16 criteria: Jobs, remote workbench/browser and persistent RequestSnapshot are explicitly outside this review's delivery scope. The previous revision's consent requirements are superseded and are not findings against this architecture.

## Major

### Saved project directory can prevent the device reconnecting

**Location**: `src/octop/infra/devices/executor.py:379`, `:469`; `src/octop/infra/devices/client.py:258`.

**Problem**: `saved_executor()` reconstructs an owner executor with the persisted working directory. Its constructor calls `apply_policy`, which rejects a missing directory. If a previously valid project folder is renamed, deleted or its drive is temporarily unavailable, startup fails before connecting to the controller. The controller cannot deliver a corrected policy although the device identity remains valid.

**Evidence**: Direct construction with owner mode and a nonexistent absolute directory raised `DeviceExecutionError: working directory must be an existing absolute directory`. The saved-state constructor passes that same field before `run()` can establish the connection. Existing invalid-policy tests exercise a running client, not this restart case.

**Suggested fix**: Separate restoring identity/trust from validating the availability of an execution default. Reconnect and report the unavailable directory; reject affected operations until corrected, without silently choosing another project. Add a saved-policy restart regression with a removed directory and recovery via a new policy.

### Editing a symbolic link replaces the link instead of its target

**Location**: `src/octop/infra/devices/filesystem.py:36–54`, `:140`.

**Problem**: `fs.edit` reads through a symlink and computes the target file's digest. Its nested `fs.write` also checks that target content, but `os.replace(temporary, path)` replaces the directory entry for the symlink. The original target remains unchanged and the link becomes a regular file containing the edited content. This violates the owner-mode native-link behavior and can silently break linked project/configuration files.

**Evidence**: Source trace: `path.read_bytes()` and `digest(path)` dereference the link, while `os.replace` acts on the final link entry. No actual symbolic link or user file was modified in review.

**Suggested fix**: Define write-through semantics for existing links and resolve the actual destination consistently before checks and atomic replacement; preserve the link. Add read/edit/write coverage on POSIX and Windows where symlink support is available.

### Canceled native filesystem tasks can still mutate after reporting cancellation

**Location**: `src/octop/infra/devices/executor.py:898–900`, `:749–754`.

**Problem**: All native filesystem work runs in `asyncio.to_thread`. Canceling the awaiting task does not stop its worker. `execute()` immediately records the operation as canceled, and connection/grant teardown treats the task as finished, while a slow write, edit, move or recursive remove may still commit afterward. Revoking writes does not revalidate the already-running worker before its side effect.

**Evidence**: An isolated probe replaced only the native worker with a threading-event gate. After it entered, the operation task was canceled and awaited, write permission was removed, then the gate was released. Output: `worker reached mutation after cancellation and write revocation: True`. The probe performed no filesystem mutation or real device operation; it verifies the lifecycle race directly.

**Suggested fix**: Give cancellable filesystem workers a cancellation/commit protocol and coordinate policy changes with in-flight commits; for work that cannot be stopped, wait for its actual outcome and do not claim completed cancellation. Add deterministic gated-write and policy-change tests.

## Other inspected boundaries

- Context resolution validates account ownership of devices, agents and threads; calls recheck policy/grant revisions and observation modes.
- Explicit device selection takes precedence over the expert default; request backend looks up a persisted context rather than changing a shared backend target per turn.
- Owner execution is gated by applied mode/revision and protocol v3; policy application persists the existing state before sending its acknowledgement. No credential/device-ID replacement was observed.
- Harness keeps BackendWorkspace on storage and adds an explicit `/.agent/` route for internal content, with project execution as the default backend. No additional confirmed harness blocker found in this pass.
- Work remains in progress; no claim is made that the above inspection proves every entry point or every architecture acceptance criterion.

## Verification limits

Parent supplied device regression results (266 passed / 2 skipped, then focused 31 passed / 1 skipped after migration repair) and harness test status. These suites were not independently rerun. Review independently ran the missing-directory and gated-cancellation probes described above. No application source was modified.
