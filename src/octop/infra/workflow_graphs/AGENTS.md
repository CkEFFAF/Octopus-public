# Workflow graphs

Approved contract: `docs/specs/0052-configurable-workflow-graphs.md`. User guide and importable examples: `docs/workflow-graphs.md`, `docs/examples/workflow-graphs/`.

- `models.py`, `state.py` and `planning.py` own definition validation and pure branch/context transitions. SQL stays in `infra/db/repos/workflow_graphs.py`; schema changes need paired SQLite/PostgreSQL migrations.
- `service.py` is the owner-scoped authoring/control boundary shared by API and Agent tools. Published versions are immutable, runs pin versions, draft writes use revision checks. Runtime identities never come from event data.
- `runner.py` observes durable activations. Agent dispatch reuses canonical conversation locks and CronDeliveryService; scripts use ExecutionService and persistent Jobs on the frozen execution source.
- Keep accepted-work capacity separate from activation status. Pause/cancel/budget exhaustion prevent new dispatch and retain accepted Jobs unless their cancellation is explicitly requested. Uncertain effects remain unknown; receipt reconciliation never resubmits work.
- `middleware.py` projects model request copies only. Preserve system instructions and complete tool-call/result chains; never delete history or use context injection to broaden authority.
- Event registrations have one consumer per activation, callbacks are scoped and bounded, and private credentials stay out of ordinary inspection. Ready and waiting scans must rotate fairly beyond one batch.
- The dashboard source is `dashboard/src/pages/WorkflowGraphs/`. Keep the viewport available for the canvas; workflow actions live in the settings Drawer, the inspector opens on selection, and run history starts collapsed. Fence asynchronous edits against changed graphs/nodes and newer field input.

- GPU innovation examples and design admission follow `docs/specs/0053-innovation-experiment-workflow.md` and `docs/examples/workflow-graphs/gpu-innovation.md`. Numbered designs, review evidence and implementation hashes are checked by the portable helpers; the original project task queue remains authoritative.

Run `uv run pytest tests/unit/workflow_graphs tests/integration/test_workflow_graphs.py -q` and the dashboard's WorkflowGraphs tests for focused verification. Repo-wide gates remain in the root `AGENTS.md`.

_Drafted by /sync from the introducing change, worth a quick human pass._
