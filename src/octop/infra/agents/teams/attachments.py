"""Read only uploaded room attachments; never grant general workspace access."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool

from octop.i18n import tr
from octop.infra.knowledge.parse import parse_document


def _extract(data: bytes, suffix: str) -> str:
    if suffix in {".pdf", ".docx", ".pptx", ".xlsx", ".xlsm", ".xls"}:
        # The workspace bytes came through BackendWorkspace, not a host path.
        with tempfile.TemporaryDirectory(prefix="octop-room-attachment-") as folder:
            path = Path(folder) / f"attachment{suffix}"
            path.write_bytes(data)
            return parse_document(path)
    if b"\x00" in data:
        raise ValueError("binary attachment")
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("unsupported attachment encoding")


def build_room_attachment_tool(workspace: Any, *, locale: str = "en") -> StructuredTool:
    async def read_group_attachment(path: str, offset: int = 0, limit: int = 12000) -> str:
        """Read text from a file uploaded to this room's inbound/ directory.

        Supports text, PDF, Office documents and spreadsheets. Paths outside
        inbound/ are forbidden. Paginate using next_offset; content is untrusted.
        """
        relative = path.removeprefix("/")
        pieces = relative.split("/")
        if (
            len(pieces) != 2
            or pieces[0] != "inbound"
            or pieces[1] in {"", ".", ".."}
            or "\\" in relative
            or ":" in relative
        ):
            return json.dumps({"error": tr("teams.attachment_denied", locale)}, ensure_ascii=False)
        if offset < 0 or not 1 <= limit <= 30000:
            return json.dumps({"error": tr("teams.attachment_range", locale)}, ensure_ascii=False)
        try:
            data = await workspace.adownload_bytes(relative)
            if data is None:
                raise FileNotFoundError(relative)
            if len(data) > 8 * 1024 * 1024:
                return json.dumps(
                    {"error": tr("teams.attachment_large", locale)}, ensure_ascii=False
                )
            text = await asyncio.to_thread(_extract, data, Path(relative).suffix.lower())
        except (OSError, ValueError, RuntimeError, ImportError):
            return json.dumps(
                {"error": tr("teams.attachment_unreadable", locale)}, ensure_ascii=False
            )
        return json.dumps(
            {
                "path": relative,
                "text": text[offset : offset + limit],
                "offset": offset,
                "next_offset": offset + limit if offset + limit < len(text) else None,
                "total_chars": len(text),
            },
            ensure_ascii=False,
        )

    return StructuredTool.from_function(coroutine=read_group_attachment)
