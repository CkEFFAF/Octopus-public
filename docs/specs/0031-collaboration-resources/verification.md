# Integration verification

Contract: 0031, revision 2026-10-18.4. Architect/integrator: root. Date: 2026-10-18.

Status: local implementation, regression verification and independent source review complete; final full gate has only reproduced baseline failures. This record does not declare the full repository green or live rollout accepted.

## Acceptance evidence map

| Acceptance | Observable checks |
| --- | --- |
| AC1 | `test_collaboration_resources.py`: actual assembled read tool with unavailable device; bounded document parsing and source revalidation. `test_team_attachments.py` uses the common reader. `test_collaboration.py` drives actual HTTP upload through preparation to Processor model input and rejects forged metadata. |
| AC2, AC3 | `test_team_device_context.py` drives real middleware through application preparation and execution resolution for sync/async policies; separate overlapping child sessions, replay and strict schema checks. `test_paper_dispatch_entrypoints.py` checks actual runtime tools. |
| AC4 | Exact invocation/version grants, cross-account denial, revocation, mutable upload-source rejection and cache access revalidation in resource tests. |
| AC5 | Real FastAPI public-message projection and owner checks in `test_collaboration.py`; dashboard panel/dock tests cover mounting, cursor merge, child details and artifacts. Resource tests cover more-than-500 recent references and old event-page reference recovery, including owner/thread boundaries. |
| AC6 | Real replay/conflict/retry/cancellation/completion race tests in `test_team_device_context.py`; Harness full suite covers ToolRuntime identity, awaited acceptance and executor uncertainty. Startup missing/corrupt/valid, recovery and repeated-transition idempotence tests use actual SQLite state/events and controlled snapshots. |
| AC7, AC8 | Native fake GPU report publication, parent resource reading, explicit fake laptop delivery and acknowledgement/hash failures in resource tests; verified authenticated frontend resource preview/download component tests. |
| AC9 | Ask/Plan target restrictions, denied roots, shared peer text-only restrictions, thread/account/grant checks, isolated actual device contexts. |
| AC10 | `test_progress_final_reconciliation.py`, history suite and existing nested child stream isolation regressions. |
| AC11 | Harness transaction contention, retryable busy outcome, rollback, retirement/successor/journal atomicity tests in its final full suite. No live memory was changed. |
| AC12 | SQLite migration/new and already applied watermark tests; real FastAPI/OpenAPI tests; backend/dashboard locale parity; strict source checks and integrated suites. PostgreSQL is source-reviewed only. |

## Recorded gates

Evidence logs are retained in workspace `ops/`; they are local acceptance evidence and are not runtime product assets.

* Harness final source: **1837 passed, 31 skipped**; Ruff lint and 353-file format check pass; strict mypy 192 source files pass. Logs: `harness-final-pytest-20261018.log`, `harness-final-static-20261018.log`.
* Application uses the actual installed portable Harness wheel. All 369 package files match its manifest. Wheel SHA256 is `e0bcc39b92e7d8603af319e54267a5f069716f40c0581592577c5c2920ebaf1f`. The relative uv source/lock was checked; no Harness source PYTHONPATH was used for final integration runs.
* Initial application full non-live suite: **4849 passed, 21 failed, 153 skipped**. Eight failures reproduce on an unmodified archive of application HEAD 60111355: offsite POSIX hook on Windows, six Linux hub executable/bash checks, and backup default retention mismatch 14 versus 7. Logs: `collaboration-app-full-20261018.log`, `collaboration-backend-baseline-20261018.log`.
* **Final application full non-live suite: 4870 passed, 8 failed, 151 skipped, 838.42 seconds** (`uv run --no-sync --offline pytest -n 4 -m 'not live' --durations=10`). Final failure identities exactly match those eight baseline failures; all thirteen collaboration-affected failures are resolved. Log: `collaboration-app-final-20261018.log`. No baseline exclusions were used to obtain this result.
* Coder's final affected checks: **171 passed, 2 skipped**; expanded gateway checks **479 passed, 2 skipped**. They include all thirteen corrected cases and the final boundaries, with the actual installed wheel. The real HTTP 9 MiB binary upload/content path succeeds, while parsing returns `DOCUMENT_LIMIT` independently.
* Root final application strict mypy for all `src`: **exit 0**. Ruff lint passes; format checks pass for 1320 files and report only four unrelated baseline test-format failures. The changed integration test is formatted. Logs: `collaboration-app-final-mypy-20261018.log`, `collaboration-app-final-static-20261018.log`, `collaboration-baseline-format-20261018.log`.
* Dashboard broad suite: **1373 passed, 12 assertion failures plus one new suite-import failure**. All 12 assertion failures reproduce on unmodified HEAD (8 dock, 1 sidebar, 1 admin path, 2 run receipt). The new PDF-engine import failure was fixed at the production lazy-load boundary; four affected suites / 11 tests then passed. Logs: `collaboration-frontend-full-20261018.log`, `collaboration-frontend-baseline-dock-20261018.log`, `collaboration-frontend-baseline-other-20261018.log`.
* Root final dashboard checks: **four suites / 19 tests pass**, including all four existing add-tab cases; typecheck, affected ESLint and Prettier pass; production build passes in 64 seconds. Logs: `collaboration-frontend-final-targeted-20261018.log`, `collaboration-frontend-final-static-20261018.log`, `collaboration-final-frontend-build-20261018.log`. Backend/dashboard tool-label parity: 10 tests pass with the installed wheel; collaboration zh/en keys match (77).
* Root restored each changed tracked file's HEAD newline style to remove whole-file diff noise, checking normalized bytes stay identical. `git diff --check` passes with `core.whitespace=cr-at-eol` for the baseline CRLF files. Final gate input fingerprint: 2610 files, manifest SHA256 `5b9617a3b489ce115050c54c512898379f1b72c038ba134396642fb1eb4ab301`; post-gate comparison is identical. The root AGENTS guide gains one factual contract pointer; curated prose and historical audits remain intact.

