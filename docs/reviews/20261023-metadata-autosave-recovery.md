# Metadata automatic application and historical batch recovery

Self-review against main `9e8902eb`; no independent reviewer was used.

- The actual last batch failure was invalid JSON, followed by a successful brief job. Historic outcomes remain unchanged; later recovery is derived from the latest owned auto/brief job and displayed separately.
- Historical failure browsing is paginated and owner scoped, including already recovered conversations. Ordinary latest-state filtering and bulk selection retain their original semantics. Tests cover 25 failures across pages, recovery followed by another failure, missing batches and foreign users.
- Settings apply immediately. A single serialized writer uses the last confirmed revision and retains rapid edits; failures restore confirmed form values and show an inline error. Batch start is unavailable while a write is pending. No Provider or chat-model preference is changed as part of rollout.
- JSON syntax diagnostics contain only line/column/offset, never the invalid model response. Original error details remain available for historical batch rows.
- Targeted backend/integration/i18n: 111 passed. Frontend settings/history interactions: 11 passed. TypeScript passed. Full `make all`: 5,133 passed / 157 skipped, Ruff and strict mypy passed.
- Real isolated app: toggled title generation and selected a model; both persisted after reload without Save/Cancel. A recovered conversation remained accessible in the old batch failure dialog, and its JSON syntax diagnostics opened in a second dialog. Native pointer inspection required keyboard activation for one intercepted click. Screenshot capture timed out; DOM/interaction acceptance is recorded, not screenshot or mobile visual acceptance.
- Normal hook, final-head CI and deployment evidence are recorded in the PR and release manifest once completed. Windows waiting remains waived by the user.
