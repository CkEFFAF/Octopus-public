# Git panel local preview

Validated and approved by the user on 2026-10-13 for PR and merge.

The Git panel now has a change scope menu, directory groups, file filtering, per-file addition and deletion totals, and split or unified diff rendering with source line numbers. All changes shows both staged and unstaged sections. Existing confirmation and recovery copy behavior is preserved.

Small windows below the desktop breakpoint use the existing floating dock so the file sidebar stays visible. Git uses container queries to move the file list above the diff when its own panel becomes narrow.

Evidence:

* Fifteen Vitest cases passed across Git panel interactions, diff line parsing and pairing, work modes, and dock keep-alive behavior.
* Nine targeted Python cases passed, including literal filename restore and unambiguous skill snapshot digests.
* TypeScript, targeted ESLint, production build and diff whitespace check passed.
* Browser verified at desktop width and the default small window. The small window correctly displays the floating panel with both diff columns and file sidebar.
* Screenshot: `D:/Agent_Workspace/octopus/workbench-test-run/git-ui-preview.png`.

The first full repository run with the existing shared environment reported 4515 passed, 151 skipped and two provider tests failing due to dependency mismatch. The isolated Python 3.12 environment uses the repository's pinned harness wheel. Its full `make precommit` gate passed: Ruff check/format, mypy across 595 source files, and 4517 tests passed with 188 skipped (four workers, testmon selection disabled for the full run). All thirteen provider tests also passed in the pinned environment.
