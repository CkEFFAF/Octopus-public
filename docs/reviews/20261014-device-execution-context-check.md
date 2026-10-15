# Review, release/1.0.2b11, 2026-10-14

**Reviewed by**: independent Codex review agent (did not author implementation; model separation not asserted)
**Scope**: uncommitted device consent, grant expansion, execution target and context inspection changes; spec 0015
**Verdict**: Blocked

## Summary

The implementation makes confirmations asynchronous, retains owner checks for device tools, and uses request epochs to prevent context responses crossing agent/thread boundaries. Two unresolved consent issues remain: remotely accessible approval files can defeat local approval, and unavailable native windows prematurely remove the headless inbox. This is an interim review of an actively changing working tree; resolved findings are recorded below.

## Blockers

### Remote file access can forge local approval — `src/octop/infra/devices/consent.py:152`

**Problem**: The inbox accepts a JSON decision when its nonce matches the readable request. DeviceExecutor `_path` (`executor.py:524–544`) allows paths inside its shared root without excluding device/network state. A shared user directory or disk root, explicitly supported by AC-08, can therefore expose `state/consents` to an already authorized files_read/files_write connection. That connection can read the request nonce and create the decision via ordinary file upload operations.

**Why it matters**: An account with file permissions can approve its own new roots, command capability or desktop takeover without a device-local person. Private filesystem ACLs do not isolate the same client's file-operation code from its consent code. Other controller state under the same shared root also needs isolation.

**Evidence**: An isolated synthetic request under a temporary shared root was read with actual `files.read`; actual `files.write_begin`, `files.write_chunk` and `files.write_commit` created its decision. The process printed `Remote file API forged valid approval predicate: True`. Only fake request data was used; no real device, native prompt or authorization was invoked. The test exercised the file API using an executor without a persistent journal; the production `_path` implementation does not consult state_dir either.

**Suggested fix**: Exclude the entire device-network private state tree from remote file operations and directory enumeration, including every controller's state, even when an ancestor is shared. Verify denial for read/stat/list/write and upload commit with a broad shared root, while local CLI approval still works.

## Major

### No interactive desktop removes the headless inbox — `src/octop/infra/devices/consent.py:150`

**Problem**: Windows always starts `_native_confirm`. Missing Tk or failure to create the interactive window returns False (`consent.py:85–93`). `confirm` treats that as a completed rejection, exits, and deletes the inbox request immediately.

**Why it matters**: AC-04's local CLI approval is unavailable on headless Windows or an unavailable DISPLAY: the request is removed before a person can inspect/decide it. This differs from an explicit refusal or timeout.

**Suggested fix**: Distinguish native UI unavailability from a real refusal. Keep the inbox alive until the protocol deadline when no native UI can be opened, while actual reject/close/timeout continues to reject. Cover unavailable native UI, local CLI approval, expiry and cancellation without opening real device prompts.

## Minor

### Polling discards previously loaded history — `dashboard/src/pages/Chat/components/ChatDockContext.tsx:45`

**Problem**: Loading an older page merges it, but the next 5/15-second refresh replaces events with only the latest 120 and resets the cursor. An older selected step and its content disappear while the person is inspecting them.

**Suggested fix**: Merge refreshed latest events into retained pages and preserve the oldest pagination cursor; reset only when the thread/agent changes. Add a pagination-then-poll regression.

## Resolved during review

- Silent 4000-character consent truncation: the implementation now preserves complete details and line breaks, escapes other controls, and provides a scrollable native text area. A synthetic details string beyond 4000 characters retains its final sensitive-path marker in the latest code. The previously reported hidden-roots approval risk is resolved by inspection.

## Strengths

- Confirmation tasks are canceled and awaited on connection teardown and superseding grant versions; the reader can continue serving heartbeats during human decisions.
- New roots are validated for absolute/existing/non-link paths before the local roots map is updated; owner HTTP resolution checks new paths and high-risk additions.
- Device tools retain authenticated ownership checks, persistent-versus-temporary target conflicts, and selected grant-version checks. Context refreshes use epochs to reject stale responses.

## Test coverage and limits

- Parent reported 131 focused tests and static checks passing before this review; this report does not claim to have rerun that suite.
- Reviewer performed source and data-contract tracing plus the isolated file-API approval-forgery reproduction above. No business code or Git state was changed.
- Frontend verification and real native acceptance remain with the parent/user. Fixes for the two open consent findings require focused regression evidence before approval.
