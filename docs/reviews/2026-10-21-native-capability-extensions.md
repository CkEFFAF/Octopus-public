# Native capability extension review

Date: 2026-10-21
Scope: spec 0035 revision 3, local changes over PR39/main `4b59917be90bf8204bc93cd9fa825055a9b0f756`.
Review method: implementing agent's integrated code and behavior review; no independent reviewer was used.

Agents now discover/configure encrypted connections, create/install/toggle workspace skills, manage builtin/plugin tool switches, install requested plugins with the existing module permission, and configure/probe/attach custom MCP services. The Dashboard shares credential preparation/persistence, refreshes successful changes and distinguishes saved/probed/deferred results.

| Acceptance | Implementation and evidence |
| --- | --- |
| LC8–LC9 | Authenticated native wrapper, fresh user/module permissions, owned resources, encrypted ConnectorService persistence and output/error/audit redaction. `test_native_extensions.py` checks ordinary users, revocation, disabled modes/users/tools, foreign ownership, secret non-echo and invalid-update preservation. |
| LC10 | Custom mailbox validation, configurable ports and SMTP465 implicit TLS. `test_mail_servers.py` mocks both SMTP transports; HTTP preview and real Dashboard form checks verify port round trips. No real authentication or delivery was attempted. |
| LC11 | Builtin/custom attachment retains scoped choices and uses existing live middleware. Native integration verifies saved configuration reaches the next tool resolution and device-denied attachment is rejected before persistence. Existing installed-Harness live-configuration scenarios remain green. |
| LC12–LC13 | Localized tool labels, safe port preview/form helper and successful receipt-only refresh. Composer tests reject failed, foreign and old-thread receipts; browser verifies saved/deferred labels and synthetic form submission. |
| LC14 | Canonical package validation/commit and BackendWorkspace operations; install-disabled, enable keys, safe paths, mounted/builtin protection and same-turn skill reading are covered. Conversation skill filters remain effective. |
| LC15 | Tool settings merge through existing helpers. Critical tools and foreign experts stay protected. Plugin installation requires the plugins module, schedules reloads without closing active graphs, and returns deferred receipts. A real synthetic echo plugin archive is installed through the existing URL installer with the download replaced by a local fixture. |
| LC16 | Custom MCP uses encrypted canonical storage/validation, preserves other servers, requires explicit replacement and redacts probe/errors. Target changes cannot silently reuse saved authentication. Tests exercise HTTP/stdio configuration and mocked discovery without calling remote tools. |
| LC17 | Skill/tool panels refresh on scoped saved writes, including server-wide plugin installation. Composer changes remain scoped to the active conversation; saved/probed/next-request/after-turn states are distinct. Native-first guidance is shipped in skill-manager and Octop Assistant. |

Verification:

- `make all`: 5068 passed, 157 skipped, 36 dependency deprecation warnings; Ruff and mypy (677 files) passed. Local log: `D:/Agent_Workspace/octopus/ops/native-extension-make-all-1021.log`.
- After the last MCP authentication-target safeguard: 321 focused cases passed, 1 skipped; mypy (677 files) passed again. Log: `D:/Agent_Workspace/octopus/ops/native-extension-final-focused-1021.log`.
- Final focused frontend: 4 files / 8 tests passed, covering custom mailbox ports, capability result states, composer isolation and open-panel refresh.
- Final `npm run build` after the panel refresh hook passed TypeScript and Vite production build (37.48 seconds). Log: `D:/Agent_Workspace/octopus/ops/native-extension-final-frontend-build-1021.log`.
- Changed React files had0 ESLint errors; existing hook-dependency warnings were preserved. Diff whitespace check uses `core.whitespace=cr-at-eol` because backend locale files are CRLF in the existing index.
- Ego-browser operated real components using synthetic in-memory API responses. It verified configured ports, an edited SMTP 587 submission with IMAP 1993 retained and password omitted, and the deferred plugin label. The 800×480 viewport had no horizontal overflow. Two screenshot attempts timed out at CDP capture; no pixel-level visual acceptance is claimed. Preview files, page and local Vite server were removed/stopped after the interaction check.

No production account/mailbox access, messages sent, external package download, commit/push/PR, deployment, or Windows/Linux CI claim is part of this local feature delivery. Inputs supplied to tools still enter conversation history; vault encryption and redacted outputs do not constitute a new secret-entry protocol. OAuth consent remains interactive. Graph-bound plugin additions become available after active turns; saving a connector or MCP definition alone does not verify authentication or attach it to every conversation.

Release follow-up after the user's commit/deploy request: PR40 initially passed Linux (5207 passed,18 skipped), all packaging and CodeQL checks. Windows reported5065 passed/159 skipped and one timeout in the unchanged reload event-loop test. The1s deadline covered synchronous config/schema assembly, and the150ms fake rebuild also imposed a scheduling race. Local comparison measured config assembly at0.2132s with baseline native tools versus0.3638s with the added tools; the isolated regression passed. Parameter-model reuse removes repeated reflection while retaining fresh per-expert closures. The test now holds the rebuild behind a release signal and asserts loop progress before release. Related agent/native checks passed122 cases; a repeated-builder regression verifies distinct expert defaults and strict argument validation after schema reuse. New CI and final rollout evidence supersede the initial local-only delivery state and are tracked in PR40 and the private rollout record.

With parameter models primed, the same local measurement observed0.1275s config assembly. A negative-control experiment deliberately ran the fake blocking wait inline on the event loop; the new concurrency regression failed as expected. The release gate does not simply skip or invert the failed assertion.
