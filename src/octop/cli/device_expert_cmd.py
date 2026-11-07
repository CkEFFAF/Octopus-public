"""Commands local coding agents can call through the existing device program."""

from __future__ import annotations

import json
import sys
import uuid
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

import click

from octop.i18n import tr
from octop.infra.devices.expert_client import ExpertClient, ExpertClientError, ExpertConfig
from octop.infra.devices.network import DeviceNetwork
from octop.infra.utils.locale import DEFAULT_LOCALE


def _execute(action: Callable[[], dict[str, Any]]) -> None:
    try:
        payload = action()
        click.echo(json.dumps({"schema_version": 1, **payload}, ensure_ascii=False))
    except ExpertClientError as exc:
        click.echo(json.dumps(exc.payload(), ensure_ascii=False), err=True)
        raise click.exceptions.Exit(1) from None
    except (OSError, ValueError, KeyError, TypeError):
        error = ExpertClientError("invalid_response")
        click.echo(json.dumps(error.payload(), ensure_ascii=False), err=True)
        raise click.exceptions.Exit(1) from None


@click.group()
@click.option(
    "--state",
    type=click.Path(path_type=Path, file_okay=False),
    default=lambda: Path.home() / ".octop-device",
    envvar="OCTOP_DEVICE_STATE",
    help="Existing device state directory.",
)
@click.pass_context
def expert(ctx: click.Context, state: Path) -> None:
    """Configure an expert token and talk to cloud experts. Results are JSON."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            with suppress(ValueError, OSError):
                stream.reconfigure(encoding="utf-8", errors="replace")
    ctx.obj = {"state": state}


def _server(state: Path, server: str | None, controller: str | None) -> str:
    if server and controller:
        raise ExpertClientError("select_server")
    if server:
        return server
    controllers = [
        item
        for item in DeviceNetwork(state).controllers()
        if item.get("status") == "configured" and (controller is None or item["id"] == controller)
    ]
    if len(controllers) != 1:
        raise ExpertClientError("select_server")
    return str(controllers[0]["server_url"])


@expert.command()
@click.option("--server", help="Cloud server URL, or reuse the single saved controller.")
@click.option("--controller", help="Saved controller ID when more than one is configured.")
@click.option("--token-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.pass_obj
def configure(
    obj: dict[str, Any], server: str | None, controller: str | None, token_file: Path | None
) -> None:
    """Verify and privately save an expert token. Never pass the secret in argv."""

    def action() -> dict[str, Any]:
        endpoint = _server(obj["state"], server, controller)
        if token_file:
            with token_file.open("rb") as stream:
                raw = stream.read(4097)
            if len(raw) > 4096:
                raise ExpertClientError("invalid_token")
            try:
                token = raw.decode("utf-8-sig").strip()
            except UnicodeError:
                raise ExpertClientError("invalid_token") from None
        else:
            token = click.prompt(
                tr("device_expert.token_prompt", DEFAULT_LOCALE), hide_input=True, err=True
            )
        return ExpertConfig(obj["state"]).configure(endpoint, token)

    _execute(action)


@expert.command("config")
@click.pass_obj
def show_config(obj: dict[str, Any]) -> None:
    """Show the selected server and credential ID, without revealing the token."""
    _execute(lambda: ExpertConfig(obj["state"]).public())


@expert.command("list")
@click.pass_obj
def list_experts(obj: dict[str, Any]) -> None:
    """List the experts currently authorized by the configured token."""
    _execute(lambda: ExpertConfig(obj["state"]).client().identity())


def _message(message: str | None, message_file: Path | None) -> str:
    if message is not None and message_file is not None:
        raise ExpertClientError("invalid_message")
    text = (
        message
        if message is not None
        else message_file.read_text(encoding="utf-8")
        if message_file
        else click.get_text_stream("stdin").read()
    )
    if not text.strip() or len(text) > 50_000:
        raise ExpertClientError("invalid_message")
    return text


def _message_options(function: Any) -> Any:
    function = click.option("--message", help="Text to send, or read UTF-8 text from stdin.")(
        function
    )
    function = click.option(
        "--message-file", type=click.Path(exists=True, dir_okay=False, path_type=Path)
    )(function)
    function = click.option("--command-id", type=click.STRING, help="Caller idempotency key.")(
        function
    )
    return click.option("--wait", type=click.IntRange(0, 300), default=30, show_default=True)(
        function
    )


@expert.command()
@click.option("--expert", "expert_id", required=True)
@_message_options
@click.pass_obj
def ask(
    obj: dict[str, Any],
    expert_id: str,
    message: str | None,
    message_file: Path | None,
    command_id: str | None,
    wait: int,
) -> None:
    """Start a cloud conversation. Keep the returned task_id for follow-ups."""
    _execute(
        lambda: (
            ExpertConfig(obj["state"])
            .client()
            .send(
                _message(message, message_file),
                expert_id=expert_id,
                command_id=command_id,
                wait=wait,
            )
        )
    )


@expert.command()
@click.option("--task", "task_id", required=True)
@_message_options
@click.pass_obj
def reply(
    obj: dict[str, Any],
    task_id: str,
    message: str | None,
    message_file: Path | None,
    command_id: str | None,
    wait: int,
) -> None:
    """Continue a task, or start the next turn with the completed task's context."""
    _execute(
        lambda: (
            ExpertConfig(obj["state"])
            .client()
            .send(
                _message(message, message_file),
                task_id=task_id,
                command_id=command_id,
                wait=wait,
            )
        )
    )


