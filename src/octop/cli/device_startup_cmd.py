"""Interactive first setup and explicit OS startup opt-in for device clients."""

from __future__ import annotations

import platform
from pathlib import Path

import click

from octop.infra.devices import autostart as startup
from octop.infra.devices.executor import DeviceExecutionError
from octop.infra.devices.protocol import (
    DEFAULT_DEVICE_SERVER,
    is_transition_insecure_allowed,
    resolve_default_device_server,
)

def _device_group(ctx: click.Context) -> tuple[click.Context, click.Group]:
    """Resolve the ``device`` Click group even when nested via ctx.invoke."""
    current = ctx
    while current is not None:
        if isinstance(current.command, click.Group) and current.command.get_command(current, "run"):
            return current, current.command
        current = current.parent
    raise click.ClickException("device command group is unavailable")



def _prompt_server(server: str | None) -> tuple[str, bool]:
    """Return (url, allow_insecure) with env/product default prefilled (0006/0010)."""
    from octop.infra.devices.client import validate_server_url
    from octop.infra.devices.network import validate_relocation_url

    default_url = resolve_default_device_server()
    raw = server or click.prompt(
        "管理端地址",
        default=default_url,
        type=str,
    ).strip()
    url = validate_relocation_url(raw)
    # 0010 DEC-T06: filing-period whitelist skips insecure confirm.
    if is_transition_insecure_allowed(url):
        validate_server_url(url, allow_insecure=True)
        return url, True
    allow_insecure = False
    try:
        validate_server_url(url)
    except DeviceExecutionError:
        allow_insecure = click.confirm(
            "该 HTTP 地址未加密，仅适于本地调试。确认仍然使用？",
            default=False,
        )
        if not allow_insecure:
            raise click.Abort() from None
        validate_server_url(url, allow_insecure=True)
    return url, allow_insecure


@click.command("join")
@click.option(
    "--server",
    help=f"Management host URL (default: {DEFAULT_DEVICE_SERVER}; override with OCTOP_DEVICE_SERVER).",
)
@click.option(
    "--username",
    help="Account username for same-account auto-enroll (0004/0006 primary path).",
)
@click.option(
    "--password",
    prompt=False,
    hide_input=True,
    help="Account password (prefer interactive prompt; never stored).",
)
@click.option(
    "--account-token",
    prompt=False,
    help="Short-lived Bearer JWT; skips password when already signed in (never stored).",
)
@click.option("--name", help="Device name shown on the management host.")
@click.option(
    "--advanced",
    is_flag=True,
    help="Ask permission profile / pairing key (legacy guided path); prefer setup for this.",
)
@click.option(
    "--state",
    type=click.Path(file_okay=False, path_type=Path),
    default=lambda: Path.home() / ".octop-device",
)
@click.pass_context
def join(
    ctx: click.Context,
    server: str | None,
    username: str | None,
    password: str | None,
    account_token: str | None,
    name: str | None,
    advanced: bool,
    state: Path,
) -> None:
    """First-run UU join: default server + account password, then connect (0006).

    Later launches reuse saved identity. Fine permissions / shares are configured later
    (0004 register-first + 0005). Use --advanced or ``device setup`` for pairing keys
    and custom local consent.
    """
    from octop.infra.devices.first_run import (
        enroll_with_account,
        enroll_with_credential,
        has_configured_controller,
    )
    from octop.infra.devices.network import DeviceNetwork

    system = platform.system()
    if system not in {"Windows", "Linux"}:
        raise click.ClickException("Native device connections are supported on Windows and Linux.")
    group_ctx, group = _device_group(ctx)
    run = group.get_command(group_ctx, "run")
    assert run is not None
    try:
        if has_configured_controller(state):
            if server or username or password or account_token or advanced:
                raise click.UsageError(
                    "saved connections already exist; use device add-controller for another host"
                )
            click.echo("使用已保存的设备身份和权限连接。Ctrl+C 停止客户端。")
            ctx.invoke(run, state=state)
            return

        if advanced:
            _join_advanced(ctx, server=server, state=state, system=system)
            return

        url, allow_insecure = _prompt_server(server)
        device_name = name or click.prompt("设备名称", default=platform.node())
        token = account_token
        user = username
        secret = password
        if not token:
            user = (user or click.prompt("管理端账号用户名")).strip()
            if not secret:
                secret = click.prompt("管理端账号密码", hide_input=True)
            if not user or not secret:
                raise click.ClickException("账号用户名和密码不能为空。")
        click.echo(
            f"管理端：{url}\n设备：{device_name}\n"
            "默认权限：桌面查看/控制 + 文件读取（共享目录与细权限可事后配置）。"
        )
        click.confirm("使用该账号登记并连接？", default=True, abort=True)
        enroll_with_account(
            state,
            server=url,
            username=user or "",
            password=secret or "",
            name=device_name,
            allow_insecure=allow_insecure,
            account_token=token,
        )
        click.echo("登记已保存，正在连接；以后直接启动同一入口。Ctrl+C 停止。")
        ctx.invoke(run, state=state)
    except (OSError, DeviceExecutionError) as exc:
        raise click.ClickException(str(exc)) from None


