# Immediate insertion verification, spec0033 revision4

The user requested an additional immediate insertion option after `sleep 900`
blocked the existing safe-boundary action, and explicitly requested the matching UI.
Baseline: application `210529788395aa7ec953ea94cb7192582498beb9`, previously clean.
This record covers local implementation; no Git commit, publication, production
interruption or deployment was performed.

## Behavior and evidence

- AC-6: real LangChain/LangGraph tests interrupt one and two concurrent `sleep 900`
  tools. Cooperative and cancellation-resistant handlers both allow the inserted
  message to complete within the test's two-second bound. Each call gets one paired
  interrupted error ToolMessage before the inserted user message. Late returns do
  not alter the checkpoint; neither operation is replayed. Default insertion still
  waits for a once-only side effect. Stale run IDs and HITL-paused runs do not cancel
  tools. See `tests/unit/agents/test_immediate_steering.py`.
- AC-3/AC-11: authenticated HTTP and SQLite queue tests verify `cancel_tools=True`
  reaches the identified run, invalid string flags get422, another owner gets403,
  retry identity is preserved, changing an acknowledged mode conflicts, definite
  rejection restores the exact original queued payload and FIFO position, and
  uncertain outcomes are not replayed. See `tests/integration/test_chat_inputs.py`
  and `tests/unit/gateway/test_chat_input_queue.py`.
- AC-7/AC-12: separate immediate and after-tool buttons, mode-specific spinner,
  acknowledged interruption status, localized tool result, attachment/slash/pending
  guards and multiple tool-result projection are covered in the changed Dashboard
  tests. Actual component interaction through ego-browser selected `one:true` and
  `two:false` independently; the expected status and tooltip appeared. At375px,
  the measured layout viewport and document width were both375 with no overflowing
  component elements. This used synthetic callbacks, not a real provider. Browser
  screenshot capture timed out or produced a black frame, so screenshots are not
  claimed as visual evidence.

## Gates

- `uv run --frozen --no-sync pytest -n 6 -m 'not live'`: **5045 passed,158 skipped**,
  28 dependency deprecation warnings,529.11s. Full XML evidence is stored outside
  the repository in `../ops/immediate-steering-full-results.xml`.
- Final installed-wheel app regression: **27 passed**, including queue/API plus six
  real-graph/admission cases; original Harness steering regression: **10 passed**.
- Dashboard focused suite: **26 passed**, including11 existing composer/draft
  cases. Broader chat-store/queue run: **71 passed** across13files. These overlap;
  counts are not added together.
- Application Ruff check/format: **1355 files pass**; mypy: **672 source files pass**.
  Harness mypy: **194 source files pass**. Dashboard ESLint:0errors,2existing
  ChatInput hook-dependency warnings. TypeScript and production build pass.
- i18n suite: **76 passed**. No GNU make is installed on this host; the applicable
  lint, format, typecheck, full non-live pytest and frontend build commands were
  executed directly. No hook/commit is claimed.
- Harness Ruff check and format pass for all359source/test Python files. The first
  forced-config invocation used paths relative to the application and missed the
  Harness per-file rules; the corrected invocation from the Harness root passes.

## Dependency integrity

Final dependency: `1.0.2.post4.dev4+interrupt.2`, wheel SHA256
`42a7985a82e78821f7e5e7f445e927accee20418de09c5fbfd9038fd3d722566`.
The final wheel, installed package and `uv.lock` hashes match. All371runtime
members match the runtime used for the full suite; interrupt.2 only refreshes
package metadata after documentation updates. Exactly three runtime files differ
from activity.3: `agent.py`, `manager.py`, `steering.py`. All368other runtime
members, including activity/history and provider behavior, are byte-identical.
`vendor/harness/interrupt-source-manifest.json` records every member hash and the
matching source/test archive hash. The source archive includes the original10
steering regressions and the six new real-graph/admission cases.

Immediate insertion interrupts the current call's wait and requests cancellation.
External or background processes can continue; both the model result and UI say
their stop status is unconfirmed. No external process termination is promised.
