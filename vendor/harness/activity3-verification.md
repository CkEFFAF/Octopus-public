# Harness activity.3 append checkpoint fix

The public `HarnessAgent.aappend_messages` now updates as `langgraph.graph.START`. A completed checkpoint with multiple last writers no longer requires LangGraph to guess a writer. Messages enter the existing messages reducer immediately; no model or tool is invoked. A subsequent normal Harness call accepts the appended history.

START schedules entry tasks without running them. The helper therefore records the exact append checkpoint step under `octop_history_append_step`. A pending checkpoint is accepted only when its source/step match this marker, its next/task names exactly match the public graph START edges, and no task has interrupts or errors. Any other pending work raises RuntimeError before the state update. Dynamic interrupts or failed tools can add pending writes without advancing the checkpoint step; explicit task checks protect that case. Hosts must serialize same-thread writes. No application monkeypatch or concrete middleware node name is used.

Regression evidence:

- `regression-red.log`: exact activity.2 method loaded from its source zip in memory, then public append against a real completed parallel-writer checkpoint fails with `InvalidUpdateError: Ambiguous update, specify as_node`.
- `regression-green.log`: 74 public facade / checkpoint tests pass. Seven new cases cover real parallel writers; real Harness completed turn, repeated appends and next call; SQLite close/reopen in a fresh Harness instance; dynamic interrupt, static interrupt-before, failed work and external-update invalidation. Rejected appends preserve checkpoint config, values and task identities; interrupted work still resumes through Command(resume).
- `lint.log`: all checks passed; 357 files already formatted.
- `typecheck.log`: strict mypy passes for 194 source files.
- `tests.log`: 1846 passed, 39 skipped. This uses PYTHONPATH pinned to this worktree's src. Optional/environment skips remain at the activity.2 count.
- `wheel-tests.log`: 91 passed, with import origin explicitly verified under the isolated Harness venv's site-packages, version activity.3. Covers append, native task activity, run events, request snapshots/sources, model factory tool text and LangGraph protocol.

The first full attempt had 1845 passed / 39 skipped and one version assertion because the isolated venv still contained activity.2 distribution metadata. Refreshing an editable install was unavailable because its local build environment lacked editables. Installing only the locally built activity.3 wheel with --no-deps fixed that environment mismatch; the complete source gate was then rerun and passed. Both diagnostic logs are retained. No production or App environment was installed or edited.

Artifact directory: `D:/Agent_Workspace/octopus/ops/workspace-0034/harness-activity-3`

- Wheel: `octop_harness-1.0.2.post4.dev3+activity.3-py3-none-any.whl`
- Wheel SHA-256: `9af63f12f5813ab490c7691e31bddfb2918c214ef509ea50eb851fe4d8f0e4a7`
- Source zip: `harness-source.zip`
- Source zip SHA-256: `3a9100e62bf891e35cb838b7ba5e0fff4164aa1dcb2ffbd89cb0ea21a05cec4f`
- `source-manifest.json` records every package and source-archive member hash, production baseline hashes and activity.2 delta. All 371 package members match current source. Only agent.py differs from activity.2. Of production's 370 files, 367 remain byte-identical; the three changed existing files are __init__.py, agent.py and observability/run_events.py, and the one added package file is middleware/native_task.py, already present in activity.2.
- Actual activity.3 source changes: src/octop_harness/agent.py; tests/test_agent.py; new tests/test_agent_append_checkpoint.py; pyproject.toml version; README.md; CHANGELOG.md. The source archive additionally includes the pre-existing Makefile and uv.lock that activity.2 omitted; these files were not changed by this fix.

The existing App callers are cron text delivery and slash history. The Harness fix is ready for the App coder's vendor/lock integration and real isolated Cron acceptance. This Harness-only task does not claim that App integration or real Cron end-to-end verification has happened. No Git operation, App edit or production deployment was performed.
