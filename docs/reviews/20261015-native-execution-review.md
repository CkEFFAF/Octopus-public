# Native execution incremental review, 2026-10-15

**Reviewer**: independent Codex reviewer, not the implementation author.

**Scope**: current implementation of spec 0015 revision 3. Supplied baselines: main `28a97280`, SDK `1774fe9`. Reviewed native target resolution, device transport and observation, browser and desktop routing, transfers, Job process observation, current target UI, request provenance and SQLite close. Existing WorkMode fixes were not repeated. No Git operations or broad gates were run.

**Verdict**: Changes requested. Four Major findings below. This is not architecture completion or release approval.

## Major findings

### 1. Browser operations can persist typed secrets and DOM through the queued API

**Location**: `D:/Agent_Workspace/octopus/octop-workbench/src/octop/infra/devices/service.py:1296` through `1306`. Related result filtering: `src/octop/infra/devices/protocol.py:161`.

`submit` rejects ACP streams but accepts every `browser.*` action and writes the complete caller params into the durable operation row. `_execute` subsequently retains the result through `ledger_result`, which removes images but keeps DOM, element text and evaluated JS results. Both the generic operations API and `device_run` can reach this path, including `ExecutionService.submit` with a valid context.

**Reproduction evidence**: Used a fresh in memory database, a genuinely enrolled owner device and the real DeviceService with an isolated fake transport. Submitting `browser.action` with `command=type` and `text=PRIVATE_TYPED_SECRET` left that exact text in the persisted operation params. Submitting `browser.observe` retained the fake device response `text=PRIVATE_DOM_BODY` and its element text in the persisted result. These observations exercise real authorization, submission and persistence; no actual browser or private data was used.

**Impact**: Browser input, including passwords, can be retained in the ordinary operation ledger, contrary to the browser privacy contract. The normal immediate call path avoiding that ledger does not protect the alternative queued entry point.

**Recommendation**: Exclude browser streams from durable queued operations, or explicitly support them with a bounded metadata only request and result schema. Cover both raw operations and the contextual `device_run` path.

### 2. The raw device API bypasses server derived browser lanes

**Location**: `D:/Agent_Workspace/octopus/octop-workbench/src/octop/api/routers/devices.py:456` through `458`. Related authorization: `src/octop/infra/devices/service.py:1116`.

The context API derives `browser_lane` from authenticated owner/agent/thread, but `/devices/{device_id}/call` forwards arbitrary params directly to DeviceService. DeviceService checks device ownership, capability and agent ownership, without validating or deriving the browser lane. DeviceBrowsers accepts any 64 character hex lane. The lane hash is reproducible from known IDs, not an authorization credential.

**Reproduction evidence**: In the isolated enrolled device probe, created two experts under one owner. Called `DeviceService.call` as expert `caller` with the SHA256 lane for `[owner, victim, victim-thread]`. The request passed real authorization and the fake transport received the victim lane unchanged, without an execution context. This is the exact service invocation made by the raw API. The generic queued endpoint also accepts the same input.

**Impact**: A client or a tool using the raw path can address another expert/thread's browser session and bypass context mode and frozen policy checks. This finding is within one device owner's account; no cross account access was demonstrated.

**Recommendation**: Require a validated execution context for browser calls on every public entry point and always derive its lane server side. Reject client supplied lanes on raw calls instead of treating their format as authentication.

### 3. Opening the browser in another thread can select the previous thread's context

**Location**: `D:/Agent_Workspace/octopus/octop-workbench/dashboard/src/pages/Chat/hooks/useChatDockPanel.ts:222` through `235`.

The execution tab key includes target, directory, policy and mode, but neither agent/thread scope nor context origin. Existing tabs are cleared only when the expert changes. Switching between two threads of the same expert keeps the old tab. Opening the browser creates a context for the new thread, computes the same tab key, discards the new context, and activates the old tab.

**Reproduction steps**: In expert E, thread A, open the device browser. Navigate to thread B of E using the same device, directory and mode, then open the browser. `createContext` is called with B, but the existing tab with A's context wins the `tabs.some` branch. `ExecutionBrowser` continues sending through A's context and browser lane. The chat page uses route params without a thread keyed remount, so its hook state is retained. Desktop and terminal surfaces also share this key construction.

**Impact**: Inputs intended for B can affect A's browser, and B's model browser does not match the displayed workbench. Keeping an already opened tab frozen is appropriate; using it as the new thread's browser is not.

**Recommendation**: Include the originating account/agent/thread scope in tab identity, while retaining old frozen tabs separately if desired. Cover a same expert thread switch with identical target settings.

**Verification limit**: This finding follows the concrete hook and routing control flow. The attempted isolated Vitest probe could not start because spawning esbuild returned `EPERM`; it is not reported as an executed UI reproduction. Temporary probe files were removed.

### 4. Recovery cancellation reports success when a recorded process cannot be observed

**Location**: `D:/Agent_Workspace/octopus/octop-workbench/src/octop/infra/devices/jobs.py:320` through `325`.

`same_process` returns None for AccessDenied as well as for an absent process. The initial `live` filter therefore removes inaccessible identities. Cancellation only checks receipts for the remaining identities, while the coverage test compares `member_count` against the unfiltered identity list length. An inaccessible recorded member can consequently count as covered without any stopped confirmation.

**Reproduction evidence**: Called the real `JobSupervisor.cancel` with an isolated fake persisted manifest containing two process identities and a lost worker. The first identity was observable and its stop succeeded; a fake psutil Process raised `AccessDenied` when inspecting the second identity. The method wrote and returned `status=cancelled`. The second identity was never passed to `confirmed_stopped`. No OS process was launched or changed in this probe.

**Impact**: The UI and RunEvent can claim a Job was cancelled while an unobservable member may still be running. The earlier overlapping parent/child correction does not cover this initial filtering case.

**Recommendation**: Confirm the final state of every recorded identity. Treat missing or reused identities as stopped only after a positive check, and preserve unknown for AccessDenied or incomplete coverage. Add the observable member plus inaccessible member case beside the existing parent/child regression.

## Other observations and verification boundaries

Read only Job actions now bypass the old context revision gate while the device transport authorizes the current grant. New executions remain frozen. No additional defect was confirmed in that limited change, transfer checksum/context guards, request source splitting, or the inspected SQLite worker close path.

The transfer cancellation text explicitly says the browser transfer stopped and does not claim the device file was rolled back. An uncertain commit should not be interpreted as a confirmed rollback; that wording was not raised as a defect.

Independent evidence consists of the current in memory authorization/persistence probe, the deterministic cancellation probe, and source tracing. No production devices, permissions, credentials, actual desktop input, Git state or application code were changed. Only this report remains as a review artifact.

Parent supplied evidence includes Windows main 4633 passed/153 skipped before the last small changes, 42 affected tests after those changes, SDK Windows 1665/28, and prior SDK Linux 1668/22. These broad gates were not repeated. The ongoing Linux main gate, real fleet desktop acceptance and release remain outside this review conclusion.
