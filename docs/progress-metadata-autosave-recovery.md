# Metadata settings and batch recovery

Baseline: main `9e8902eb`, 2026-10-23 user screenshots.

- Apply switches and model selections immediately. Serialize account revision writes, retain rapid edits, expose applying/applied/failure state and remove explicit Save/Cancel. Batch execution must wait for pending settings writes. Restore confirmed values if applying fails.
- Production read-only evidence: the one historical batch failure was a JSONDecodeError (invalid JSON); a later brief job succeeded. Batch totals are historical, whereas the ordinary list describes the latest job. Do not mutate historical job outcomes or repeat real model calls to make old counts disappear.
- Label historical batch results, report subsequent recovery and open a paginated list of that batch's failed conversations, with original reason/details and current state. Preserve the latest-state filters for ordinary browsing and enqueueing, and enforce account ownership on batch history.
- Add content-free JSON syntax position diagnostics for future failures. Never persist or copy the model response or conversation text into diagnostics.
- Verify backend contracts/ownership/recovery, frontend automatic application/error/rapid edits and real isolated app interaction; run required repository checks before the previously authorized merge and management web deployment. Windows waiting remains waived.

Implemented and locally verified: targeted backend/integration/i18n 111 passed, frontend interactions 11 passed, TypeScript passed, full `make all` 5,133 passed / 157 skipped with Ruff and strict mypy green. Real isolated application retained switch and model changes after reload and showed recovered batch failures with original diagnostic details. Screenshot capture timed out; no visual screenshot/mobile acceptance claimed. Review evidence: `docs/reviews/20261023-metadata-autosave-recovery.md`. Normal hook, CI and deployment remain tracked in the PR and release manifest.
