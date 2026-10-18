# 0029 Attachment resources and device routing

Status: Historical diagnosis/proposal; current implementation and acceptance are governed by 0031.
Date: 2026-10-17
Mode: ENHANCEMENT / CROSS-CUTTING
Scope: Original diagnosis retained. Implementation is authorized and governed by [0031 revision 2026-10-18.4](0031-collaboration-resources/index.md); this does not authorize production deployment.
Related scope row: None present in this checkout. Extends 0015 and 0022; preserves their execution and expert-storage boundaries.

## Summary

Make uploaded attachments readable independently of the selected execution device. Centralize attachment resolution, authorization and document extraction behind a bounded AttachmentService, with one tool contract for private chats, team hosts and delegated readers. Retain existing BackendWorkspace storage and immutable ExecutionContext. Add explicit transfer only for operations that actually need the original bytes on a device.

## Evidence and diagnosis

- Production conversation: GPU expert `27N3HD`, thread `thr_01M54J707VQ9Y4VD5QABWN62HH`, title 论文实验. Read-only database inspection found the PDF hint at message 77; message 79 rejected `read_file` and recommended a shell. Subsequent shell operations ran on the GPU and searched for a controller-stored file.
- The controller attachment exists: 4,342,836 bytes, PDF signature. A read-only probe using the actual bundled application Python plus its packages extracted text from all 12 pages, totaling 48,654 characters, through the already-installed pypdf. This proves text extraction availability for this document; it does not establish formula/table fidelity.
- `api/routers/uploads.py` saves through the workspace abstraction but returns storage paths as model-facing attachment hints. `infra/gateway/media/attachment_hints.py` supplies non-image files primarily as path hints.
- `infra/agents/middleware/binary_read_guard.py` blocks binary reads and recommends shell extraction without accounting for the resource location or whether the named tool exists in this run.
- Harness `StorageExecutionBackend` routes `/.agent/` file operations to expert storage, while commands delegate to the project execution backend. That separation is intentional. The same path string does not become a real directory in the device shell.
- `infra/agents/manager.py` registers `build_room_attachment_tool` only under `if team_host`. The tool already downloads bytes through BackendWorkspace and calls `infra/knowledge/parse.py`. The private-chat surface lacks the equivalent integration.
- Existing room extraction parses the whole document on each character-range read, returns broad unreadable errors and lacks page provenance. This is reuse material, not the complete target contract.

Root cause: attachment ownership/location and execution target are separate concepts, but the model-facing interface exposes a path and a shell fallback as though both share one filesystem. Product surfaces supply different document capabilities. Recovery relies on model inference instead of an available, authorized resource operation.

## Requirements

1. **AC1 — Existing attachment readability.** A private chat on a remote execution target can read a previously uploaded text PDF through controller storage without project commands, device connectivity, re-upload or permission changes. Existing attachment messages remain usable.
2. **AC2 — Same capability across surfaces.** Private chat and team-host tools use the same service. Delegated readers receive access only to the attachment references explicitly included in their dispatch and valid for the requester; no implied access to the parent workspace.
3. **AC3 — Authenticated resource resolution.** Every read verifies requester, conversation/room association and current grant, including cached results. Resource identity is separate from backend key and device path. The resource ID or content hash alone never grants access.
4. **AC4 — Bounded, attributable output.** PDF output includes original resource identity/version, page numbers, parser identity, warnings and pagination. Extraction runs with enforceable time, memory, page and output bounds outside the web event loop. Empty extraction is classified; it is not reported as a successful full read.
5. **AC5 — Useful recovery.** Binary read rejection points to an actually registered attachment operation for a recognized upload. Errors distinguish not found, denied, unsupported format, encrypted document, parser unavailable, extraction failed, OCR required and timeout. Retrying the same permanent failure does not trigger filesystem searches.
6. **AC6 — Deliberate materialization.** When raw bytes are necessary on a device, a separately authorized operation resolves the current immutable ExecutionContext, writes into approved runtime scratch space, verifies the source version/hash and returns a device-specific receipt. Work-mode policy governs these writes; project read-only mode never silently becomes permission to write a project file.
7. **AC7 — Durable status and safe cache.** Uploaded, processing, ready and failed states describe distinct stages. Cache keys include source version/hash plus parser version/options; authorization is rechecked on every use. Failure is visible to tools and UI, with a retry action for transient failures.
8. **AC8 — End-to-end proof.** Verify upload → stored attachment → authorized tool → extracted pages for private chat with remote execution and an offline device, then team/delegated access and denied cross-user access. Cross-platform transfer verification is a separate gate before enabling materialization.

