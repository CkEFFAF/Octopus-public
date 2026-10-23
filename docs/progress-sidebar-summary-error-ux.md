# Sidebar, overview language and error details

The user reported a hidden conversation rail, English overview prose and a long
list of identical diagnostic disclosure widgets. This follow-up keeps existing
conversation selection and manual edits intact.

Implemented:

1. A permanent conversation-list control in the desktop chat header, including
   the empty-chat header. Selecting Chat in WorkspaceNav reopens the rail while
   retaining the current conversation URL. Saved collapsed preferences remain
   respected; the recovery action no longer requires finding a hover-only edge.
2. Auxiliary title, brief and digest calls explicitly use the owner's stored
   locale. Human-readable stages must be phrases rather than snake_case labels.
   Older English overviews offer an explicit language-refresh action; manual
   objectives are preserved. Goal, scope and progress use compact cards.
3. Chat, overview and batch errors use concise explanations with a Details
   button. Diagnostics and copy controls appear in a modal. Batch failures are
   grouped by reason, with counts and retained-sample counts instead of one
   indistinguishable disclosure per failed conversation.
4. The original 0035 contract specifies an input budget of 12,000 tokens, but
   generation compared UTF-8 bytes with that token limit. Calls now use the
   shared CJK-aware and JSON estimates, a 50 percent reserve and the existing
   model/context/output limits. This is an estimate, not a provider tokenizer
   measurement. Truly oversized requests still fail before invocation and
   expose only numeric input estimates/limits, never prompt content.

Evidence so far:

- Final focused backend and i18n tests: 110 passed, including long Chinese input below
  the token limit, genuinely oversized rejection, locale and numeric diagnostics.
- Final UI regression group: 20 passed across 8 files; TypeScript passed.
  The last presentation/copy changes and off-event-loop preference read are
  included in the final focused reruns.
- make all PYTEST_JOBS=8: Ruff and strict mypy passed; 5127 tests passed and
  157 skipped. The final preference-read scheduling adjustment subsequently
  passed the focused 110-test group; CI will cover the final commit as well.
- Actual isolated app, synthetic data: collapse survives refresh, a visible
  recovery control remains, clicking Chat reopens the list without changing the
  conversation URL. An old English objective, scope and stage were regenerated
  and persisted in Chinese. Details modal showed the saved safe diagnostic.
- Thirty fictional batch failures render as two explanations (24 input-budget,
  6 format errors), with two Details buttons and no diagnostic JSON on the page.
- Browser TaskSpace 16 was finished once after final verification. Some native pointer
  targeting was unreliable; DOM actions followed observed failures and hit tests.
  Screenshot capture timed out, so no screenshot-based visual pass is claimed.

The grouped Details modal showed 24 failures with 14 retained samples, an
explicit sample-count explanation, a visible copy action and bounded scrolling.

The local QA frontend/backend were stopped after the browser space was finished.
Pending: normal commit hook, PR and release verification.
No production data has been regenerated in this follow-up.
