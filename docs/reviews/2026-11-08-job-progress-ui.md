# Review, release/1.0.2b23, 2026-11-08

**Reviewed by**: GPT-6 (author model unspecified)
**Scope**: named task and script-reported progress UI, uncommitted versus ab3daf01
**Verdict**: Approve

## Summary
The sidebar summary now displays individual job names and script-reported progress; legacy kind-only labels use the existing fallback. The earlier review findings are resolved, and no remaining actionable defects were identified in the reviewed scope.

## Strengths
- Progress accepts only script-reported values and validates percentages without inferring completion.
- Job names are kept separate from conversation titles, with conservative fallback for old receipts.
- Polling guards late responses and stops on unmount.

## Test coverage
Targeted tests cover name and progress in the sidebar summary, fallback labels, and invalid or missing percentages. Browser acceptance is in progress.
