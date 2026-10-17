# Memory correction integration evidence

Baseline: management f98287ea; harness e31ca231. Spec0023 AC1..AC6.

The feature uses existing namespace-bound octop-memory1.0.0 fact operations.
It adds no generic SQL tool, host-file mutation path, cross-agent selector or
physical history deletion. Updates/deletes require exact current content and a
reason; replacement and provenance retirement metadata share a transaction.
Old atoms/raw events/audit remain available through host management.

The harness normal pre-commit make all gate passed Ruff, strict mypy191 source
files, and1752 tests (31 conditional skips). Real graph verification found a
first-worker-connection transaction initialization issue; binding the thread's
connection through the public read API before nesting transactions resolves it.
Cold installed-package integration found an import cycle; the tool dispatch
import now occurs when the tool runs. The full standard gate passed again after
that correction. No hook was bypassed.

Management installs the actual immutable harness archive at
3a82d260b7a6faaf8d4a888d71424c559727327d with a uv-generated SHA256 lock. Ninety
focused installed-package, tool catalog and i18n checks passed. Memory-off gates
all six tools; team hosts keep their existing read-only policy; the three write
operations remain selectable for configured host approval. Existing dashboard
labels/icons are extended; backend/frontend locale keys match.

Source review checked input bounds, stale-content protection, namespace
isolation, transaction rollback, source/episode/summary filtering, successor
readback and database reopening. Fresh recall is filtered; existing historical
conversation messages and frozen recall snapshots intentionally stay historical.
This is not a guarantee that a model ignores every old sentence already in its
conversation. Generated summaries rejoin recall only after regeneration.

Full management standard hook and dashboard build evidence is recorded in
ops/memory-correction-host-gate-20261017.log in the deployment workspace. Live
deployment and actual old-fact repair must be recorded separately with backup,
exact-source checks, health and readback evidence.

Full management gate passed4777 tests (188 conditional skips), strict mypy638 source files and dashboard production build. Final harness source also records actual page.id to entity_id mapping, so flattened page-headline snippets cannot bypass pending-summary filtering.
