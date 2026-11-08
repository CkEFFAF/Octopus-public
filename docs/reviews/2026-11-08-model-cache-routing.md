# Review, model-cache-routing, 2026-11-08

**Reviewed by**: independent review agent (author: root implementation agent)
**Scope**: 48 backend, dependency, schema, spec and test files, uncommitted against HEAD; plus the pinned Harness patch/source manifest. Frontend has a separate reviewer; five preexisting preview files excluded.
**Verdict**: Approve

## Summary
The final candidate provides durable per-message host context snapshots, owner-scoped deterministic task routing and explicit cache-metric availability. All concrete findings from initial review and subsequent end-to-end traces are resolved. No remaining blockers or majors were identified in the reviewed backend, runtime or schema changes.

## Resolution verification

- Gateway and direct managed execution paths honor task routing, with explicit models and thread pins taking priority. Existing Gateway/recovery decisions remain frozen, effective saved work mode is included, and shared-text requests exclude caller routing metadata.
- Local ACP creates or validates the canonical owner/expert-bound thread before real manager preparation; mismatched existing thread scopes are rejected.
- Canonical usage preserves provider-reported zero versus missing cache data. Missingness survives re-normalization; mixed call totals remain incomplete. Both usage-ledger writers forward availability, and SQL totals/buckets/thread totals preserve it. Numeric cache_hit_percent remains for older clients; the updated UI uses availability to suppress unsupported percentages.
- Trajectory completion merges the complete usage dictionary into assistant payloads. Storage retains the boolean, and cache ratios require complete reported provenance for all input-bearing events.
- Harness request snapshots sum counters and combine availability with all-complete semantics. Request-inspection API int|bool values retain JSON booleans; legacy snapshots without provenance remain unavailable in the new inspector.
- SQLite and PostgreSQL migration 039 advance the watermark. SQLite ensure-column handling supports an existing column with a rewound watermark. Restart/reapply tests preserve previously recorded usage flags and counts. The new column is additive, defaults old writes to unknown, and keeps existing numeric counters and legacy response fields available; no destructive rollback/schema behavior was introduced.
- Stream closure immediately after a route notice clears its active-model reference.

## Private snapshot projections

A sentinel check confirmed message_input retains the private snapshot in the internal archive, as required for persistence. The authenticated user-history endpoint passes wires through an explicit history serializer that returns original user text and allowed attachment/context fields. Public sharing copies only role and public_text(content). Neither projected output contained the private sentinel; no reachable user-visible or public-share snapshot leak was found.

## Strengths

- Snapshot fingerprints, copy-only replay, empty snapshots, image isolation and compaction accounting work together to preserve historical request prefixes.
- Owner-scoped catalog selection excludes embedding and foreign-account references, and tests exercise settings access through machine credentials.
- Availability now remains explicit across live usage, request inspection, auxiliary calls, durable aggregates and trajectory ratios.
- The reviewed Harness wheel/source hashes match the supplied manifest: wheel `4d3182ba3ce98a81afe7dc67e80bdb5df7e1c70762fddc220a910edea3f0cd46`; source archive `efc0c3f2f4597488daacb62c2b7845f03d9ee6135a50e48f5945f079b037cb26`.

## Test coverage

Independent initial focused run: snapshot/routing, auxiliary generation, trajectory metrics and routing API isolation — **30 passed**.

Independent admission re-review: routing tests plus real ACP registration/preparation and early stream closure — **19 passed**.

Independent final availability/schema re-review:
`uv run pytest tests/unit/devices/test_request_inspection.py tests/unit/db/test_cache_usage_availability.py tests/unit/gateway/test_usage_record.py tests/unit/trajectory/test_metrics.py tests/unit/conversations/test_generation.py -q` — **22 passed**. This reran the previously failing migration-reconciliation case and covers restart, rewound watermark, preserved data and request-inspection boolean serialization.

The implementation agent additionally reports final DB/request-inspection checks at **185 passed, 1 skipped**, and the matching Harness source suite at **1880 passed, 36 skipped**; those broader runs were not independently repeated by this reviewer. No live model calls or production changes were made. Real-provider cache samples and frontend layout acceptance remain separate validation responsibilities.

## Expanded final review: session heat and quiet overviews (0049)

**Verdict**: Approve for 0049. All concrete findings in the expanded backend scope are resolved; no remaining blockers or majors were identified.

