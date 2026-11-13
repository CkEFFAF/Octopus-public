"""Pinned expert documents stay readable and editable while the expert is stopped."""

from types import SimpleNamespace

import pytest

from octop.api.routers.workspace import WriteFileBody, read_file, write_file
from octop.infra.errors import ErrorCode, OctopError


async def test_stopped_expert_workspace_owner_can_read_and_edit_notes():
    content = {".octop/notes/manual.md": "Original experiment rules"}

    class Workspace:
        async def aread_text(self, path):
            return content.get(path)

        async def aupload_bytes(self, path, data):
            content[path] = data.decode("utf-8")

    workspace = Workspace()
    row = SimpleNamespace(user_id=7, last_state="stopped", is_shared=1)
    manager = SimpleNamespace(get_row=lambda _: row, workspace_for_agent=lambda _: workspace)
    server = SimpleNamespace(app_runtime=SimpleNamespace(agent_registry=manager))
    owner = SimpleNamespace(id=7, is_admin=False)
    args = {
        "agent_id": "gpu",
        "path": ".octop/notes/manual.md",
        "from_workspace": True,
        "as_user": None,
        "user": owner,
        "server": server,
    }
    assert (await read_file(**args))["content"] == "Original experiment rules"
    await write_file(**args, body=WriteFileBody(content="Updated experiment rules"))
    assert content[".octop/notes/manual.md"] == "Updated experiment rules"
    # Being able to chat with a shared expert still does not grant editing access.
    with pytest.raises(OctopError) as error:
        await write_file(
            **{**args, "user": SimpleNamespace(id=8, is_admin=False)},
            body=WriteFileBody(content="Other user edit"),
        )
    assert error.value.code == ErrorCode.FORBIDDEN
    assert content[".octop/notes/manual.md"] == "Updated experiment rules"
