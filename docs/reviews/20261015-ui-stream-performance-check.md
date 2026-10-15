# UI stream performance check — 2026-10-15

Date: 2026-10-15  
Reviewer: gpt-5.6-sol, high reasoning; read-only review separate from the implementation context.  
Baseline: `HEAD 11492b58b8af0d467e17d16d022f57cf2d8d0e20` on `hotfix/1.0.2b12`.  
Scope: the current tracked working-tree changes for the expert-runtime chat-page input, scrolling, and button latency issue.

## Verdict

No actionable finding in the bounded diff.

| Severity | Count |
| --- | ---: |
| Blocker | 0 |
| Major | 0 |
| Minor | 0 |

The change reduces repeated work without dropping stream state or changing the reviewed interaction semantics:

- `chatStore.ts:488-525` reduces every frame immediately and updates the imperative snapshot immediately, while subscriber publication is coalesced to a 32 ms window. Lifecycle and terminal calls use the immediate path, which cancels the pending timer first. `cancelStream`, session removal/detachment, focus switching, `done`, `error`, HITL, host terminal status, socket failure, and watchdog sealing were traced; no delayed terminal rebound or orphan timer was found.
- `messageGrouping.ts:149-209` reuses a group only when the first message object, group kind, length, and every message object are unchanged. The changed message is therefore confined to its owning group. `MessageList.tsx:302-311` preserves prior groups, and `AssistantTurnView.tsx:352` can safely use shallow memoization. The `teamWrapup` first-item check is equivalent to the former `some` check because the grouping loop maintains homogeneous wrap-up groups.
- The media, file-path, todo, and citation WeakMaps are keyed by immutable message objects. Every reviewed `chatStore` path that changes content, tool arguments/output, attachments, HITL state, or status replaces the affected message object. Media and path caches additionally partition by effective owner, so the same message rendered for another expert does not reuse owner-bound URLs. Weak keys do not retain discarded messages; per-message owner maps remain bounded by the owners used to render that message.
- The rewritten path scans in `useChatFileDetection.ts:83-122` and `toolMediaBlocks.ts:694-730` preserve the prior pattern priority and candidate boundaries while removing repeated unanchored slash backtracking. Existing edge behavior, including quoted labels and mixed file/path priorities, is covered by the updated cases.
- `index.tsx:374-375, 943-982, 1046-1072, 1123-1150` reads current messages from a ref only inside event handlers. Thread/agent identity, stream/HITL gates, policy, navigation, and error translation remain ordinary callback dependencies. Regenerate, approval/HITL auto-resume, and fork therefore use current message content without capturing a per-token array. `useChatSend.ts:96-106` removes the omitted default-array identity churn without changing selected-target semantics.
- `ChatFilePreviewContext.tsx:24-31` memoizes the provider value around callback props; the supplying callbacks are stable hooks, and the interaction regression covers consumers receiving new actions.

## Verification evidence

- Focused integrated Vitest run: **19 files, 129 tests passed**. This includes stream batching and terminal cleanup, pending aliases, team ordering, HITL, device targeting, history, message-group identity, cache invalidation, file detection, and the performance regressions.
- Neighboring interaction regression: **10 files, 59 tests passed**. It covers auto-scroll, chat input, process summaries, queue behavior, HITL layout, and speaker rendering. The two runs are disjoint, for **188 tests total**.
- TypeScript project check: `npx tsc -b --pretty false` exited 0 in this review.
- `git diff --check HEAD` reported no whitespace error. The focused ESLint run had no error; its one `react-hooks/exhaustive-deps` warning at `index.tsx:725` is present at the fixed baseline and is outside this diff. The parent verification also reports Prettier passing.
- Recorded performance probes: 300 token notifications reduced from 300 to 1; five updates over 120 settled tool messages repeated 0 completed-turn recalculations and 0 parses of the 69 KB settled output; a 72 KB slash-heavy path scan completed in sub-millisecond to low-millisecond time in the recorded runs. These are regression probes, not user-perceived latency measurements.

## Limits

The Vitest configuration aliases project modules and replaces CSS imports with an empty stub, so it proves logic and render behavior but not production CSS integration. This review did not run the production frontend build or drive a live expert chat in a browser, and it does not claim that the reported online latency has been observed as resolved. Timing assertions are deliberately avoided because local benchmark duration varies; the durable evidence is the reduced notification/recomputation counts and preserved outputs.

## Subsequent coordinator verification — 2026-10-16

After the automatic approval service recovered, the coordinator ran the normal `npm run build` successfully and reran **71 core tests in 8 files using the repository's default Vitest configuration**, without the ignored TypeScript/CSS substitutes. Evidence: `.cache/ui-perf-production-build.log` and `.cache/ui-perf-standard-vitest.log`. Browser attachment still timed out, so live input latency remains unobserved. This note records later verification and does not extend the independent review scope.
