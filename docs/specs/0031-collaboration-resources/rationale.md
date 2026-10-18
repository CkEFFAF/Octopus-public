# 0031 决策依据

Revision: 2026-10-18.4

## Context

The current product has several valid but disconnected boundaries. Inbound bytes use expert BackendWorkspace; project commands use a selected device; sync peers return tool text while team peers have room fan in. Device operation receipts and workflow run_events are mutable status views. Child threads exist but have no single durable delegation card in the source direct chat. Fixing prompts alone cannot express resource authority, execution uncertainty or delivery.

The user explicitly delegated architecture decisions and approved development after the event modeling discussion. We retain the existing stack and interrupted source patches; no new product interview is needed for choices already covered by that discussion.

## Options considered

1. Add more hints and copy child answers into the parent. This is small but cannot settle authority, unknown attempts, versions or durable delivery and increases context duplication.
2. Extend the current application with invocation records, resource versions/grants and append only events, referencing existing working chats and device receipts. This supports the reported user journeys with bounded migrations and compatibility adapters.
3. Replace the runtime with a distributed workflow engine, external event broker and global shared storage. This introduces operational components unsupported by current demand and still needs the same domain boundaries.

## Rationale

Choose option 2. Domain identity spans upload, dispatch and delivery, while actual device execution stays behind existing grants. Events record facts and provide replay; current state is still queried efficiently. The append only ledger and state transition commit together. A missed live update does not destroy the work record.

Use member_default for new delegations because the user clarified that beta behavior should serve the intended future product. Inherit remains an explicit option. Remove the old runtime function/schema replacement instead of preserving a long lived compatibility authority. A display name cannot establish execution location, so the effective device still appears on every receipt.

Use a distinct invocation identity because the existing job_id also selects asynchronous room behavior. Use content versions because an absolute path can refer to different bytes over time or on different devices. Retain old uploads with exact alias resolution, without treating any matching inbound substring as authority.

Choose a sequential029 migration after existing028, preserving deployed data and a monotonic schema watermark. Repeatedly folding unrelated domains into026 and replaying special reconciliation would make this change harder to reason about. The user's instruction permits changing that old guideline while retaining database compatibility.

Independent GPT6Luna high review identified shared child session crossover, cross store publication crashes and ambiguous cursor/transition races. The architect resolved these in revision .3 with per invocation session identity, atomic local snapshot finalization before publication commit, global cursor semantics and guarded status transitions. The reviewer did not edit source or supply implementation evidence.

Integration inspection then found that generating a fresh UUID on every public tool entry cannot prevent replayed provider tool calls from executing twice. Revision .4 names the hidden runtime tool call ID as the source, and lets the accepted host callback atomically return an existing receipt. This avoids adding a second replay authority or copying full child answers into invocation records. Explicit retry_of links intentional new attempts while preserving evidence.

Final integration also closed four boundary gaps within that contract. Server-registered resource references must enter the actual Processor request, not merely upload metadata or the dashboard. Snapshot availability is a recoverable projection: verified storage recovery restores the same immutable version without repeating execution. Bounded recent snapshots plus each event page's references preserve both new-task visibility and historical pagination; a fixed earliest-500 window cannot do that. Resource size follows the existing upload configuration, while document parsing has its own smaller cap, so valid large uploads do not fail when parser registration runs.

## References

Application AGENTS.md, specs 0022/0024/0028/0029/0030, current peer lifecycle code, BackendWorkspace, device transfer protocol and the read only cloud snapshot summarized in index.md.
