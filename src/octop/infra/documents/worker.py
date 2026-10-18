"""One-shot parser process. Only trusted code runs; document bytes arrive on stdin."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

MAX_PAGES = 500
MAX_CHARS = 2_000_000


def extract(data: bytes, suffix: str) -> dict[str, object]:
    if suffix == ".pdf":
        from io import BytesIO

        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted:
                return {"code": "DOCUMENT_ENCRYPTED"}
            if len(reader.pages) > MAX_PAGES:
                return {"code": "DOCUMENT_LIMIT"}
            pages: list[str] = []
            chars = 0
            for page in reader.pages:
                text = page.extract_text() or ""
                chars += len(text)
                if chars > MAX_CHARS:
                    return {"code": "DOCUMENT_LIMIT"}
                pages.append(text)
            return {"pages": pages, "parser": "pypdf"}
        except PdfReadError:
            return {"code": "DOCUMENT_INVALID"}
    if suffix in {".docx", ".pptx", ".xlsx", ".xlsm", ".xls"}:
        from octop.infra.knowledge.parse import parse_document

        with tempfile.TemporaryDirectory(prefix="octop-document-") as folder:
            target = Path(folder) / f"document{suffix}"
            target.write_bytes(data)
            text = parse_document(target)
        if len(text) > MAX_CHARS:
            return {"code": "DOCUMENT_LIMIT"}
        return {"pages": [text], "parser": "office"}
    if b"\x00" in data:
        return {"code": "DOCUMENT_UNSUPPORTED"}
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = data.decode(encoding)
            if len(text) > MAX_CHARS:
                return {"code": "DOCUMENT_LIMIT"}
            return {"pages": [text], "parser": "text"}
        except UnicodeDecodeError:
            continue
    return {"code": "DOCUMENT_UNSUPPORTED"}


def main() -> None:
    # Portable bundles add packages/ in launch.py rather than installing Octop.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    try:
        result = extract(sys.stdin.buffer.read(8 * 1024 * 1024 + 1), sys.argv[1])
    except ImportError:
        result = {"code": "DOCUMENT_PARSER_UNAVAILABLE"}
    except Exception:
        result = {"code": "DOCUMENT_EXTRACTION_FAILED"}
    # Parent decodes JSON bytes as UTF-8; ASCII escapes make the pipe independent
    # of Windows console code pages and preserve all document characters.
    sys.stdout.write(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