## Independent review and limits

Independent GPT-6 Luna high source review resolved invocation isolation, snapshot crash ordering, PostgreSQL cursor ordering, cancellation uncertainty/late completion and publication provenance findings. Its final correction pass inspected startup snapshot recovery, configured resource/parser cap separation, both Processor paths, recent/event-referenced listing and indexed queries, HTTP models/ownership, and frontend reason/state handling; no remaining material finding. See [review record](../../reviews/20261018-collaboration-resources.md). A provisional registered-upload UI finding was withdrawn after checking the actual pre-render filter; no code change was required.

No live PostgreSQL service or actual GPU/laptop transfer was used for acceptance: device cases use the native protocol with controlled fakes. Browser tooling explicitly reports local browser disabled in Work settings; visual acceptance was not performed or bypassed. No production deployment, source commit/push or live memory mutation occurred. These limitations prevent a claim of production rollout acceptance.

## Resume verification, 2026-10-18

Later sharing/provider development changed the combined working tree after the original frozen gate. The original full-suite figures above remain historical evidence, not a claim that this newer combined revision passes every repository gate.

The resume found and corrected one stale collaboration test: it asserted that the global migration watermark was exactly29 after the sharing migration030 had been added. The check now verifies return to the initially discovered current watermark, a minimum collaboration schema version29, repeated migration idempotence and preservation/replay of an existing accepted invocation. The owned AGENTS contract pointer now describes029 as the introducing migration rather than the permanently current watermark.

* Current installed-wheel integration: **220 passed, 2 skipped**, including actual resource/tool/API flows, dispatch isolation, gateway attachment handling, mode propagation and history reconciliation. Log: `ops/collaboration-resume-pytest-final-20261018.log` in the workspace parent. These tests run without a Harness source PYTHONPATH.
* Current dashboard: **23 passed in five suites** (collaboration panel/dock, resource preview, existing add-tab behavior and attachment utilities). TypeScript check and production build pass; Vite completed in58.76seconds. Logs: `collaboration-resume-frontend-final-20261018.log`, `collaboration-resume-build-20261018.log`.
* Collaboration/document/history source Ruff checks and the changed regression's format check pass. `git diff --check` passes with the existing CRLF convention.
* The wheel SHA256 and all369 installed package files still match `vendor/harness/source-manifest.json`. The companion Harness source differs from that artifact only in the later provider preset JSON; it has deliberately not been silently folded into the reviewed collaboration wheel.
* **Current global Python typecheck is not green**: sharing additions report three errors at `infra/history/sharing.py:161` and `infra/agents/native_management_tools.py:749,761`. They are outside the collaboration implementation and were preserved. Log: `collaboration-resume-mypy-20261018.log`. The earlier eight backend and twelve frontend baseline failures also remain documented; the full suites were not rerun during this focused resume.
* Resume source comparison found only the corrected regression and the generated dashboard manifest changed during these checks. Final fingerprint:2631 files, SHA256`2a7898d6ef508756f4c3fc307c3c133003c96b42c7bb4f31989e57817dc8f1bd`; `ops/collaboration-resume-source-final-20261018.json`.

Deployment and live-data repair remain separate from local implementation: existing cloud chat history and the two previously identified operational memory facts have not been rewritten. Explicit Ask/Plan runtime restrictions are tested; this does not assert that arbitrary prose containing “read-only” is automatically converted into a runtime policy. Live GPU/laptop, PostgreSQL and browser visual acceptance remain unverified.
