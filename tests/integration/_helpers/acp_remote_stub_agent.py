"""Stdio ACP agent process used by AC-0045-01 (stub cloud, real ACP)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any


class StubCloud:
    server = "https://example.test"

    async def aclose(self) -> None:
        return None

    async def probe(self) -> None:
        return None

    async def create_thread(self, expert_id: str, *, title: str = "") -> dict[str, Any]:
        return {"thread_id": "thr_acp_1"}

    async def create_work_item(self, **kwargs: Any) -> dict[str, Any]:
        return {"task_id": "task_acp_1", "status": "queued"}

    async def add_input(self, task_id: str, text: str, *, command_id: str) -> dict[str, Any]:
        return {"ok": True}

    async def progress(self, task_id: str) -> dict[str, Any]:
        return {"status": "completed", "summary": "你好，任务完成", "task_id": task_id}

    async def cancel(self, task_id: str, *, command_id: str) -> dict[str, Any]:
        return {"status": "cancelled"}


async def main() -> None:
    # Ensure repo src is importable when spawned as a script.
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "src"))
    from acp import run_agent

    from octop.infra.acp_remote.agent import RemoteAcpAgent
    from octop.infra.acp_remote.sessions import SessionStore

    store = SessionStore(Path("/tmp/octop-acp-remote-test-sessions.json"))
    agent = RemoteAcpAgent(
        cloud=StubCloud(),  # type: ignore[arg-type]
        expert_id="expert-main",
        credential_id="cred-test",
        store=store,
        poll_interval=0.01,
        poll_timeout=5.0,
    )
    await run_agent(agent, use_unstable_protocol=True)


if __name__ == "__main__":
    asyncio.run(main())
