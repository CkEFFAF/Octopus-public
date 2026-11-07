"""Scoped cloud expert conversations for the standalone device program."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from octop.i18n import tr
from octop.infra.devices.client import validate_server_url
from octop.infra.devices.executor import (
    DeviceExecutionError,
    _reject_links,
    private_state_dir,
    save_private_json,
)
from octop.infra.utils.locale import DEFAULT_LOCALE
from octop.infra.utils.process_lock import ProcessAlreadyRunning, ProcessLock

TERMINAL = frozenset({"completed", "failed", "cancelled"})
_RESPONSE_LIMIT = 8 * 1024 * 1024


class ExpertClientError(Exception):
    def __init__(
        self,
        code: str,
        *,
        status: int | None = None,
        command_id: str | None = None,
        task_id: str | None = None,
    ) -> None:
        self.code = code
        self.status = status
        self.command_id = command_id
        self.task_id = task_id
        super().__init__(code)

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "error": self.code,
            "message": tr(f"device_expert.{self.code}", DEFAULT_LOCALE),
            **({"http_status": self.status} if self.status else {}),
            **({"command_id": self.command_id} if self.command_id else {}),
            **({"task_id": self.task_id} if self.task_id else {}),
        }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def expert_server_url(server: str) -> str:
    if (
        not server
        or "\\" in server
        or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in server)
    ):
        raise ExpertClientError("invalid_server")
    try:
        return validate_server_url(server)
    except DeviceExecutionError:
        raise ExpertClientError("invalid_server") from None


class ExpertConfig:
    def __init__(self, state: Path) -> None:
        self.path = state.absolute() / "expert-client" / "config.json"

    def load(self) -> dict[str, Any]:
        try:
            _reject_links(self.path)
            if not self.path.exists():
                raise ExpertClientError("not_configured")
            if self.path.stat().st_size > 64 * 1024:
                raise ValueError
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                not isinstance(value, dict)
                or value.get("version") != 1
                or not isinstance(value.get("token"), str)
                or not value["token"].startswith("oaa_")
                or not isinstance(value.get("credential_id"), str)
            ):
                raise ValueError
            expert_server_url(value["server_url"])
            return value
        except ExpertClientError:
            raise
        except (OSError, ValueError, KeyError, TypeError):
            raise ExpertClientError("invalid_config") from None

    def configure(self, server: str, token: str) -> dict[str, Any]:
        client = ExpertClient(server, token)
        identity = client.identity()
        private_state_dir(self.path.parent)
        save_private_json(
            self.path,
            {
                "version": 1,
                "server_url": client.server,
                "token": token,
                "credential_id": identity["credential_id"],
            },
        )
        return {"server_url": client.server, **identity}

    def client(self) -> ExpertClient:
        value = self.load()
        return ExpertClient(
            value["server_url"],
            value["token"],
            journal=self.path.parent / "commands",
            credential_id=value["credential_id"],
        )

    def public(self) -> dict[str, Any]:
        value = self.load()
        return {key: value[key] for key in ("server_url", "credential_id")}


def _text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(block.get("text") or "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


class ExpertClient:
    def __init__(
        self,
        server: str,
        token: str,
        *,
        journal: Path | None = None,
        credential_id: str = "",
    ) -> None:
        self.server = expert_server_url(server)
        if (
            not token.startswith("oaa_")
            or len(token) > 4096
            or any(not (c.isascii() and (c.isalnum() or c in "_-")) for c in token)
        ):
            raise ExpertClientError("invalid_token")
        self._token = token
        self._opener = urllib.request.build_opener(_NoRedirect())
        self._journal = journal
        self._credential_id = credential_id
        self._record_path: Path | None = None
        self._record: dict[str, Any] = {}

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        command_id = body.get("command_id") if body else None
        request = urllib.request.Request(
            self.server + path,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with self._opener.open(request, timeout=20) as response:
                raw = response.read(_RESPONSE_LIMIT + 1)
            if len(raw) > _RESPONSE_LIMIT:
                raise ValueError
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError
            return payload
        except urllib.error.HTTPError as exc:
            code = "auth_failed" if exc.code in {401, 403} else "request_rejected"
            raise ExpertClientError(code, status=exc.code, command_id=command_id) from None
        except (OSError, ValueError):
            raise ExpertClientError(
                "request_unconfirmed" if method == "POST" else "unavailable",
                command_id=command_id,
            ) from None

    @staticmethod
    def _id(value: str) -> str:
        return urllib.parse.quote(value, safe="")

    def identity(self) -> dict[str, Any]:
        value = self.request("GET", "/api/auth/agent-access-keys/identity")
        if not isinstance(value.get("credential_id"), str):
            raise ExpertClientError("invalid_response")
        return value

    def find(self, command_id: str) -> dict[str, Any]:
        if self._journal:
            path = self._command_path(command_id)
            _reject_links(path)
            if path.exists():
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("kind") == "input":
                    task_id = record["target_task_id"]
                    query = urllib.parse.urlencode({"command_id": command_id})
                    receipt = self.request(
                        "GET", f"/api/work-items/{self._id(task_id)}/inputs?{query}"
                    )["receipt"]
                    return {
                        "command_id": command_id,
                        "task": self.detail(task_id) if receipt else None,
                        "input_receipt": receipt,
                    }
        query = urllib.parse.urlencode({"command_id": command_id, "status_group": "all"})
        items = self.request("GET", f"/api/work-items?{query}").get("items", [])
        return {"command_id": command_id, "task": items[0] if items else None}

    def history(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        if not task.get("worker_thread_id"):
            return []
        path = (
            f"/api/agents/{self._id(task['agent_id'])}/threads/"
            f"{self._id(task['worker_thread_id'])}/history"
        )
        messages: list[dict[str, Any]] = []
        cursor: str | None = None
        seen: set[str] = set()
        offset = 0
        while True:
            query: dict[str, str | int] = {"limit": 100, "offset": offset}
            if cursor:
                query["cursor"] = cursor
            payload = self.request("GET", f"{path}?{urllib.parse.urlencode(query)}")
            page = payload.get("messages", [])
            messages = [*page, *messages]
            offset += len(page)
            if not payload.get("has_more"):
                break
            cursor = payload.get("next_cursor")
            if not page or (cursor and cursor in seen):
                raise ExpertClientError("invalid_response")
            if cursor:
                seen.add(cursor)
        return [
            message
            for message in messages
            if isinstance(message, dict) and message.get("role") in {"user", "assistant"}
        ]

    def detail(self, task_id: str) -> dict[str, Any]:
        return self.request("GET", f"/api/work-items/{self._id(task_id)}")

    def result(self, task: dict[str, Any]) -> dict[str, Any]:
        progress = task.get("progress") or {}
        output = str(progress.get("output_text") or "")
        if task["status"] in TERMINAL:
            output = (
                "\n".join(
                    _text(message)
                    for message in self.history(task)
                    if message["role"] == "assistant"
                )
                or output
            )
        return {
            "schema_version": 1,
            "server_url": self.server,
            "expert_id": task["agent_id"],
            "session_id": task["origin_thread_id"],
            "task_id": task["task_id"],
            "status": task["status"],
            "reply": output or str(task.get("reported_outcome") or ""),
            "cancel_requested": bool(task.get("cancel_requested")),
            "current_attempt_id": task.get("current_attempt_id"),
            "permission_request": progress.get("permission_request"),
        }

    def wait(self, task_id: str, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            task = self.detail(task_id)
            if (
                task["status"] in TERMINAL
                or task["status"] == "unknown"
                or (task.get("progress") or {}).get("permission_request")
                or time.monotonic() >= deadline
            ):
                return self.result(task)
            time.sleep(min(0.5, max(0, deadline - time.monotonic())))

    def send(
        self,
        message: str,
        *,
        expert_id: str | None = None,
        task_id: str | None = None,
        command_id: str | None = None,
        wait: float = 30,
    ) -> dict[str, Any]:
        command_id = command_id or uuid.uuid4().hex
        if not message.strip() or len(message) > 50_000:
            raise ExpertClientError("invalid_message", command_id=command_id)
        try:
            if self._journal:
                private_state_dir(self._journal)
                self._record_path = self._command_path(command_id)
                with ProcessLock(self._record_path.with_suffix(".lock")):
                    _reject_links(self._record_path)
                    fingerprint = hashlib.sha256(
                        json.dumps([message, expert_id, task_id], ensure_ascii=False).encode(
                            "utf-8"
                        )
                    ).hexdigest()
                    if self._record_path.exists():
                        record = json.loads(self._record_path.read_text(encoding="utf-8"))
                        if record.get("fingerprint") != fingerprint:
                            raise ExpertClientError("command_conflict")
                        recovered = self.find(command_id)["task"]
                        if recovered is None:
                            raise ExpertClientError(
                                "request_unconfirmed", task_id=record.get("target_task_id")
                            )
                        return self._wait_result(recovered["task_id"], wait, command_id)
                    self._record = {"fingerprint": fingerprint}
                    return self._send(
                        message,
                        expert_id=expert_id,
                        task_id=task_id,
                        command_id=command_id,
                        wait=wait,
                    )
            return self._send(
                message, expert_id=expert_id, task_id=task_id, command_id=command_id, wait=wait
            )
        except ProcessAlreadyRunning:
            raise ExpertClientError("command_busy", command_id=command_id) from None
        except ExpertClientError as exc:
            exc.command_id = exc.command_id or command_id
            raise
        finally:
            self._record_path = None

    def _command_path(self, command_id: str) -> Path:
        assert self._journal is not None
        key = hashlib.sha256(
            f"{self.server}\n{self._credential_id}\n{command_id}".encode()
        ).hexdigest()
        return self._journal / f"{key}.json"

    def _record_send(self, kind: str, target_task_id: str | None = None) -> None:
        if self._record_path:
            save_private_json(
                self._record_path,
                {**self._record, "kind": kind, "target_task_id": target_task_id},
            )

    def _wait_result(self, task_id: str, wait: float, command_id: str) -> dict[str, Any]:
        try:
            return {**self.wait(task_id, wait), "command_id": command_id}
        except ExpertClientError as exc:
            exc.task_id = task_id
            raise

    def _send(
        self,
        message: str,
        *,
        expert_id: str | None,
        task_id: str | None,
        command_id: str,
        wait: float,
    ) -> dict[str, Any]:
        match = self.find(command_id)["task"]
        if match:
            existing = self.detail(match["task_id"])
            if (
                (expert_id is not None and existing["agent_id"] != expert_id)
                or (task_id is None and existing["instructions"] != message)
                or (
                    task_id is not None
                    and (
                        not existing["instructions"].endswith(f"\n\nCurrent request:\n{message}")
                        or existing["origin_thread_id"] != self.detail(task_id)["origin_thread_id"]
                    )
                )
            ):
                raise ExpertClientError("command_conflict", command_id=command_id)
            return self._wait_result(existing["task_id"], wait, command_id)
        previous = self.detail(task_id) if task_id else None
        if previous and previous["status"] == "unknown":
            raise ExpertClientError("unknown_task", command_id=command_id)
        if previous and previous["status"] not in TERMINAL:
            self._record_send("input", previous["task_id"])
            try:
                self.request(
                    "POST",
                    f"/api/work-items/{self._id(previous['task_id'])}/inputs",
                    {"text": message, "command_id": command_id, "schema_version": 1},
                )
            except ExpertClientError as exc:
                exc.task_id = previous["task_id"]
                raise
            return self._wait_result(previous["task_id"], wait, command_id)
        if previous:
            expert_id = previous["agent_id"]
            thread_id = previous["origin_thread_id"]
            context = str(previous.get("instructions") or "")
            context += "\n" + "\n".join(
                f"{item['role']}: {_text(item)}" for item in self.history(previous)
            )
            instructions = (
                f"Previous conversation:\n{context[-24000:]}\n\nCurrent request:\n{message}"
            )
        else:
            if not expert_id:
                raise ExpertClientError("missing_expert")
            thread = self.request("POST", f"/api/agents/{self._id(expert_id)}/threads")
            thread_id = thread["thread_id"]
            instructions = message
        self._record_send("create")
        created = self.request(
            "POST",
            "/api/work-items",
            {
                "command_id": command_id,
                "agent_id": expert_id,
                "origin_thread_id": thread_id,
                "title": message[:80],
                "instructions": instructions,
                "schema_version": 1,
            },
        )
        return self._wait_result(created["task_id"], wait, command_id)
