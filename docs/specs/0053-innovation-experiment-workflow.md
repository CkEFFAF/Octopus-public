# GPU innovation iteration and accessible experiment files

**Date**: 2026-11-12
**Status**: In Progress

## Summary

Build on the published Graph engine to keep approved GPU research moving across conversations. Use Grok 4.7 for design, prioritization and analysis, and DeepSeek for implementation and routine work. Expose experiment manuals, memory and reports in the expert profile and chat. Make Graph configuration readable without requiring JSON editing.

## Context

The current task classifier checks code words before reasoning, so an architecture or experiment analysis mentioning code is routed as coding. Graph agent nodes already pin a model per stage, persist activations and retain accepted device Jobs. Expert profile files only list root Markdown and chat files only show conversation outputs. The settings toolbar overlaps scrolling content and the inspector presents common configuration as raw JSON.

The user has authorized automatic experimentation under the existing experiment and server maintenance rules, specifically without displacing other users' GPU work. Those original rules remain authoritative. Source identity is GPU expert `27N3HD`, device `01M4W2V33NV33E8DSNXN0PQ9ZB`, project directory `/home/wjh/workspace`. Existing source documents are accessed through BackendWorkspace, not through GPU shell paths.

## Requirements

1. AC1: Explicit design, experiment planning, decision making and result analysis classify as reasoning even when code words occur. Ordinary implementation remains coding. Manual selections and owner task preferences retain precedence.
2. AC2: A validated importable innovation Graph chooses Grok 4.7 for scientific judgment and DeepSeek for implementation, records real observations and report links, waits without occupying a model turn when resources are unavailable, and repeats approved work within the engine's existing budgets.
3. AC3: A persistent queue records proposal approval, prerequisites, priority, scientific rationale, baseline, metrics and optimization direction, version relationships, execution receipts and report paths. It rejects cycles, unmet prerequisites, duplicate concurrent claims and unapproved work. Unknown work is reconciled, never resubmitted automatically.
4. AC4: Existing experiment rules, maintenance rules, domain knowledge, dataset priors and manuals are read before planning. Availability checks cannot kill, evict or alter another user's processes. Lack of clear safe capacity causes waiting.
5. AC5: An owner can persist named expert or project file pins, read/edit their current contents, and access the same list from expert profile and chat across conversations. Project pins freeze an explicit local/device source. Existing ownership, execution authority and file conflict protections apply.
6. AC6: Node model selection, input/output bindings and common configuration are forms. Raw JSON remains optional advanced configuration. Graph settings have compact actions and scrolling fields without overlap, use the existing theme and remain usable at narrow widths.
7. AC7: Decision stages can explicitly delegate through the existing ACP tool to an enabled local advanced Agent. Missing configuration or a failed ACP invocation is visible, never fabricated as a completed decision.
8. AC8: A silent model transport has a finite idle timeout and bounded retries. Continuous streaming can outlast the idle interval; cancelling a blocked model turn does not cancel accepted GPU Jobs.
9. AC9: Every queued task has a task numbered, versioned design document before implementation. It names code files and interfaces, concrete implementation and validation steps, comparison protocol, dependencies, risks and resource constraints. Independent model review and its real invocation evidence are linked and frozen with the document hash. Changes require a new review. DeepSeek implements the reviewed design; it cannot invent a different experiment at execution time.
10. AC10: The canvas shows two readable business workflows, design and review (5 nodes) and execution and reports (9 nodes). Identity, revision, document and code hash checks are deterministic helper logic. Agent files have a single header action for selection and confirmed bulk unpinning, with no per row delete buttons. Unpinning never deletes source files.

## Decision

Improve the existing engine in place. Keep Graph definitions and runtime state in the existing tables. Keep the portable queue alongside experiment reports in the GPU project, using atomic writes, locks and revision checks. Store owner/expert file pin metadata in existing settings with compare and set. No database schema or new dependency is required.

**Implementation skills**: architect, develop, frontend-design.

## Options considered

Prompt only automation cannot enforce queue admission or retain reliable stage state. A separate workflow server adds unnecessary infrastructure. Existing immutable Graph versions, durable Jobs and waits already supply the needed execution control.

## Feature design