## Decision

Deliver in two phases. First unify reading through a small AttachmentService over the existing storage and parser implementations. Then introduce durable resource IDs, parse state/cache and optional device materialization. Do not make automatic file replication a prerequisite for reading.

Keep the current Python/FastAPI application, BackendWorkspace and ExecutionService. No new queue, object-storage provider, distributed filesystem or protocol migration is required for this proposal. A bounded subprocess parser can run under the current service; it need not be a separate deployed microservice.

## Design

### 1. Resource reference

Use an opaque `attachment_id` for new uploads, associated server-side with owner, conversation/room, source expert store, backend-relative key, MIME, size and immutable source version/hash. An optional model-facing `attachment://<id>` representation is an application identifier, not a shell path and not an access token.

For old messages, resolve the recorded upload metadata under its authenticated source workspace and conversation. Do not accept an arbitrary host absolute path or strip an `inbound/` substring from an unrelated path as proof of ownership. Introduce IDs lazily without moving original files or rewriting conversation prose. New tool calls resolve metadata server-side; the model supplies neither owner nor backend credentials.

### 2. Common attachment reading

Expose `read_attachment` with a resource reference and bounded page/range arguments. Keep `read_group_attachment` as a compatibility adapter. The short-term resolver may accept a validated legacy upload reference; its authorization still uses the current authenticated conversation and stored attachment association.

The service retrieves bytes through BackendWorkspace, selects a parser by detected type and declared MIME, and returns structured text and provenance. Extract the existing parsing primitives into a shared document module if needed, retaining `knowledge.parse.parse_document` as an adapter so knowledge and chat do not grow duplicate parser implementations. Do not create a reverse dependency from the document domain into agent orchestration.

For PDFs, preserve page boundaries before flattening for older callers. Reuse pypdf for text-layer extraction. Low/empty text pages may request a configured OCR capability; parse errors or encrypted documents are classified before deciding whether OCR is appropriate. Formula, table and figure inspection can request rendered pages through an available visual reader. Plain extracted text is not a promise of layout fidelity.

Run potentially expensive parsing in a killable worker process with bounded input/output and timeout, retaining the existing upload cap and defining service limits explicitly during implementation. A timeout around `asyncio.to_thread` alone does not terminate parser work. Avoid reparsing the full PDF for every page/range read.

### 3. Routing and capability discovery

Attachment tools operate on resources and their authorized storage, independently of ExecutionContext. Project file tools and shell commands continue to use that context. Expert memory/skills keep `/.agent/` semantics.

BinaryReadGuard remains a guard against putting raw binary in model context. For a recognized, authorized upload it names `read_attachment` and returns the attachment reference. It does not recommend an unavailable tool or a device shell for a controller resource. Unrelated project PDFs retain their project location; this proposal does not silently reinterpret them as controller uploads.

The model receives attachment metadata and supported operations, without controller host paths as its primary interface. Structured errors include a stable code, source scope, retryable flag and available next action. The runtime can route valid reads deterministically; model wording is supplementary.

### 4. Optional device materialization

Only workflows requiring original bytes invoke `materialize_attachment`. Use the existing authenticated device transport and immutable ExecutionContext, with attachment-read and destination-write policy checked separately. A device path is valid for that device/context only.

