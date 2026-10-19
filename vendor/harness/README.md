# Internal Harness release candidate

The pinned `1.0.2.post4.dev1+tooltext.1` wheel is based on the production `370`-source artifact and applies the reviewed share-tool-content revision 1 boundary fix. It normalizes textual tool-result blocks to a provider-compatible string without changing internal message structures, call IDs, or non-text payloads. It is a private release candidate and has not been merged, pushed, deployed, or publicly released.

`source-manifest.json` records the source baseline, source commit, every packaged file hash and the wheel SHA256. The application uses a repository relative uv source and a hash locked wheel, so `uv sync --frozen` installs this contract instead of restoring the older production archive. The override is portable with this repository directory and contains no absolute checkout path.

For local development, use the repository's normal `uv sync --frozen` and run/test commands. The existing application virtual environment was also checked by importing the installed wheel without a Harness source PYTHONPATH. Source checks in the companion Harness checkout are separate evidence from application integration tests.

Future release preparation should publish the reviewed immutable Harness source/artifact through the normal authorized release process, replace the vendor override deliberately, regenerate the lock and rerun integrated checks. Do not remove this override while retaining code that requires the new dispatch/lifecycle API.

The original source archive reference was `https://github.com/CkEFFAF/octop-harness/archive/2ac4d602f931c985dae3cf4bc36a72b9c7104fbd.tar.gz`.

The artifact preserves the production source baseline at Harness commit `6636ce2c4fed85c92f37da66459a218ddf158aef`; only `octop_harness/llm/factory.py` differs from that baseline. `source-manifest.json` records every source file, the reviewed patch digest, and the current wheel digest. `share-tool-content-factory.patch` is included beside the wheel for review provenance.
