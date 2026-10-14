# Background device input review, 2026-10-14

Reviewer: independent GPT-6 agent. Author model not supplied.

Scope: the two stdin guards in `src/octop/infra/devices/client.py` and their parameterized regression in `tests/unit/devices/test_client.py`, compared with `8be6df458625df69f83e013aa0b8aebadfdcc9c9` on `hotfix/device-background-input`.

Verdict: Approve. No blocking or major defect identified.

## Findings

Both confirmation branches now short circuit before calling isatty when stdin is None. The desktop branch retains its default reject decision; the permission proposal branch explicitly rejects when confirmation is required but no terminal exists. Interactive confirmation and the existing policy for proposals not requiring confirmation are unchanged. Neither new condition grants permissions or applies a proposal.

The regression exercises both real protocol branches with stdin set to None, verifies the correlated rejection response, then verifies a successful ping on the same connection and unchanged executor permissions. These assertions demonstrate connection continuity and default rejection rather than only testing the Boolean guard.

The existing connection finally block still cancels and awaits heartbeat and operation tasks. The regression closes its fake socket, awaits the connection coroutine and closes the executor on the passing path. No production resource lifetime changes were introduced.

## Verification boundary

This review inspected the exact diff and surrounding protocol and cleanup code without modifying business code or Git state. The parent reports both regression cases failed before the fix, 46 relevant tests passed afterward, Ruff passed, and two real pythonw clients rejected takeover while remaining online across three pings. Those execution results are parent-provided evidence, not independently rerun in this lightweight review.