- Archive activity extraction traverses the actual tagged metadata and message wire.data wrapper without resolving content-addressed bodies. Real message_to_dict tests forbid body decoding. Legacy and archive seeding exclude generated cron, summarization and pinned-skill humans, and worker-thread prompts are excluded from historical seeding.
- Real inputs use owner/expert/thread scope and stable identities. Task command IDs are normalized and namespaced by task and operation; source IDs are no longer truncated into possible deduplication collisions.
- Queued inputs record the durable receipt's original created_at at admission. Delayed Gateway dispatch reuses the owner-bound receipt and steer:{command_id} HumanMessage ID; accepted steering uses the same source identity and original timestamp. Historical seeds share human:{message_id}, so they do not create another record.
- Ranking occurs before limiting results, preserves pins first and includes weekly input/task frequency. Job signals follow the existing stale/unavailable-observation rule. The frontend refresh uses a visibility gate, one pending request and interval/listener cleanup; detailed visual acceptance remains with the frontend reviewer.
- Automatic-only scheduling preserves manual/control-job behavior and existing lease-token/expiry checks. Automatic deferral removes only its own claim increment, retaining prior provider failures. Coalescing preserves a later scheduled due time; dirty-source revision validation and completion paths remain intact.
- Folded migration 039 contains matching SQLite/PostgreSQL activity DDL, foreign keys, uniqueness and indexes. The reconciliation helper idempotently ensures the new table even for an existing 039 watermark; prior cache-availability migration restart/data-retention checks still pass.

Final independent run:
`uv run pytest tests/unit/gateway/test_chat_input_queue.py tests/unit/conversations/test_heat.py tests/unit/db/test_cache_usage_availability.py tests/unit/devices/test_request_inspection.py -q` — **40 passed**.

An additional read-only integration exercise used the real queue repository and AgentManager.steer_stream with only the Harness response replaced. Duplicate enqueue, promotion into an active run and subsequent delayed Gateway activity capture produced **exactly one activity row at the original two-hours-earlier admission timestamp**, with the canonical HumanMessage ID. No model call, deployment or production mutation was performed.

## Expanded final review: execution-file delivery

**Verdict**: Approve. Both independently reproduced Major findings are resolved; no remaining concrete blocker or major was identified in the final file-delivery delta.

- FileDeliveryMiddleware preserves canonical Harness ConversationModeMiddleware authorization before publication, including Ask/Plan restrictions and the existing configurable exceptions/path semantics. Non-intercepted tools, missing execution contexts and /.agent/ paths continue through the original handler. Chained Ask/Plan tests prove neither publisher nor native terminal runs when denied.
- Execution-file publication reuses ResourceService scope checks and the persisted execution context, verifies complete bounded transfer bytes against declared size/SHA256, and publishes a snapshot before exposing metadata. Cross-owner/expert/thread paths do not gain authority from a model-supplied file path.
- IM projection derives owner/thread scope from the actual managed request or authenticated HITL context. The loader re-fetches the resource through owner_view, verifies exact version and published state, and uses ResourceService.bytes for current source authorization and snapshot-integrity checks. It does not trust a returned content URL or model-supplied media bytes.
- Source-content authorization now covers execution/device/local resources with persisted contexts, rechecks their owner/expert/thread context and performs the existing current-policy fs.stat call before returning bytes. This retains current device grant/read-policy enforcement for published device artifacts.
- Only transient outgoing IM events carry the base64 attachment; the tool/checkpoint result stays resource metadata. A project_stream regression verifies one actual emitted media payload equals the source bytes and has no unauthenticated URL dependency.
- Dashboard enrichment/attachment projection and IM projection reject failed ToolMessages. Plain missing-file/error output no longer invents a media path, including the reported no-such-file case. The existing model sees a failed ToolMessage rather than a fabricated successful file card.

Independent final verification:
`uv run pytest tests/unit/agents/test_collaboration_resources.py tests/unit/gateway/test_tool_media.py -q` — **61 passed**.
`uv run pytest tests/unit/gateway/test_stream_project_tools.py -q` — **3 passed**.

These 64 checks cover resource boundaries, verified snapshot delivery, real IM stream projection, canonical mode gating and failed-result suppression. No production conversation was modified, no live model/provider call was made and no deployment was performed. Existing production screenshots/history were treated as diagnostic evidence, not as proof that the undeployed candidate has already repaired historical files.
