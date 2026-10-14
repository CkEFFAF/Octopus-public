# Background device input review, 2026-10-14

Reviewer: independent GPT-6 agent. Author model not supplied.

Scope: the two stdin guards in `src/octop/infra/devices/client.py` and their parameterized regression in `tests/unit/devices/test_client.py`, compared with `8be6df458625df69f83e013aa0b8aebadfdcc9c9` on `hotfix/device-background-input`.

Verdict: Approve. No blocking or major defect identified.

## CI follow-up: stopping while connecting

Focused follow-up verdict: Approve. Reviewed the additional stop-event check immediately inside the connection context and its gated-connection regression. No blocker identified.

When stop occurs before the connection context has entered, the new check returns before assigning the socket or sending hello. Returning from inside async with still awaits its exit, which closes the late socket. Both surrounding finally blocks still run, clearing the socket reference and closing executor resources. Normal connection, authentication, permission reconciliation and retry behavior are unchanged when the stop event is clear. If context cleanup raises an already handled transport exception, the set stop event also prevents backoff and another loop iteration.

The regression uses events to establish the precise ordering: connection entry begins, stop is requested, then the socket becomes available. It verifies run completes, the socket is closed and no hello or other message was sent. Its finally block releases the gate, cancels and gathers the task, and closes the executor, including on assertion failure. At that review stage the existing network test timeout was unchanged. A subsequent, separate test-budget adjustment is recorded below.

The parent reports this focused case timed out before the change and passed afterward, with 57 client/network/takeover/permission cases and Ruff passing. The Windows CI failure establishes a cleanup timeout; the initial failure may have been masked by that cleanup and its specific cause is not established by this review. The new regression independently targets the confirmed stop-during-connect race. These execution results are parent-provided evidence; this follow-up inspected code and tests only.

## Subsequent real-network test budget adjustment

Focused verdict: Approve. Reviewed the uncommitted change confined to `test_two_real_managers_survive_one_disconnect_and_reconnect_same_identity`. Its initial connection, file response, reconnection and final termination waits now each use a finite 30-second budget, replacing 5, 5, 8 and 5 seconds respectively. No production timeout or retry policy is changed.

This test verifies continuity, identity isolation and eventual shutdown, with no documented five-second performance requirement. A functional waiting budget that accommodates the client's existing 15-second connection timeout and CI scheduling is appropriate. Thirty seconds remains a test limit, not a new operational latency promise. A regression may take longer to report, but missing events or nontermination still fail.

The existing behavioral checks remain: manager B connects once and returns the proof.txt directory entry while A disconnects, A reconnects with the same device ID and token, two client state directories remain distinct, and network.stop must be followed by completion of the running task. There is no skip, exception suppression or removal of these assertions. The deterministic stopped-during-connect regression remains separate and still catches that specific race with its short gated test.

The parent reports 36 client/network tests and Ruff passed after the budget adjustment. This supports the current change but does not prove that the first Windows failure was caused by scheduling or ACL setup. The initial CI exception may still have been masked by cleanup, and its specific cause remains uncertain. Review verification here was the exact diff and surrounding test logic only.

## Findings

Both confirmation branches now short circuit before calling isatty when stdin is None. The desktop branch retains its default reject decision; the permission proposal branch explicitly rejects when confirmation is required but no terminal exists. Interactive confirmation and the existing policy for proposals not requiring confirmation are unchanged. Neither new condition grants permissions or applies a proposal.

The regression exercises both real protocol branches with stdin set to None, verifies the correlated rejection response, then verifies a successful ping on the same connection and unchanged executor permissions. These assertions demonstrate connection continuity and default rejection rather than only testing the Boolean guard.

The existing connection finally block still cancels and awaits heartbeat and operation tasks. The regression closes its fake socket, awaits the connection coroutine and closes the executor on the passing path. No production resource lifetime changes were introduced.

## Verification boundary

This review inspected the exact diff and surrounding protocol and cleanup code without modifying business code or Git state. The parent reports both regression cases failed before the fix, 46 relevant tests passed afterward, Ruff passed, and two real pythonw clients rejected takeover while remaining online across three pings. Those execution results are parent-provided evidence, not independently rerun in this lightweight review.
