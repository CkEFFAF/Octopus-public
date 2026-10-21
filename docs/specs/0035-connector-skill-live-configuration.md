# Connector and skill live configuration

Date: 2026-10-21
Status: Implemented (focused verification; not deployed)
Baseline: main `6e9db521856183d71253b47690b64dacbd5db12e`.
Execution: one agent, as requested. No deployment.

## Requirements

- LC1: An authenticated expert self-update of connector selections applies to that same conversation at the next model boundary, including newly registered built-in gateway tools. Do not replace the graph or close the checkpointer of an active turn. Other conversations retain their explicit selections.
- LC2: Both model visibility and tool execution recheck current connector visibility, active state and credentials. Removed connections cannot be called through stale graph tools. Preserve mode, disabled-tool, device-deny, team and shared-text restrictions. A configured connection is not proof of successful upstream authentication.
- LC3: The chat composer follows successful native self-updates, including explicit empty selections, without requiring a new user message or overriding another thread's draft. Failed updates and late responses from another conversation cannot change selection. Agent profile, connector and skill lists refresh together.
- LC4: Installed, removed and disabled skills are resolved from current expert storage at model boundaries rather than trusting checkpointed `skills_metadata`. Preserve storage namespaces and package paths. Do not execute downloaded scripts to validate a package.
- LC5: `enable=false` really disables a newly installed skill. Marketplace manifests without runtime-readable YAML name/description fail before workspace writes. A failed read-only marketplace HTTP request must never install or upgrade host software; an already installed optional CLI may still be used.
- LC6: Explain that the Agent Mail cron source requires its own connector kind; it is not an authentication test for an IMAP/SMTP mailbox. Do not suggest OAuth or QQ web login for an app-password connector based only on that error.
- LC7: Exercise the actual installed graph with synthetic connectors: save, next model call sees tool, execution works, removal rejects stale calls, credential rotation uses fresh credentials, and concurrent threads remain isolated. Cover skill refresh, install-disable semantics and frontend event synchronization with focused checks; do not run an unsolicited full regression suite.

## Design

Use application middleware with supported model-request and tool-call overrides. Keep self-update selection overrides bound to authenticated owner, expert, thread and run; do not mutate cached agent-wide selection or another turn's config. A native update explicitly changing the current expert's connectors replaces that turn's stale selection snapshot; unrelated changes preserve it. Persisted defaults continue to apply through existing selection resolution for later turns.

The runtime applies capability changes between model calls. An already running call is allowed to finish with its original context. Device identity and execution scope remain frozen for the active run; settings requiring a graph rebuild retain an honest deferred status. Successful save receipts expose applied capability fields separately from remaining reload state.

Front-end updates consume successful, scoped native tool receipts rather than inferring a successful save from a tool name alone. Refresh the shared agent list and update only explicitly returned current-conversation capability fields. Preserve explicit user choices in other conversations.

Market compatibility means structural loader compatibility, correct storage and enablement, not a promise that arbitrary third-party tools/dependencies are installed. Keep existing archive traversal and resource limits. Do not install external software as a search fallback.

## Evidence

The public QQ-mail share shows a saved connector selection followed by absent tools. Its claimed `Agent Mail source is unavailable` diagnostic is misleading: that cron path accepts `agently-cli`, while the mailbox catalog uses an IMAP app password and an in-process gateway.

Earlier synthetic investigation reproduced that rebuilding a Harness graph after injecting tools leaves the currently executing graph unchanged. It also found stale explicit composer selections and checkpointed skill metadata. All findings must be rechecked on this baseline before acceptance.

## Verification on this baseline

- Python: 62 distinct focused cases passed across live configuration, skill installation, marketplace fallback, native management operations and skill package mounting. This includes the installed Harness graph with MCP filtering, conversation/tool filtering and deferred tool search, plus the real SkillsMiddleware prompt after same-turn installation.
- Frontend: 33 focused cases passed across composer resource synchronization, history and tool streams. TypeScript build checking passed. Changed Python files pass Ruff and the diff passes whitespace checking.
- Explicit empty connector receipts, failure/other-expert/late-thread receipts, credential rotation, permission revocation, read-only modes, owner scoping and frozen local device identity are covered.
- No production mailbox login, inbox read, send operation, deployment or full regression run was performed. Synthetic tools prove the application capability path, not the validity of a user's app password or arbitrary third-party skill dependencies.
- Changed frontend files pass Prettier. Formatting was limited to the changed files.
- Release preparation repeats the 62 focused cases in this checkout's `uv sync --frozen` environment with pinned Harness `1.0.2.post4.dev3+activity.3`; all pass. Full backend mypy (672 files), frontend production build and changed-file format/lint checks pass. GNU make is unavailable on the Windows host, so the local hook cannot run; these commands are recorded instead of claiming the hook or full CI passed.
