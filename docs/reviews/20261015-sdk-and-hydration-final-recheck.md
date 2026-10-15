# b11 final independent fix recheck

Date: 2026-10-15
Reviewer: independent `gpt-5.6-sol`, high effort
Main source: `2d83fa4f35e99f58d70c36279e0507c716092d81`
SDK source: `22514b47cca464a393c754ce3053908eaa25e813`
Contract: `docs/specs/0015-device-execution-and-context-inspection.md`, revision 3

## Verdict

Approve with one Minor repair recommended. No Blocker or Major regression was found in the named fixes.

## Minor

### Work mode hydration can overwrite an explicit change that returns to the baseline value

`D:\Agent_Workspace\octopus\octop-workbench\dashboard\src\pages\Chat\components\DeviceTargetSelect.tsx:123`

The hydration merge treats a field as unchanged when its current value equals the value captured before the request. The mode control remains usable while target hydration is loading. If the initial in memory mode is `agentic`, the user selects another mode and then deliberately returns to `agentic` before the saved selection resolves, `current.workMode === before.workMode` becomes true and the stored mode overwrites the user's final choice. The same race does not apply to target and directory because those controls are disabled until hydration is ready.

Recommended repair: track a per field dirty flag or revision for mode changes during hydration, rather than using value equality as the change signal. Add a deferred hydration regression that changes the mode away from and back to the baseline before resolving the saved response.

## Rechecked repairs

No additional actionable regression was found in these paths:

* SDK snapshot retention redacts full values before truncation, bounds retained identifiers and metadata, caps retained component detail, and continues computing full component counts and token estimates.
* External `lc_source`, `skill`, and memory recall markers are removed from normalized caller messages by copy. Runtime injected and checkpointed summary or skill messages retain their attribution.
* Compression comparison uses ordered identity and fingerprint pairs with retained multiplicities, and omits invented identifiers for unlabelled removals.
* ACP shutdown explicitly contains `CancelledError`, closes conversations concurrently, and continues after an individual cleanup failure.
* Existing thread sends and new execution panes require target hydration readiness. Frozen queued selections are scoped to the original agent and thread and bypass later ambient selection state only when the original explicit target was ready.
* The Windows terminal acceptance helper answers the two ConPTY terminal queries and waits for an actual PowerShell prompt before input.
* Browser discovery prefers cached Playwright Chromium over branded system installations while retaining system fallback.
* Linux CI, Windows CI, and release tests install Chromium through the Playwright package resolved in the project environment before running tests.

## CodeQL alert trace

The four public CodeQL alerts identify intentional native capability sinks, not a demonstrated authorization bypass in the inspected call chains:

* HTTP execution calls start with authenticated `current_user` and resolve contexts through the owner's repository namespace.
* `ExecutionService.get` rechecks device, expert, and thread ownership. `_prepare` rechecks frozen policy and grant revisions and enforces read only work modes.
* The device service rechecks device ownership, applied policy, capability grants, agent ownership, and expected grant version before sending the frame.
* `DeviceExecutor.execute` calls `_authorize` before any flagged path or process sink.
* Native `fs.*` is rejected outside owner mode. Restricted command and ACP calls map `root_id` to a device local configured root, instead of accepting the controller path. ACP also requires the explicit `acp_run` capability and a writable shared root on the device.
* Owner mode deliberately accepts absolute OS paths and process execution under the device account, as required by AC-05. ACP uses `create_subprocess_exec` with an argument vector and no shell interpolation.

The public CodeQL check is still red and therefore remains a merge gate until its alerts are recorded through the project's accepted security triage process. This review does not dismiss or suppress them.

## Acceptance limits

This was a read only source recheck. I did not run the full or focused suites because the mandatory commit hook was already running and the task prohibited interference. The supplied Windows, Linux, browser, and ConPTY results were treated as prior evidence, not independent acceptance.

Production remains b10. Public PR CI is still running, and the CodeQL auto check is currently failing on the four traced alerts. Revision 3 still requires real registered device desktop input, reconnect behavior, cross device target isolation, upgrade preservation, and production rollout evidence before architecture delivery can be declared accepted.

## Follow-up: hydration repair recheck

The earlier Minor is resolved. No actionable finding remains in the three-file repair diff.

* `D:\Agent_Workspace\octopus\octop-workbench\dashboard\src\pages\Chat\hooks\deviceTarget.ts:28` and `:45-47` add a scope-local work-mode mutation revision. `setExecutionSelection` increments it whenever a work-mode field is supplied, including a same-value write (`:88-90`), so an away-and-back choice is observable.
* `D:\Agent_Workspace\octopus\octop-workbench\dashboard\src\pages\Chat\components\DeviceTargetSelect.tsx:35-45` captures the revision with the selection baseline at mount or scope change. Hydration applies the saved work mode only while that revision is unchanged (`:127-129`). Retry attempts retain the original baseline, so any intervening work-mode write remains protected. A scope change captures the new scope's revision and disposes the prior request.
* `D:\Agent_Workspace\octopus\octop-workbench\dashboard\src\pages\Chat\components\DeviceTargetSelect.test.tsx:369-425` covers the deferred away-and-back race and scope switching. The strengthened retry case also covers an intervening same-value write before retry.

This follow-up was a read-only diff review. I did not rerun tests or type checks. The reported focused tests, TypeScript check, and formatting result remain supplied evidence rather than independent acceptance. The broader acceptance limits above remain unchanged.
