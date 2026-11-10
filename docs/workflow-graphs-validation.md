# Graph validation, 2026-11-10

The implementation and requested compact workspace are available in the isolated feature working copy. This is local validation evidence, not a deployment or a claim that real research experiments have run. The spec remains In Progress while the patch awaits integration.

## Final checks

| Check | Result |
| --- | --- |
| Full backend, `uv run --no-sync pytest -n 8 -m "not live" -q` | 5,666 passed, 157 skipped, 1,078.75 seconds |
| Graph models/repository/planning/runtime/examples and canonical Agent-delivery integration | 49 passed, 30.53 seconds; includes four documentation examples added after the full-suite collection |
| Full dashboard, Vitest runner with four workers and 30-second test timeout | 347 files, 1,817 tests passed, 825.24 seconds |
| Graph dashboard tests, including settings consolidation and stale JSON responses | 4 files, 17 tests passed |
| Strict mypy | 759 source files passed |
| Ruff check and format check | Passed, 1,508 Python files formatted |
| TypeScript project build | Passed |
| ESLint and Prettier on changed Graph/dashboard surfaces | Passed |
| Vite production build | Passed in 2 minutes 26 seconds; existing large vendor-chunk warning remains |
| Independent code review | gpt-6-astra, Approve; subsequent targeted 14-file follow-up also Approve |
| Cumulative patch application | `git apply --check --cached` passed against develop `f71eb815af01a7b32d0237968a8754d1387dd762` and main `9adaf2fa622976a6c4617c2817f886e8ce654327` |
| Graph-only patch application | Passed against the staged performance-v2 baseline |

On this Windows runner, the local dependency junction requires the prepared ESM runner configs `.vitest-performance.mjs` and `.vite-performance.ts`. They reproduce the repository configs with the ESM directory-name adjustment and are not delivered source changes. `PYTHONPATH` was explicitly bound to this checkout's `src`, so the reused editable environment could not import the original checkout instead. No package installation was performed through the junction.

## Acceptance evidence

| Contract | Evidence |
| --- | --- |
| AC-1, shared authoring/version/owner scope | Repository revision/conflict/version tests, owner-scoped API and tool tests, immutable pinned-version UI test |
| AC-2, visual editor | DOM canvas/definition/page tests; real local browser node creation, drag, edge deletion by keyboard, connection by ports, selection inspector, context controls, fit, save, export and publish |
| AC-3, node execution/loops/parallelism | Real durable repository runtime tests for branch context, one-time join and error grouping, bounded loops and ready-preflight error loops; capacity and nonblocking canonical-session lock tests |
| AC-4, triggers and durable waits | Early signal retained across runner replacement, single-consumer activation test, schedule skip/restart/dedup tests, 160-wait fairness test, 130-signal ordinary-wakeup fairness test |
| AC-5, canonical execution | Full server integration using a fake Harness response through actual CronDeliveryService and canonical child-history persistence; detached local Python Job with actual terminal receipt, working directory and environment |
| AC-6, before/after contexts | Protected system/tool-chain projection tests, new/restored thread and independently retained recipe tests, frozen execution/MCP source tests; real UI export confirms new session, recent 8 turns, restore session/keep recipe |
| AC-7, inspection | Typed unfinished/completed activation responses, bounded output summaries, pinned run canvas, run orchestration tests |
| AC-8, recovery/control | Accepted/unknown/superseded capacity retention, dead-local-worker reservation release without replay, lease fencing, receipt-only reconciliation and truthful Job-cancellation tests |
| AC-9, events and authority | Scoped callback rotation, nested-data idempotency, raw/data size limits, authorization/mode/shared-text guards and credential redaction tests |

The real browser screenshot records the full workspace after save and publication. It shows the compact header, floating Add control, larger semantic cards and context chips, visible ports, hidden selection inspector and collapsed run history. Browser Agent control chrome is separate from the application UI. The original browser verification space was subsequently closed; it was not silently replaced or reclaimed.

## Practical limits

PostgreSQL migration execution, external devices/providers, real model inference and GPU workloads were not run. The integration tests use an isolated account/database and controlled Harness/transport fakes, with a real short local Python Job for the process/receipt boundary. Dedicated mobile browser verification and every production environment combination remain integration checks, not claims made by these local results.

No commit, push, PR, production database mutation or deployment was performed. The original checkout remained clean at `9adaf2fa622976a6c4617c2817f886e8ce654327`. Raw logs and screenshot evidence live in the task workspace; the delivery report records their file paths.