The receipt records attachment ID/version/hash, device/context ID, resulting path, byte count and expiry/cleanup policy. Copy via temporary file plus verified completion where supported. Interrupted copies do not produce a ready receipt. Retries are idempotent for the same version and target. No shell guessing, credential exposure, cloud `/root` access, or implicit execution-target switch is introduced.

### 5. State, caching and observability

Durable parse states distinguish uploaded, queued/processing, ready, OCR-required and failed. The UI can show concise user-facing labels while retaining detailed failure codes in receipts. An attachment can remain uploaded when parsing fails.

Cache parsed derivatives by source version/hash and parser version/options; keep ACL checks outside the cache. Do not expose global hash lookups. Record attachment ID, conversation/run, parser, pages, duration, cache result and error code, with no document text or credentials in operational logs. Reuse short status receipts instead of replaying large event histories into context.

## Build plan

1. **Phase 1: reproduce and unify reads** (AC1, AC2, AC8). Add a private-chat/remote-target regression using a real text-layer PDF. Extract the shared service from room attachment reading, connect private/team surfaces, and verify the real deployed parser environment. Preserve existing files and tool aliases.
2. **Phase 1: recovery and bounded output** (AC3, AC4, AC5). Resolve legacy references with ownership checks, return paginated page text, isolate parser work and replace unreachable shell hints with the available tool. Verify no project/device operation occurs in the read flow.
3. **Phase 2: durable identity and derivatives** (AC3, AC4, AC7). Add new upload IDs, message associations, state and cache. Follow the repository's released-schema migration rules with paired SQLite/PostgreSQL migrations; keep old API fields as compatibility fields while adapters migrate. Verify repeated reads reuse extraction and revoked access cannot read a cached result.
4. **Phase 2: delegated references** (AC2, AC3, AC8). Pass explicit per-dispatch resource grants with lifecycle and current authorization. Verify child agents can read those resources without parent workspace access.
5. **Phase 2: optional transfer** (AC6, AC8). Add context-bound materialization and receipts only after reading is stable. Verify approved scratch writes, read-only project behavior, offline target handling, hash mismatch, retry and cleanup on Windows/Linux.
6. **Integration gate** (all AC). Run repository checks appropriate to the touched layers, then prove the actual upload/read flow and the existing 12-page production attachment read through the application tool. A direct parser probe alone does not satisfy end-to-end completion. Deployment remains separate from this proposal.

## Consequences

- A remote/offline GPU no longer blocks controller-stored document reading.
- Reusing existing storage and parser code reduces change surface. Most phase-1 work belongs in management integration; a device client upgrade is unnecessary unless a newly required transfer operation is absent.
- New identities/state require metadata migrations in phase 2; original attachment bytes stay in place.
- Simple extraction does not guarantee faithful equations, tables or figures. Visual/OCR support is capability-dependent and must report its limits.
- Prompts and skills remain useful instructions, but availability, authorization, routing and recovery become executable contracts.

## Follow-up / unresolved decisions

- Proposed, not accepted or implemented. No scope row exists to advance.
- Set concrete parser resource/page/time limits from deployment capacity and representative files before shipping AC4; they are not guessed here.
- OCR/visual provider and cost policy remain capability-dependent. They do not block reading this existing text-layer PDF.
- Audit current device transfer APIs before adding a transport operation; do not duplicate an existing binary upload capability.

## References

- Local code: `api/routers/uploads.py`; `infra/gateway/media/{inbound_store,attachment_hints}.py`; `infra/agents/{manager.py,middleware/binary_read_guard.py,teams/attachments.py}`; `infra/knowledge/parse.py`; `infra/execution/backend.py`.
- Existing specs: [0015](0015-device-execution-and-context-inspection.md), [0022](0022-expert-store-boundary.md).
- [pypdf extraction documentation](https://pypdf.readthedocs.io/en/stable/user/extract-text.html): text/OCR distinction, layout limitations and memory considerations.
- [MCP resources](https://modelcontextprotocol.io/specification/2025-06-18/server/resources): URI-addressed resources as a design reference only; adopting MCP is not required.
