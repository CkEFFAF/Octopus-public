# Expert storage boundary review

Date: 2026-10-17

The fix was reviewed in an independent read only agent context against harness baseline `ff965d2` and management baseline `cc2ac13b`, using AC1 to AC6 in spec 0022.

Review findings were addressed before submission:

1. Exact `/.agent` mount routing must receive the same authorization as `/.agent/`.
2. Deleting an ancestor must not remove protected runtime files. Agent content deletion now requires a confirmed individual file; directory removal uses host management.
3. Recursive ls, glob and grep results require authorization of every returned path before rendering or offloading. This also rejects a file symlink reaching another expert under a broad controller mount.
4. Windows local runtime names require case normalization and rejection of trailing dot, trailing space and alternate stream aliases. Cloud object keys retain their case semantics.
5. Each subagent must retain its configured skill source roots. Declared custom SQLite and session transcript locations must remain protected.

The reviewer rechecked the final implementation and returned no remaining actionable findings. Existing limitations of nonvirtual Windows drive paths and separately configured subagent backends were distinguished from changes in this fix.

Validation: management full non live suite 4765 passed, 153 skipped; management focused integration suite 56 passed; full mypy 637 modules passed. Harness normal commit gate passed Ruff, mypy and 1740 tests (31 skips). Its GitHub Linux Python 3.12 and CodeQL checks passed. Management pins the actual installed source archive at `d30b36cbb17e9e8403d01555a4f399667228263b`, lockfile SHA256 `fa0ee8c9c6c070bd2433f0d97850f50499207c7464e333f3e0e6b33e550bfeef`. No production database, memory, device, service or filesystem permissions were changed by this work.

The full testmon commit gate additionally exposed a preexisting PID fixture race: the parent PID file existed while its write was still empty, producing ValueError before the process assertion ran (4764 other tests passed). The fixture now writes a temporary PID file and atomically publishes it after completion. Executor implementation is unchanged; its complete focused suite passed 29 tests with one platform skip after the fixture correction.

The corrected management standard commit gate then passed 4767 tests with 186 conditional skips and the dashboard build. The patch was subsequently rebased onto main `789b044c`, which introduced an unrelated TypeScript error in the nullish ContextWindowRing fallback. Its two optional fields now explicitly use undefined, preserving their existing runtime values while avoiding property access on a value already narrowed to nullish. Final validation checks the integrated main revision and the storage fix together.
