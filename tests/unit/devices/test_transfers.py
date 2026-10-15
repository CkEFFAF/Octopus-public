from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from octop.infra.devices.transfers import CHUNK, NativeTransfers


@pytest.fixture
def files(tmp_path: Path) -> Any:
    state = tmp_path / "runtime"
    state.mkdir()
    transfers = NativeTransfers(state)

    def call(action: str, **params: Any) -> dict[str, Any]:
        return transfers.execute(
            action, {"execution_context_id": "frozen", **params}, tmp_path, contextlib.nullcontext
        )

    yield transfers, call, tmp_path
    transfers.close()


@pytest.mark.parametrize("content", [b"", b"binary\x00data" * 180000], ids=["empty", "multi-chunk"])
def test_large_and_empty_native_upload_download_have_matching_checksums(
    files: Any, content: bytes
) -> None:
    _, call, root = files
    destination = root / "outside" / "中文.bin"
    destination.parent.mkdir()
    digest = hashlib.sha256(content).hexdigest()
    begun = call("fs.upload.begin", path=str(destination), size=len(content), sha256=digest)
    session = begun["transfer_id"]
    for offset in range(0, len(content), CHUNK):
        block = content[offset : offset + CHUNK]
        assert call(
            "fs.upload.chunk",
            transfer_id=session,
            offset=offset,
            data_b64=base64.b64encode(block).decode(),
        )["bytes_done"] == offset + len(block)
    result = call("fs.upload.commit", transfer_id=session)
    assert destination.read_bytes() == content
    assert result["sha256"] == digest
    assert call("fs.upload.status", transfer_id=session)["status"] == "completed"
    # A repeated commit only observes the existing completion receipt.
    assert call("fs.upload.commit", transfer_id=session) == result
    download = call("fs.download.begin", path=str(destination))
    received = bytearray()
    for offset in range(0, len(content), CHUNK):
        block = call("fs.download.chunk", transfer_id=download["transfer_id"], offset=offset)
        received.extend(base64.b64decode(block["data_b64"]))
    assert bytes(received) == content and download["sha256"] == digest
    call("fs.download.close", transfer_id=download["transfer_id"])
    assert not list(destination.parent.glob(".octop-native-*"))


def test_context_offsets_checksum_and_destination_races_do_not_commit(files: Any) -> None:
    _, call, root = files
    content = b"payload"
    begun = call(
        "fs.upload.begin",
        path="target",
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    session = begun["transfer_id"]
    with pytest.raises(ValueError, match="context"):
        call(
            "fs.upload.chunk",
            execution_context_id="different",
            transfer_id=session,
            offset=0,
            data_b64="",
        )
    with pytest.raises(ValueError, match="offset"):
        call(
            "fs.upload.chunk",
            transfer_id=session,
            offset=1,
            data_b64=base64.b64encode(content).decode(),
        )
    call(
        "fs.upload.chunk",
        transfer_id=session,
        offset=0,
        data_b64=base64.b64encode(content).decode(),
    )
    (root / "target").write_bytes(b"another writer")
    with pytest.raises(ValueError, match="destination changed"):
        call("fs.upload.commit", transfer_id=session)
    assert (root / "target").read_bytes() == b"another writer"
    call("fs.upload.abort", transfer_id=session)
    corrupt = call(
        "fs.upload.begin", path="corrupt", size=1, sha256=hashlib.sha256(b"a").hexdigest()
    )
    call(
        "fs.upload.chunk",
        transfer_id=corrupt["transfer_id"],
        offset=0,
        data_b64=base64.b64encode(b"b").decode(),
    )
    with pytest.raises(ValueError, match="checksum"):
        call("fs.upload.commit", transfer_id=corrupt["transfer_id"])
    assert not (root / "corrupt").exists()
    call("fs.upload.abort", transfer_id=corrupt["transfer_id"])


def test_download_detects_source_mutation_and_upload_rejects_replaced_temporary(files: Any) -> None:
    _, call, root = files
    source = root / "source"
    source.write_bytes(b"before")
    download = call("fs.download.begin", path="source")
    source.write_bytes(b"changed and longer")
    with pytest.raises(ValueError, match="source changed"):
        call("fs.download.chunk", transfer_id=download["transfer_id"], offset=0)
    call("fs.download.close", transfer_id=download["transfer_id"])
    upload = call("fs.upload.begin", path="target", size=0, sha256=hashlib.sha256(b"").hexdigest())
    manifest = json.loads((root / "runtime" / "native-transfers.json").read_text())
    temporary = Path(manifest[upload["transfer_id"]]["temporary"])
    # Windows does not let another actor replace an open upload file.
    if os.name == "nt":
        with pytest.raises(PermissionError):
            temporary.unlink()
    else:
        temporary.unlink()
        temporary.write_bytes(b"replacement")
        with pytest.raises(ValueError, match="temporary file was replaced"):
            call("fs.upload.commit", transfer_id=upload["transfer_id"])
        assert not (root / "target").exists()
        call("fs.upload.abort", transfer_id=upload["transfer_id"])
        assert temporary.read_bytes() == b"replacement"


def test_process_restart_cleans_only_its_uncommitted_native_upload(tmp_path: Path) -> None:
    state = tmp_path / "runtime"
    state.mkdir()
    code = """
import contextlib, hashlib, sys
from pathlib import Path
from octop.infra.devices.transfers import NativeTransfers
root = Path(sys.argv[1])
stream = NativeTransfers(root / 'runtime')
stream.execute('fs.upload.begin', {'path': 'incomplete', 'size': 0,
    'sha256': hashlib.sha256(b'').hexdigest(), 'execution_context_id': 'test'}, root, contextlib.nullcontext)
"""
    subprocess.run([sys.executable, "-c", code, str(tmp_path)], check=True, timeout=20)
    assert len(list(tmp_path.glob(".octop-native-*"))) == 1
    unrelated = tmp_path / "keep-me"
    unrelated.write_text("user content")
    restarted = NativeTransfers(state)
    assert not list(tmp_path.glob(".octop-native-*")) and not (tmp_path / "incomplete").exists()
    assert unrelated.read_text() == "user content"
    restarted.close()
