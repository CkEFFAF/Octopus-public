# 0011 implementation handoff

Authoritative requirements: `0011-acp-preset-extensions.md`, revision
`2026-10-12.3`. Implementation date: 2026-10-13. This PR contains T0 and T1
code; FU-001's harness source is retained separately as requested by the user.
Implementation verification originally left production services unchanged.
The user subsequently authorized the 1.0.2b7 release and cloud hub upgrade;
the release gate and deployment evidence are recorded below.

## Completed behavior

- Migration 025 preserves IDs and credentials, requires an existing provider
  owner and replaces global names with `UNIQUE(user_id, name)`. Empty instances
  need no owner; ambiguous historical instances require `PRIMARY_OWNER_USER_ID`.
- Ordinary users configure only their own providers and preferred model.
  Explicit privileged administration retains the project's delegated permission
  policy. CLI operations use the acting user. Codex token files, refresh,
  pending states and logout follow the same account boundary.
- Shared experts use the owner's catalog and factory. Actual harness factories
  and model caches stay separate for accounts with identical public model refs.
  Provider changes refresh every factory of that owner, including models that
  are available for an individual turn but are not the expert's default.
- Empty provider registration fails closed after lifecycle locks and during
  internal rebuilds; it cannot detect credentials from the hub environment.
  Harness's global plugin model contexts are sealed. Non-model plugin tools
  continue to work; plugin model access requires a future account-scoped
  harness API. This does not sandbox arbitrary installed Python code.
- Hermes, Grok Build and OpenClaw appear after Pi, default disabled, support
  edits and cannot be deleted. Grok Build has no automatic-approval argument.
  Existing custom runner CRUD is preserved.
- Remote ACP tests run a real subprocess and verify the exact four-field
  payload, no forwarded hub environment and device-local credential inheritance.
  Device protocol fields and Accepted 0004 are unchanged.

## Verification

- Windows required ship gate: **`make all PYTEST_JOBS=4` passed**; full non-live
  suite: **4506 passed, 151 skipped** (temporary basetemp; no real LLM calls).
  `make precommit` also passed (**4506 passed, 186 skipped**, including live
  tests skipped without credentials).
- Strict mypy: **593 source files passed**. Ruff check and format check passed.
- Dashboard: TypeScript and production/PWA build passed. ACP component and model
  utility tests: **6 passed**, including built-in ordering, edit and delete behavior.
- Scalar documentation route returned HTTP 200; generated provider and ACP
  operations have readable summaries and typed request schemas.
- Account isolation regressions use two real users, same-name private providers,
  shared expert selection, independent token files/logout, cross-account OAuth
  state rejection and startup/removal races. The integration and runtime tests
  exercise actual APIs and actual harness factories with synthetic credentials.
- Independent review found the empty-provider and ownerless OAuth-state paths;
  both were fixed and rechecked. No remaining confirmed blocking finding.
- SQLite migrations and restores are exercised. PostgreSQL migration received
  SQL/schema invariant checks and static review; a live PostgreSQL upgrade is
  still unverified.
- Linux full non-live suite in an isolated Ubuntu 24.04 root/headless directory:
  **4632 passed, 16 failed, 9 skipped**. Eleven failures were caused by the
  source-export tool setting file timestamps to 1970, outside ZIP's supported
  range. After correcting only those temporary timestamps, the three affected
  plugin test modules passed: **28 passed**. The other five failures concern
  headless desktop capabilities and systemd behavior under root; all five were
  reproduced against unchanged `ff869e41` source. No production data, login
  file or running hub service was accessed. Linux CI is still required; this
  environment's original full suite was not reported as green.
- Linux account ownership, migration, provider API, ACP and memory regression
  modules: **56 passed**.

### 1.0.2b7 release gate

- Windows `make all PYTEST_JOBS=4`: **4507 passed, 151 skipped**; Ruff and
  strict mypy (**593 source files**) pass. No paid model calls.
- Linux strict mypy passes after narrowing ignores to Windows-only platform
  APIs. Root/headless fixtures use explicit account and hardware assumptions;
  the desktop capture test now sets its capability before applying grants.
  The first release run reached **4648 passed, 2 failed, 8 skipped**; those
  fixture failures were corrected and their modules rerun: **42 passed**.
  The final full Linux run passed: **4650 passed, 8 skipped**. Both platform
  results must also pass PR CI before merge.
- GitHub Actions syntax validation passes for every changed workflow.
  Private-fork release publication no longer depends on upstream PyPI secrets;
  CodeQL still analyzes code and retains SARIF when Code Scanning is unavailable.
- Migration 025 was rehearsed against a protected cloud-local database copy:
  both provider records retain their IDs and credentials, other resource counts
  remain unchanged, and integrity/foreign-key checks pass. The production hub
  remains on its existing version until release assets and backups are ready.

Release and rollback procedure: `../octopus/release-process.md`.

## Remaining acceptance and separate harness work

- **T1.7:** actual Hermes/Grok Build/OpenClaw installations, authenticated
  sessions/Gateway and interactive permission flow need real-device acceptance.
  Documentation checks and a synthetic ACP subprocess are not substitutes.
- **T2.1–T2.3:** prepared in the separate `octop-harness-presets` checkout.
  Canonical model catalog refresh and xAI source are retained, not committed or
  published. Its Windows full run has the same 46 failures as the original
  source (1606 vs 1603 passes; 28 skips; no new failure IDs); 43 focused provider
  tests, Ruff and strict mypy pass. The user chose to preserve that source and
  submit the Octopus PR first.
- **T2.4–T2.5:** wait for a harness release containing that catalog, then bump
  only the harness dependency/lock and verify the Dashboard's xAI presets.
  This release updates only Octopus's version in `pyproject.toml` and `uv.lock`;
  harness dependency pins remain unchanged. It adds no second provider-template
  JSON to Octopus.

For upgrade steps and the review checklist, see
`../octopus/configuration-ownership.md`. Back up before migration; rollback
requires restoring the earlier database because older code lacks account ownership.