@expert.command("get")
@click.option("--task", "task_id", required=True)
@click.pass_obj
def get_task(obj: dict[str, Any], task_id: str) -> None:
    """Read current progress and the available reply. Does not send a message."""

    def action() -> dict[str, Any]:
        client = ExpertConfig(obj["state"]).client()
        return client.result(client.detail(task_id))

    _execute(action)


@expert.command("wait")
@click.option("--task", "task_id", required=True)
@click.option("--timeout", type=click.IntRange(0, 300), default=30, show_default=True)
@click.pass_obj
def wait_task(obj: dict[str, Any], task_id: str, timeout: int) -> None:
    """Wait for a result or a permission request, without repeating the question."""
    _execute(lambda: ExpertConfig(obj["state"]).client().wait(task_id, timeout))


@expert.command()
@click.option("--command-id", required=True)
@click.pass_obj
def find(obj: dict[str, Any], command_id: str) -> None:
    """Look up a task creation receipt after an unconfirmed send. Read only."""
    _execute(lambda: ExpertConfig(obj["state"]).client().find(command_id))


def _mutate(obj: dict[str, Any], task_id: str, action: str, body: dict[str, Any]) -> dict[str, Any]:
    client: ExpertClient = ExpertConfig(obj["state"]).client()
    result = client.request("POST", f"/api/work-items/{client._id(task_id)}/{action}", body)
    return {"task_id": task_id, "command_id": body["command_id"], "receipt": result}


@expert.command()
@click.option("--task", "task_id", required=True)
@click.option("--command-id", default=None)
@click.pass_obj
def cancel(obj: dict[str, Any], task_id: str, command_id: str | None) -> None:
    """Request cancellation; inspect the receipt or wait for server confirmation."""
    _execute(
        lambda: _mutate(
            obj,
            task_id,
            "cancel",
            {"command_id": command_id or uuid.uuid4().hex, "scope": "task", "schema_version": 1},
        )
    )


@expert.command()
@click.option("--task", "task_id", required=True)
@click.option("--attempt", required=True, help="Current attempt from get/wait.")
@click.option("--pending", required=True, help="Current permission_request.pending_id.")
@click.option("--decision", type=click.Choice(["approve", "reject"]), multiple=True, required=True)
@click.option("--command-id", default=None)
@click.pass_obj
def permission(
    obj: dict[str, Any],
    task_id: str,
    attempt: str,
    pending: str,
    decision: tuple[str, ...],
    command_id: str | None,
) -> None:
    """Explicitly answer the current permission request. Never approves automatically."""
    _execute(
        lambda: _mutate(
            obj,
            task_id,
            "permissions",
            {
                "command_id": command_id or uuid.uuid4().hex,
                "attempt_id": attempt,
                "pending_id": pending,
                "decisions": list(decision),
            },
        )
    )
