"""Thin authorized file preview source adapter."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from octop.api.deps import current_user, get_server
from octop.infra.documents.file_sources import FileSourceService

router = APIRouter()


class OpenFileSourceBody(BaseModel):
    kind: Literal["execution", "workspace", "resource"]
    context_id: str = Field(default="", max_length=200)
    path: str = Field(default="", max_length=4096)
    resource_id: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def valid_source(self) -> "OpenFileSourceBody":
        if (
            (self.kind == "resource" and not self.resource_id)
            or (self.kind != "resource" and (not self.path or "\x00" in self.path))
            or (self.kind == "execution" and not self.context_id)
        ):
            raise ValueError("invalid file source")
        return self


@router.post(
    "/agents/{agent_id}/threads/{thread_id}/file-sources/open",
    summary="Open an authorized immutable file preview version",
)
async def open_file_source(
    agent_id: str,
    thread_id: str,
    body: OpenFileSourceBody,
    user: Any = Depends(current_user),
    server: Any = Depends(get_server),
) -> Any:
    try:
        return await FileSourceService(server.app_runtime.agent_registry).open(
            int(user.id), agent_id, thread_id, body.model_dump()
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
