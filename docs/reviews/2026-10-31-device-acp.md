# Review, working tree, 2026-10-31

**Reviewed by**: Codex (author model unspecified)
**Scope**: ACP working-tree changes, uncommitted
**Verdict**: Approve

## Summary
The device settings store checks ownership and strips environment variables from effective configurations. Existing sessions retain their original target, and permission responses now route by the ACP session ID supplied by the pinned Harness tool. The previously reported permission-resume failure is fixed.

## Strengths
- Device overrides are scoped to the owner and strip environment variables.
- Existing message and close operations look up the session's original target; permission responses locate the owning service by session ID.

## Test coverage
The supplied verification reports broad automated coverage, successful live OpenCode and Codex checks, and 11 focused tests passing after the permission routing fix. The added regression test checks the exact Harness argument shape; it uses a mocked target service rather than a full suspended ACP session.

The final working-directory diagnostic and capability-list changes were also inspected; no additional actionable finding was identified. Supplied verification includes live Hub RPC and expert-chat checks for OpenCode and Codex, plus the added delegate regression test.
