"""Interactive first setup and explicit OS startup opt-in for device clients."""

from __future__ import annotations

import platform
from pathlib import Path

import click

from octop.infra.devices import autostart as startup
from octop.infra.devices.executor import DeviceExecutionError


@click.command("join")
@click.option("--server", help="Management host URL; otherwise ask interactively.")
@click.option(
    "--state",
    type=click.Path(file_okay=False, path_type=Path),
    default=lambda: Path.home() / ".octop-device",
)
@click.pass_context
def join(ctx: click.Context, server: str | None, state: Path) -> None:
    """Guide first enrollment, then connect; later launches reuse saved permissions."""
    from octop.infra.devices.client import validate_server_url
    from octop.infra.devices.network import DeviceNetwork, validate_relocation_url

    system = platform.system()
    if system not in {"Windows", "Linux"}:
        raise click.ClickException("Native device connections are supported on Windows and Linux.")
    assert ctx.parent is not None
    group = ctx.parent.command
    assert isinstance(group, click.Group)
    run = group.get_command(ctx.parent, "run")
    enroll = group.get_command(ctx.parent, "add-controller")
    assert run is not None and enroll is not None
    try:
        controllers = DeviceNetwork(state).controllers()
        if any(item.get("status") == "configured" for item in controllers):
            if server:
                raise click.UsageError(
                    "saved connections already exist; use device add-controller for another host"
                )
            click.echo("使用已保存的设备身份和权限连接。Ctrl+C 停止客户端。")
            ctx.invoke(run, state=state)
            return
        server = validate_relocation_url(
            server or click.prompt("管理端地址（浏览器访问的完整地址）", type=str).strip()
        )
        allow_insecure = False
        try:
            validate_server_url(server)
        except DeviceExecutionError:
            allow_insecure = click.confirm(
                "该 HTTP 连接未加密，仅用于可信网络联调。仍然使用？", default=False
            )
            if not allow_insecure:
                raise click.Abort() from None
        name = click.prompt("设备名称", default=platform.node())
        click.echo("1 文件和终端（读写共享目录，命令逐次确认）")
        if system == "Windows":
            click.echo("2 桌面和文件（桌面查看、键鼠控制、共享目录读写）")
        click.echo("3 仅查看文件\n4 自定义权限")
        profile = click.prompt(
            "权限方案",
            type=click.Choice(["1", "2", "3", "4"] if system == "Windows" else ["1", "3", "4"]),
            default="2" if system == "Windows" else "1",
        )
        shared = (
            click.prompt(
                "共享目录（仅此目录；不存在时创建）",
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
            control = desktop and click.confirm("允许键鼠控制？", default=False)
            allow_command = click.confirm("允许逐次确认后执行命令？", default=False)
        click.echo(f"管理端：{server}\n设备：{name}\n共享目录：{shared}")
        click.echo("文件：" + ("只读" if read_only else "读写"))
        click.echo("桌面：" + ("查看和控制" if control else "仅查看" if desktop else "关闭"))
        click.echo("命令：" + ("每次确认后以当前系统用户执行" if allow_command else "关闭"))
        if allow_command:
            click.echo("共享目录限制文件传输；命令以当前用户权限执行，不是系统沙箱。")
        click.confirm("信任该管理端并按以上权限接入？", default=False, abort=True)
        credential = click.prompt(
            "配对码或设备接入密钥（在管理端「设备」页生成，隐藏输入）", hide_input=True
        ).strip()
        if not credential:
            raise click.ClickException("配对码或设备接入密钥不能为空。")
        shared.mkdir(parents=True, exist_ok=True)
        ctx.invoke(
            enroll,
            server=server,
            pair_code=None if credential.startswith("oak_") else credential,
            access_key=credential if credential.startswith("oak_") else None,
            key_file=None,
            name=name,
            share=(shared,),
            read_only=read_only,
            desktop=desktop,
            control=control,
            allow_command=allow_command,
            allow_insecure=allow_insecure,
            state=state,
        )
        click.echo("接入已保存，正在连接；以后直接运行同一个入口。Ctrl+C 停止。")
        ctx.invoke(run, state=state)
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
    click.echo("添加受信任管理端；每个端独立授权，项目和聊天不自动同步。")
    server = click.prompt("管理端 HTTPS 地址", type=str).strip()
    allow_insecure = False
    if server.startswith("http://"):
        from octop.infra.devices.client import validate_server_url

        try:
            validate_server_url(server)
        except DeviceExecutionError:
            allow_insecure = click.confirm(
                "该 HTTP 连接未加密，仅用于可信网络联调。仍然使用？", default=False
            )
            if not allow_insecure:
                raise click.Abort() from None
    access_key = click.prompt("粘贴管理端生成的设备接入密钥（隐藏输入）", hide_input=True).strip()
    name = click.prompt("当前设备名字", default=platform.node())
    shared = click.prompt("共享目录（留空不共享）", default="", show_default=False)
    share: tuple[Path, ...] = ()
    read_only = True
    if shared:
        path = Path(shared).expanduser().absolute()
        if not path.is_dir():
            raise click.ClickException("共享目录不存在；请先创建目录。")
        share = (path,)
        read_only = not click.confirm("允许向该目录写入文件？", default=False)
    desktop = platform.system() == "Windows" and click.confirm(
        "允许查看这台 Windows 的桌面？", default=False
    )
    control = desktop and click.confirm("允许通过该管理端操作键盘和鼠标？", default=False)
    allow_command = click.confirm(
        "允许管理端提交经确认的命令？命令按当前 OS 用户运行。", default=False
    )
    if allow_command and not share:
        raise click.ClickException("命令执行需要共享工作目录。请重新配置并指定目录。")
    assert ctx.parent is not None
    group = ctx.parent.command
    assert isinstance(group, click.Group)
    command = group.get_command(ctx.parent, "add-controller")
    assert command is not None
    ctx.invoke(
        command,
        server=server,
        pair_code=None,
        access_key=access_key,
        key_file=None,
        name=name,
        share=share,
        read_only=read_only,
        desktop=desktop,
        control=control,
        allow_command=allow_command,
        allow_insecure=allow_insecure,
        state=state,
    )
    click.echo("配置已保存。以后直接运行 start-device；新增管理端再次运行 setup-device。")
