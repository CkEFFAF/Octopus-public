"""Bookmarks preserve source identity and cannot widen expert or target access."""

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from octop.api.deps import current_user, get_server
from octop.api.routers.pinned_files import router
from octop.infra.agents.pinned_files import (
    PinnedFile,
    PinnedFiles,
    PinnedFilesConflict,
    PinnedFilesService,
)
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.settings import SettingsRepo
from octop.infra.errors import ErrorCode, OctopError


@pytest.fixture
def services(tmp_path):
    pool = SqlitePool(tmp_path / "pins.db")
    run_migrations(pool)
    settings = SettingsRepo(pool)
    rows = {
        "gpu": SimpleNamespace(user_id=7, is_shared=1),
        "other": SimpleNamespace(user_id=8),
    }
    manager = SimpleNamespace(get_row=rows.get)
    yield PinnedFilesService(manager, settings), manager, settings
    pool.close()


def note(**changes):
    return {
        "id": "manual",
        "title": "Manual",
        "scope": "expert",
        "path": ".octop/notes/manual.md",
        **changes,
    }


def test_pins_survive_service_recreation_and_reject_shared_expert_access(services):
    service, manager, settings = services
    saved = service.save("gpu", 7, False, PinnedFiles(files=[PinnedFile(**note())]))
    restored = PinnedFilesService(manager, settings).get("gpu", 7, False)
    assert restored == saved
    assert restored.revision == 1
    assert service.get("gpu", 1, True) == saved
    for action in (
        lambda: service.get("gpu", 8, False),
        lambda: service.save("gpu", 8, False, saved),
    ):
        with pytest.raises(OctopError) as error:
            action()
        assert error.value.code == ErrorCode.FORBIDDEN
    assert service.get("other", 8, False).files == []


@pytest.mark.parametrize(
    "path",
    [
        "../manual.md",
        "notes/../../manual.md",
        "/etc/passwd",
        "C:/secret",
        "file://secret",
        "\\\\host\\secret",
        ".",
        "manual\x00.md",
    ],
)
def test_expert_paths_cannot_escape_the_workspace(path):
    with pytest.raises(ValidationError):
        PinnedFile(**note(path=path))


def test_project_pins_require_explicit_target_and_keep_its_identity(services):
    service, _, _ = services
    project = note(
        scope="project",
        path="reports/run.md",
        target_kind="device",
        device_id="gpu-box",
        working_dir="/research",
    )
    pin = PinnedFile(**project)
    saved = service.save("gpu", 7, False, PinnedFiles(files=[pin]))
    assert saved.files[0].device_id == "gpu-box"
    assert saved.files[0].working_dir == "/research"
    for missing in ("target_kind", "device_id", "working_dir"):
        with pytest.raises(ValidationError):
            PinnedFile(**{key: value for key, value in project.items() if key != missing})
    with pytest.raises(ValidationError):
        PinnedFile(**note(device_id="gpu-box"))
    local = PinnedFile(**note(scope="project", target_kind="local", working_dir="/research"))
    with pytest.raises(OctopError) as error:
        service.save("gpu", 7, False, PinnedFiles(revision=1, files=[local]))
    assert error.value.code == ErrorCode.FORBIDDEN


def test_stale_revision_and_concurrent_cas_never_overwrite_newer_pins(services, monkeypatch):
    service, _, settings = services
    first = service.save("gpu", 7, False, PinnedFiles(files=[PinnedFile(**note())]))
    with pytest.raises(PinnedFilesConflict):
        service.save("gpu", 7, False, PinnedFiles())
    original = settings.compare_and_set

    def race(key, raw, value):
        newer = PinnedFiles(revision=2, files=[PinnedFile(**note(title="Newer manual"))])
        assert original(key, raw, newer.model_dump_json())
        return original(key, raw, value)

    monkeypatch.setattr(settings, "compare_and_set", race)
    with pytest.raises(PinnedFilesConflict):
        service.save("gpu", 7, False, first)
    assert service.get("gpu", 7, False).files[0].title == "Newer manual"


async def test_http_read_write_validation_and_conflict(services):
    _, manager, settings = services
    app = FastAPI()
    app.include_router(router, prefix="/api")
    user = SimpleNamespace(id=7, is_admin=False)
    server = SimpleNamespace(
        app_runtime=SimpleNamespace(agent_registry=manager),
        services=SimpleNamespace(settings_repo=settings),
    )
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_server] = lambda: server

    @app.exception_handler(OctopError)
    async def errors(_, error):
        return JSONResponse(error.to_envelope(locale="zh"), status_code=error.status)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        url = "/api/agents/gpu/pinned-files"
        assert (await client.get(url)).json() == {"revision": 0, "files": []}
        body = {"revision": 0, "files": [note()]}
        saved = await client.put(url, json=body)
        assert saved.status_code == 200
        assert saved.json()["revision"] == 1
        conflict = await client.put(url, json=body)
        assert conflict.status_code == 409
        assert conflict.json()["error"]["details"]["reason"] == "pinned_files_conflict"
        assert "置顶文件" in conflict.json()["error"]["message"]
        assert (
            await client.put(url, json={"revision": 1, "files": [note(path="../secret")]})
        ).status_code == 422
        user.id = 8
        assert (await client.get(url)).status_code == 403
        assert (await client.put(url, json=body)).status_code == 403