def _join_advanced(
    ctx: click.Context, *, server: str | None, state: Path, system: str
) -> None:
    """Legacy permission-profile join; kept for scripts and pair/key enrollment."""
    group_ctx, group = _device_group(ctx)
    run = group.get_command(group_ctx, "run")
    enroll = group.get_command(group_ctx, "add-controller")
    assert run is not None and enroll is not None

    url, allow_insecure = _prompt_server(server)
    name = click.prompt("设备名称", default=platform.node())
    click.echo("1 文件工作终端（读写共享目录；可选命令确认）")
    if system == "Windows":
        click.echo("2 远程桌面文件（可查看并控制桌面；共享目录读写）")
    click.echo("3 只查看文件\n4 自定义权限")
    profile = click.prompt(
        "权限方案",
        type=click.Choice(["1", "2", "3", "4"] if system == "Windows" else ["1", "3", "4"]),
        default="2" if system == "Windows" else "1",
    )
    shared = (
        click.prompt(
            "共享目录（本地目录，不存在时将创建）",
            default=str(state.absolute().parent / "OctopShare"),
            type=click.Path(file_okay=False, path_type=Path),
        )
        .expanduser()
        .absolute()
    )
    read_only = profile == "3"
    desktop = profile == "2"
    control = desktop
    allow_command = profile == "1"
    if profile == "4":
        read_only = not click.confirm("允许写入共享目录？", default=False)
        desktop = system == "Windows" and click.confirm("允许查看桌面？", default=False)
        control = desktop and click.confirm("允许桌面控制？", default=False)
        allow_command = click.confirm("允许每次确认后执行命令？", default=False)
    allow_acp = not read_only and click.confirm(
        "允许专家调用本地 ACP 工作区？代理可按当前用户权限读写与执行命令，且需在设备端再次确认",
        default=False,
    )
    click.echo(f"管理端：{url}\n设备：{name}\n共享目录：{shared}")
    click.echo("文件：" + ("只读" if read_only else "读写"))
    click.echo("桌面：" + ("查看和控制" if control else "仅查看" if desktop else "关闭"))
    click.echo("命令：" + ("每次确认后以当前系统用户执行" if allow_command else "关闭"))
    click.echo("ACP 工作区：" + ("以当前系统用户运行" if allow_acp else "关闭"))
    if allow_command:
        click.echo("共享目录用于文件传输；命令以当前用户权限执行，非系统沙箱。")
    click.confirm("信任该管理端并按以上权限加入？", default=False, abort=True)
    auth_mode = click.prompt(
        "登记方式：1 账号密码登录  2 设备接入密钥/配对码",
        type=click.Choice(["1", "2"]),
        default="1",
    )
    username = None
    password = None
    pair_code = None
    access_key = None
    if auth_mode == "1":
        username = click.prompt("管理端账号用户名").strip()
        password = click.prompt("管理端账号密码", hide_input=True)
        if not username or not password:
            raise click.ClickException("账号用户名和密码不能为空。")
    else:
        credential = click.prompt(
            "粘贴一次性设备接入密钥或配对码（输入时隐藏）", hide_input=True
        ).strip()
        if not credential:
            raise click.ClickException("设备接入密钥或配对码不能为空。")
        if credential.startswith("oak_"):
            access_key = credential
        else:
            pair_code = credential
    shared.mkdir(parents=True, exist_ok=True)
    ctx.invoke(
        enroll,
        server=url,
        pair_code=pair_code,
        access_key=access_key,
        key_file=None,
        username=username,
        password=password,
        account_token=None,
        name=name,
        share=(shared,),
        read_only=read_only,
        desktop=desktop,
        control=control,
        allow_command=allow_command,
        allow_acp=allow_acp,
        allow_insecure=allow_insecure,
        state=state,
    )
    click.echo("登记已保存，正在连接；以后直接启动同一入口。Ctrl+C 停止。")
    ctx.invoke(run, state=state)


