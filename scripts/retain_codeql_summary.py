"""Retain complete SARIF in the job summary when artifact storage is full.

The analysis step remains mandatory. A compressed copy in the summary has the
same repository access control as the build logs and does not consume artifact
storage. Oversized reports fail rather than being silently truncated.
"""

from __future__ import annotations

import base64
import gzip
import html
import json
import os
from pathlib import Path


def render(directory: Path) -> str:
    sections = [
        "## CodeQL results\n",
        "Analysis completed. Complete SARIF copies are retained below (gzip + base64).\n",
    ]
    files = sorted(directory.glob("*.sarif"))
    if not files:
        raise ValueError("CodeQL did not produce SARIF")
    for path in files:
        raw = path.read_bytes()
        document = json.loads(raw)
        results = [result for run in document.get("runs", []) for result in run.get("results", [])]
        sections.append(f"### {html.escape(path.name)} — {len(results)} findings\n")
        for result in results:
            rule = html.escape(str(result.get("ruleId", "unknown")))
            level = html.escape(str(result.get("level", "warning")))
            message = html.escape(str(result.get("message", {}).get("text", "")))
            sections.append(f"- **{level} / {rule}**: {message}\n")
        encoded = base64.b64encode(gzip.compress(raw, mtime=0)).decode("ascii")
        sections.append(
            f"<details><summary>Complete {html.escape(path.name)}</summary>\n\n```text\n{encoded}\n```\n\n</details>\n"
        )
    output = "\n".join(sections)
    if len(output.encode("utf-8")) > 900_000:
        raise ValueError(
            "Complete CodeQL summary exceeds the retention budget; no report was truncated"
        )
    return output


if __name__ == "__main__":
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
        stream.write(render(Path("codeql-results")))
