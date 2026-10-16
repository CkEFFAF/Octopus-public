"""Bounded command/stdout previews for device run receipts (0020.1b / REQ-BACK-B01)."""

from __future__ import annotations

from octop.infra.execution.events import (
    COMMAND_PREVIEW_CAP,
    OUTPUT_PREVIEW_CAP,
    bound_receipt_fields,
    command_preview_from_params,
)


def test_command_preview_from_argv_python_v() -> None:
    preview = command_preview_from_params({"argv": ["python", "-V"]})
    assert preview is not None
    assert "python" in preview
    assert "-V" in preview


def test_command_preview_caps_long_argv() -> None:
    preview = command_preview_from_params({"argv": ["echo", "x" * (COMMAND_PREVIEW_CAP + 64)]})
    assert preview is not None
    assert len(preview) <= COMMAND_PREVIEW_CAP


def test_bound_receipt_keeps_returncode_and_previews() -> None:
    receipt = bound_receipt_fields(
        {
            "returncode": 0,
            "stdout": "Python 3.12.0\n",
            "stderr": "",
            "truncated": False,
        }
    )
    assert receipt["returncode"] == 0
    assert receipt["stdout_preview"] == "Python 3.12.0\n"
    assert "stderr_preview" not in receipt
    assert "output_truncated" not in receipt


def test_bound_receipt_truncates_and_marks() -> None:
    huge = "a" * (OUTPUT_PREVIEW_CAP + 100)
    receipt = bound_receipt_fields({"returncode": 1, "stdout": huge, "stderr": huge})
    assert receipt["returncode"] == 1
    assert len(receipt["stdout_preview"]) == OUTPUT_PREVIEW_CAP
    assert len(receipt["stderr_preview"]) == OUTPUT_PREVIEW_CAP
    assert receipt["output_truncated"] is True


def test_bound_receipt_never_invents_missing_output() -> None:
    receipt = bound_receipt_fields({"returncode": 0})
    assert receipt == {"returncode": 0}