@click.command("first-run")
@click.option(
    "--server",
    help=f"Management host URL (default: {DEFAULT_DEVICE_SERVER}; override with OCTOP_DEVICE_SERVER).",
)
@click.option(
    "--cli",
    "force_cli",
    is_flag=True,
    help="Force the text wizard even when a GUI is available.",
)
@click.option(
    "--state",
    type=click.Path(file_okay=False, path_type=Path),
    default=lambda: Path.home() / ".octop-device",
)
@click.pass_context
def first_run(
    ctx: click.Context,
    server: str | None,
    force_cli: bool,
    state: Path,
) -> None:
    """0006 entry: GUI first-run when possible, else UU text join; reconnect if enrolled."""
    from octop.infra.devices.first_run import gui_available, has_configured_controller, run_tk_first_run

    if platform.system() not in {"Windows", "Linux"}:
        raise click.ClickException("Native device connections are supported on Windows and Linux.")
    group_ctx, group = _device_group(ctx)
    run = group.get_command(group_ctx, "run")
    join_cmd = group.get_command(group_ctx, "join")
    assert run is not None and join_cmd is not None
    try:
        if has_configured_controller(state):
            click.echo("使用已保存的设备身份连接。Ctrl+C 停止客户端。")
            ctx.invoke(run, state=state)
            return
        if not force_cli and gui_available():
            added = run_tk_first_run(state, server=server)
            if added is None:
                raise click.Abort()
            click.echo("登记已保存，正在连接。Ctrl+C 停止。")
            ctx.invoke(run, state=state)
            return
        ctx.invoke(
            join_cmd,
            server=server,
            username=None,
            password=None,
            account_token=None,
            name=None,
            advanced=False,
            state=state,
        )
    except (OSError, DeviceExecutionError) as exc:
        raise click.ClickException(str(exc)) from None


@click.group()
def autostart() -> None:
    """Install, inspect or remove startup under your own OS user (explicit opt-in)."""


@autostart.command("install")
@click.option(
    "--state",
    type=click.Path(file_okay=False, path_type=Path),
    default=lambda: Path.home() / ".octop-device",
)
@click.option("--yes", is_flag=True, help="Confirm installing and starting this saved network.")
def install(state: Path, yes: bool) -> None:
    """Windows: login task. Linux: systemd user service; no UI or account password."""
    from octop.infra.devices.network import DeviceNetwork

    try:
        if not any(
            item.get("status") == "configured" for item in DeviceNetwork(state).controllers()
        ):
            raise DeviceExecutionError("configure a controller with device setup first")
        if not yes:
            click.confirm(
                "Install startup and connect all saved controllers with their saved permissions?",
                abort=True,
            )
        click.echo(startup.install(state))
    except (OSError, DeviceExecutionError) as exc:
        raise click.ClickException(str(exc)) from None


