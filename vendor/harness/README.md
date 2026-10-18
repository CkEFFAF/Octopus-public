# Internal beta Harness artifact

This wheel contains the collaboration contract from spec0031, revision2026-10-18.4, and the provider catalog update from0032. The user has authorized merging and private cloud deployment of this tested artifact. It is not a public package release.

`source-manifest.json` records the source baseline, source commit, every packaged file hash and the wheel SHA256. The application uses a repository relative uv source and a hash locked wheel, so `uv sync --frozen` installs this contract instead of restoring the older production archive. The override is portable with this repository directory and contains no absolute checkout path.

For local development, use the repository's normal `uv sync --frozen` and run/test commands. The existing application virtual environment was also checked by importing the installed wheel without a Harness source PYTHONPATH. Source checks in the companion Harness checkout are separate evidence from application integration tests.

Future release preparation should publish the reviewed immutable Harness source/artifact through the normal authorized release process, replace the vendor override deliberately, regenerate the lock and rerun integrated checks. Do not remove this override while retaining code that requires the new dispatch/lifecycle API.

The original source archive reference was `https://github.com/CkEFFAF/octop-harness/archive/2ac4d602f931c985dae3cf4bc36a72b9c7104fbd.tar.gz`.

Task-result compatibility build `1.0.2.post3+taskresults.1` applies `task-results.patch` to clean Harness commit `6636ce2c4fed85c92f37da66459a218ddf158aef`. It only clears the task outcome when terminal receipt persistence fails, plus its regression and local version metadata. The manifest retains the previous wheel provenance and records every source file, patch and current wheel digest.
