# Vendored Harness for Octop fork releases

## Current immediate-insertion artifact

The application now pins `1.0.2.post4.dev4+interrupt.2`. `interrupt-source-manifest.json`
records the exact wheel/archive hashes and all 371 package members. Only `agent.py`,
`manager.py` and `steering.py` differ from activity.3; all other runtime members,
including activity/history support, remain byte-identical. `harness-source.zip`
contains the matching source, tests and build metadata. This is a local candidate,
not a publication or deployment claim.
`interrupt-steering.patch` exposes the three runtime changes as a readable diff.

The original insertion behavior is retained. The new queued-message action forwards
`cancel_tools=True` to interrupt current tool handler waits and supply paired
interruption results, without replaying work or promising external process termination.
Checks and limitations are recorded in `docs/progress-agent-live-message-steering.md`.

## Previous 0034 integration artifact

The activity.3 baseline wheel SHA256 is `9af63f12f5813ab490c7691e31bddfb2918c214ef509ea50eb851fe4d8f0e4a7`.
`activity3-source-manifest.json` and `activity3-verification.md` retain its provenance.
Its historical archive hash was `3a9100e62bf891e35cb838b7ba5e0fff4164aa1dcb2ffbd89cb0ea21a05cec4f`;
the shared source archive is now replaced by the immediate-insertion revision.
The original `source-manifest.json` and patch files below describe the earlier tooltext.1 baseline.

This revision adds public native-task activity/correlation and safe history append after completed parallel checkpoints. Hosts must still serialize writes to the same thread; the application uses its dashboard input-queue lock for scheduled delivery. The integration tests and real local task/Job and timer-restart evidence are recorded in `docs/progress-workspace-0034.md`.

The Octop fork release attaches this pinned dependency wheel alongside the application wheel. Install the Harness wheel from the same release before installing the application wheel; this fork dependency is not resolved from the public PyPI index. The application source distribution includes the lock, exact wheel and provenance above so `uv sync --frozen --no-dev` works from the extracted source. Portable packages bundle their locked dependencies. Release assets and the merged source identify publication state; historical checkpoints below are provenance, not current deployment claims.

## Previous tooltext.1 baseline

The pinned `1.0.2.post4.dev1+tooltext.1` wheel is based on the production `370`-source artifact and applies the reviewed share-tool-content revision 1 boundary fix. It normalizes textual tool-result blocks to a provider-compatible string without changing internal message structures, call IDs, or non-text payloads. It is a private release candidate and has not been merged, pushed, deployed, or publicly released.

`source-manifest.json` records the source baseline, source commit, every packaged file hash and the wheel SHA256. The application uses a repository relative uv source and a hash locked wheel, so `uv sync --frozen` installs this contract instead of restoring the older production archive. The override is portable with this repository directory and contains no absolute checkout path.

For local development, use the repository's normal `uv sync --frozen` and run/test commands. The existing application virtual environment was also checked by importing the installed wheel without a Harness source PYTHONPATH. Source checks in the companion Harness checkout are separate evidence from application integration tests.

Future release preparation should publish the reviewed immutable Harness source/artifact through the normal authorized release process, replace the vendor override deliberately, regenerate the lock and rerun integrated checks. Do not remove this override while retaining code that requires the new dispatch/lifecycle API.

The original source archive reference was `https://github.com/CkEFFAF/octop-harness/archive/2ac4d602f931c985dae3cf4bc36a72b9c7104fbd.tar.gz`.

The artifact preserves the production source baseline at Harness commit `6636ce2c4fed85c92f37da66459a218ddf158aef`; only `octop_harness/llm/factory.py` differs from that baseline. `source-manifest.json` records every source file, the reviewed patch digest, and the current wheel digest. `share-tool-content-factory.patch` is included beside the wheel for review provenance.