@autostart.command("remove")
@click.option(
    "--state",
    type=click.Path(file_okay=False, path_type=Path),
    default=lambda: Path.home() / ".octop-device",
)
@click.option("--yes", is_flag=True, help="Confirm stopping and removing this startup task.")
def remove(state: Path, yes: bool) -> None:
    if not yes:
        click.confirm(
            "Stop this startup task and remove automatic launch (keep device identities)?",
            abort=True,
        )
    try:
        click.echo(startup.uninstall(state))
    except (OSError, DeviceExecutionError) as exc:
        raise click.ClickException(str(exc)) from None


@autostart.command("status")
@click.option(
    "--state",
    type=click.Path(file_okay=False, path_type=Path),
    default=lambda: Path.home() / ".octop-device",
)
def status(state: Path) -> None:
    try:
        click.echo(startup.status(state))
    except (OSError, DeviceExecutionError) as exc:
        raise click.ClickException(str(exc)) from None


@click.command("setup")
@click.option(
    "--state",
    type=click.Path(file_okay=False, path_type=Path),
    default=lambda: Path.home() / ".octop-device",
)
@click.pass_context
def setup(ctx: click.Context, state: Path) -> None:
    """Guided first setup or addition of another trusted Windows controller."""
    click.echo("添加或配置另一管理端；每个端独立授权，项目与账本不自动同步。")
    server, allow_insecure = _prompt_server(None)
    auth_mode = click.prompt(
        "登记方式：1 账号密码登录  2 设备接入密钥",
        type=click.Choice(["1", "2"]),
        default="1",
    )
    username = None
    password = None
    access_key = None
    if auth_mode == "1":
        username = click.prompt("管理端账号用户名").strip()
        password = click.prompt("管理端账号密码", hide_input=True)
        if not username or not password:
            raise click.ClickException("账号用户名和密码不能为空。")
    else:
        access_key = click.prompt(
            "粘贴在管理端生成的设备接入密钥（输入时隐藏）", hide_input=True
        ).strip()
        if not access_key:
            raise click.ClickException("设备接入密钥不能为空。")
    name = click.prompt("当前设备名称", default=platform.node())
    shared = click.prompt("共享目录（可留空跳过）", default="", show_default=False)
    share: tuple[Path, ...] = ()
    read_only = True
    if shared:
        path = Path(shared).expanduser().absolute()
        if not path.is_dir():
            raise click.ClickException("共享目录不存在；请先创建目录。")
        share = (path,)
        read_only = not click.confirm("允许向该目录写入文件？", default=False)
    desktop = platform.system() == "Windows" and click.confirm(
        "允许查看本机 Windows 桌面画面？", default=False
    )
    control = desktop and click.confirm("允许通过该管理端操作键盘和鼠标？", default=False)
    allow_command = click.confirm(
        "允许运行经本机确认的命令？命令按当前 OS 用户运行。", default=False
    )
    if allow_command and not share:
        raise click.ClickException("命令执行需要至少一个共享目录；请重新配置并指定目录。")
    allow_acp = (
        bool(share)
        and not read_only
        and click.confirm(
            "允许专家调用本地 ACP 工作区？代理可按当前用户权限读写与执行命令，且需在设备端再次确认",
            default=False,
        )
    )
    group_ctx, group = _device_group(ctx)
    command = group.get_command(group_ctx, "add-controller")
    assert command is not None
    ctx.invoke(
        command,
        server=server,
        pair_code=None,
        access_key=access_key,
        key_file=None,
        username=username,
        password=password,
        account_token=None,
        name=name,
        share=share,
        read_only=read_only,
        desktop=desktop,
        control=control,
        allow_command=allow_command,
        allow_acp=allow_acp,
        allow_insecure=allow_insecure,
        state=state,
    )
    click.echo("配置已保存。以后直接运行 start-device；添加另一管理端再运行 setup-device。")