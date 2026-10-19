# Steering release evidence, 2026-10-19

## Scope

The integrated branch is `steering-integrated-review`. It contains the live message steering change, the persistent chat input queue, the accepted terminal receipt retry fix, the team and Bridge admission boundary fix, and the combined Harness wheel. No production deployment was performed in this worktree.

## Artifact checks

The packaged artifact is `vendor/harness/octop_harness-1.0.2.post4.dev1+taskresults.1-py3-none-any.whl`.

Its SHA256 is `beb8636d683391cb8dc6e22d5384e70c5f771f0be1ddf52c3ffbfb6ce6482e14`. The wheel has 375 entries. The source manifest has 370 source entries, and its source hashes, wheel hash, and lockfile hash match the packaged bytes.

## Integrated gate results

These are the actual final command results from the isolated integration environment.

* `uv sync --frozen` completed successfully and installed the final combined wheel. Session `92563`.
* Targeted backend pytest completed with `70 passed, 2 warnings`. Exit code 0. Session `54557`.
* `uv run --frozen ruff check src tests` passed. Exit code 0.
* `uv run --frozen ruff format --check src tests` passed with 1338 files already formatted. Exit code 0.
* `uv run --frozen mypy src/octop` passed with no issues in 662 source files. Exit code 0. Session `2251`.
* Targeted Vitest completed with 10 files and 45 tests passed. Exit code 0. Session `80226`.
* `npx tsc -b` completed with exit code 0. Session `4832`.
* `npm run build` completed with exit code 0. Vite reported a successful production build in 55.37 seconds. Session `38143`.
* `uv run --frozen pytest -n auto -m "not live"` completed with `4952 passed, 159 skipped, 36 warnings` in 636.68 seconds. Exit code 0. Session `62774`.

The staged diff had no unresolved conflict markers and `git diff --cached --check` passed. The full repository frontend format check still reports the repository baseline drift across 1198 files, so no whole repository formatting write was performed. The changed frontend behavior was covered by the targeted tests, TypeScript check, and production build.

## Release state

The normal Git hook commit, push, pull request, CI, and merge are the remaining publication steps. The production cutover remains a separate operation that must use the exact merged `main` commit and must preserve active device and GPU work.
