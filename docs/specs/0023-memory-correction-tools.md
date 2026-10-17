# 0023 Agent memory maintenance and correction

Status: Accepted
Date: 2026-10-17

## Problem

The GPU expert can search/get structured memory but cannot list, save, correct
or retire facts through its tools. The underlying memory library and dashboard
already implement these operations. Five live fact atoms still claim that the
expert cannot read/edit its own controller memory files after that issue was
fixed. Recalled raw evidence and pending summaries can also repeat those claims.

## Decision

Reuse octop-memory1.0.0's namespace-bound create_atom, replace_atom and
deprecate_atom APIs in the harness. Add memory_list/write/update/delete beside
search/get. Update creates a successor and delete soft-retires; do not erase raw
conversations or checkpoints. Require exact expected_content and a reason for
every update/delete. Tools accept fact paths, never caller-selected namespaces,
host database paths, raw-event edits or bulk deletion.

Record correction source markers through the existing namespace metadata API
in the same transaction. Explicit search/get and fresh automatic recall omit
retired atoms, their associated raw evidence/episodes, and affected dirty entity
summaries until regeneration. Readback of successors shows the current
assertion, without re-presenting the inherited superseded quote. Host audit
retains old content. Existing historical messages/recall snapshots stay intact.

## Acceptance

- AC1: A memory-enabled agent has all six named tools. Disabled memory still
  has no memory tools.
- AC2: Write is immediately listable/searchable/gettable. Update returns a
  readable successor and preserves the old atom's lineage and audit journal.
- AC3: Delete excludes the fact from current list/search and retains audit and
  raw history. It cannot delete a database or edit historical evidence.
- AC4: An atom ID belonging to another namespace is not accessible for mutation,
  even when both namespaces use one SQLite database. Stale expected_content
  fails without changing data.
- AC5: Cached hits, raw fallback, affected dirty summaries and fresh automatic
  recall do not return the retired assertions. This remains true after closing
  and reopening the database. Regenerated clean summaries become usable.
- AC6: A storage failure rolls back the replacement and source markers. Inputs
  and list sizes are bounded. No model/provider/device call is needed to repair
  facts or verify the feature.

## Integration and verification

The management dependency must pin the exact reviewed harness commit and
archive hash, following spec0022. No GPU transport or OS permission change is
needed. A sixth obsolete atom describing the former runtime whitelist and
search/get-only use was also identified read-only and is included in correction. Correct the identified obsolete GPU atoms only through the tested
namespace-bound operations after a fresh backup; preserve all conversation and
other expert data. Verify the capability through a private fake-model/storage
probe and verify production corrections by reading current facts and the audit.

Harness evidence: tests/test_memory_management.py; existing memory service/tool,
runtime, replay and full-suite checks. Independent host integration must inspect
the installed archive, not rely on an uninstalled future wheel.