The design workflow reads original rules and the authoritative backlog, writes concrete versioned task designs, obtains an independent review, and freezes the design, review and invocation evidence before registering a queue entry. It runs independently of GPU availability. A fixed configured research scope plus the original owner approvals governs automatic approval; a model supplied scope is not sufficient. Pending, rejected and blocked designs remain proposals.

The execution workflow claims a reviewed version, has DeepSeek implement its fixed design, obtains an independent code review against the design and an actual file manifest, then runs through deterministic admission checks. Resource loss waits in the same persistent device Job without model calls or duplicate launches. Analysis produces real receipts and reports; the archive operation chooses its transition from the actual ledger state. A missing report or uncertain effect remains explicitly pending reconciliation.

Both workflows use the existing 30 minute scheduler with overlap skipped. Execution checks capacity before claiming, so a busy execution check calls no model, while design work can continue separately. One execution run records one version. Queue payloads require design_path, design_revision and design_review_path. Approval freezes the SHA256 of design, review and evidence; claim and run recheck them. Code review binds an implementation manifest and every file hash. Confirmed process launch errors become failed with returncode null and a real error log; uncertain effects after launch remain blocked. Server shutdown removes and closes only its own log handlers.

During the owner's budget limited validation, live Agent nodes use DeepSeek, schedules and training are disabled, and the design registrar receives no authorized approval scopes. DeepSeek test output is not recorded as completed advanced review. The preferred production model remains Grok 4.7 when the owner restores it. External 429 responses are retained as failed test evidence, not successful expert acknowledgement.

Reports record inspiration and evidence, hypothesis, baseline and comparison protocol, code/config/checkpoint identifiers, execution receipts, observed phenomena, encountered problems and solutions, evaluation logs, analysis, recommendations, and previous/next report paths. A missing result or incomparable evaluation is never called an improvement.

Model refs are resolved from the owner's actual provider catalog. The current verified refs are `OpenCode Go (Compatible)/grok-4.7` and `OpenCode Go (Compatible)/deepseek-v4.1-flash`. Graph stage selection is explicit, independent of keyword routing. Account reasoning/research and coding preferences are configured through the existing routing API.

Pins contain a stable ID, title, scope and path. Expert paths are workspace relative. Project pins additionally save target kind, device ID and working directory; opening creates an authenticated execution context rather than reusing a different conversation's source. GET/PUT `/api/agents/{agent_id}/pinned-files` validate ownership, bounds and revision. No credentials or document contents are stored in pin metadata.

UI direction: preserve the app theme and font, with white/slate surfaces, blue action accents, clear 14px controls and 12px supporting text. The workflow canvas remains the primary surface. Settings actions occupy a compact fixed area; configuration scrolls separately. Inspector groups identify task, model, context and bindings. Avoid decorative panels and large empty gaps.

| Value | Source |
| --- | --- |
| Model for each stage | Explicit Graph node model using owner usable provider catalog |
| Approval and permitted operations | User's experiment rules plus explicit queue approval |
| Priority and potential | Grok analysis persisted with rationale, eligible dependencies first |
| Resource availability | Fresh device observations under existing maintenance rules |
| Completion and improvement | Actual Job receipts and matched baseline metric evidence |
| File content | BackendWorkspace or fixed authenticated native execution context |
| Pin revision and visibility | Owner/expert settings record, CAS and ownership checks |
| Active stage and wait state | Existing persisted Graph run and activation records |

## Build plan

1. Fix reasoning classification precedence and add meaningful regression tests (AC1).
2. Provide queue helper, innovation Graph and operating guide; exercise approval, dependency, locking and report transitions (AC2, AC3, AC4).
3. Add persistent file pins and profile/chat reading and editing (AC5).
4. Improve settings and inspector forms and verify responsive rendering (AC6).
5. Run focused tests, dashboard build and Linux make all. Deploy an isolated release directory, preserve data and accepted GPU Jobs, configure actual models/pins/Graph through authorized APIs, and verify live behavior (all ACs). Windows CI completion is not a deployment prerequisite per the user's instruction.
6. Repair the matched Harness source, build a reviewed wheel with finite model transport waits, include a replayable patch and source manifest, and verify silent and active streaming plus cancellation (AC8).

## Consequences

The Graph remains bounded; paused runs expose explicit continuation rather than an unbounded promise. Scientific judgment is model work, while approval and queue integrity have deterministic validation. Original manuals remain the source of operational rules and can be adjusted through the new file entry points.
