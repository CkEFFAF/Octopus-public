"""Security reports remain recoverable without Actions artifact storage."""

from __future__ import annotations

import base64
import gzip
import importlib.util
import json
import random
import re
from pathlib import Path

import pytest


def _renderer(repo_root: Path):
    spec = importlib.util.spec_from_file_location(
        "retain_codeql_summary", repo_root / "scripts/retain_codeql_summary.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.render


def test_complete_sarif_is_recoverable_and_findings_are_readable(
    tmp_path: Path, repo_root: Path
) -> None:
    content = json.dumps(
        {
            "runs": [
                {
                    "results": [
                        {
                            "ruleId": "py/example",
                            "level": "error",
                            "message": {"text": "unsafe <value>"},
                        }
                    ]
                }
            ]
        }
    ).encode()
    (tmp_path / "python.sarif").write_bytes(content)
    summary = _renderer(repo_root)(tmp_path)
    assert "1 findings" in summary and "py/example" in summary
    assert "unsafe &lt;value&gt;" in summary and "unsafe <value>" not in summary
    encoded = re.search(r"```text\n([A-Za-z0-9+/=]+)\n```", summary)
    assert encoded is not None
    assert gzip.decompress(base64.b64decode(encoded[1])) == content


def test_missing_or_oversized_reports_fail_instead_of_losing_results(
    tmp_path: Path, repo_root: Path
) -> None:
    render = _renderer(repo_root)
    with pytest.raises(ValueError, match="did not produce"):
        render(tmp_path)
    large = base64.b64encode(random.Random(1).randbytes(2_000_000)).decode()
    (tmp_path / "python.sarif").write_text(
        json.dumps({"runs": [], "properties": {"body": large}}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="no report was truncated"):
        render(tmp_path)
