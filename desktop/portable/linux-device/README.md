# Linux 无界面设备客户端

这个包只运行后台设备连接、共享目录与明确授权的命令。它不启动 Web UI、账号数据库或管理服务，不需要桌面、浏览器、X11 或 LLM 配置。任意已分别授权的 Windows 管理端都能操作它；某个管理端关机不会断开其他连接。

## 构建与平台

支持 `linux-amd64`（`uname -m` 为 `x86_64`）和 `linux-arm64`（`aarch64`）。不支持 ARM32、Alpine/musl 或 Windows runtime 混装。

从当前修改后的源码根目录构建：

```bash
bash desktop/portable/package-device-linux.sh linux-amd64
# ARM64 Linux 使用：
bash desktop/portable/package-device-linux.sh linux-arm64
```

也可使用已可用的 Docker 环境：

```bash
bash desktop/portable/package-device-linux.sh linux-amd64 --docker
# ARM64 跨架构需要 Docker 已配置该架构执行能力；脚本不会安装模拟器。
```

构建机需要 Bash、tar、curl 和 uv；原生构建自动复用或下载项目固定的 Python 3.12 portable runtime，只安装 `uv.lock` 中带 SHA-256 校验的 click/websockets 二进制轮子，Linux wheel 限定 manylinux 2.17 基线。部署机器无需系统 Python 3.12，无需安装完整 Octop 依赖或先构建界面。输出在 `desktop/portable/release/Octop-device-linux-<arch>-<version>.tar.gz`。

首次在线构建后，可用 `OCTOP_GREEN_OFFLINE=1` 重用同一架构的 runtime 和 `desktop/portable/.cache/uv` 缓存，禁止网络访问；离线 Docker 构建需要镜像本身已安装 uv。Windows Git Bash 可以跨平台组装包，直接保留官方 runtime tar 的 Linux 权限和符号链接，不在 NTFS 上解压 Linux runtime；不会执行 Linux runtime，也不会将其标为原生验收通过。

Ubuntu 20.04 的 glibc 2.31 高于 Python portable GNU/Linux baseline 2.17，预期可运行；仍需匹配 CPU 并在目标机器执行 runtime/CLI/连接验收。[Python-build-standalone 官方运行要求](https://gregoryszorc.com/docs/python-build-standalone/main/running.html#runtime-requirements)说明该 baseline；不能将 Windows 上打包成功等同 Ubuntu 验收。

包内 `VERSION.txt` 的 `verification` 区分原生导入/CLI 冒烟通过与尚未原生运行的跨平台组装。包中没有账号、数据库、`device-state`、连接密钥、Windows 二进制或 Web UI。不得把已有 `device-state` 放进分发包。

## 第一次连接

**open-device primary path (0007)**: after extract run `./open-device.sh`. Wizard default server is `https://octop.effaf.me` (override with `OCTOP_DEVICE_SERVER` or `--server`). Account password auto-enrolls same-account device (0004); name/share/fine permissions later on manager (0005). Headless fallback: `./start-device.sh` / `./setup-device.sh` (pair-code / access-key path).


将匹配架构的包传到 Linux，使用普通 OS 用户解压到固定目录。示例：

```bash
mkdir -p "$HOME/apps"
tar -xzf Octop-device-linux-amd64-1.0.2b7.tar.gz -C "$HOME/apps"
cd "$HOME/apps/Octop-device-linux-amd64"
chmod +x open-device.sh setup-device.sh start-device.sh
./runtime/bin/python3 -c 'import platform, ssl; print(platform.machine(), ssl.OPENSSL_VERSION)'
# Primary (0006/0007): first-run wizard, default https://octop.effaf.me
./open-device.sh
```

首次运行直接进入向导：填写管理端地址、设备名字，选择文件和终端或只读等权限方案，确认共享目录与权限，然后隐藏输入管理端生成的配对码或接入密钥。共享目录不存在时会在确认后创建。接入成功立即连接，以后仍使用同一个 `start-device.sh`，无需重复配对。命令以当前 Linux 用户执行，共享目录限制不构成 OS 命令沙箱。

密钥由该 Windows 管理端登录后的设备页面生成。不要使用 Windows 登录密码。HTTPS 默认核验系统信任证书；HTTP 联调需明确确认且流量未加密。凭据只保存在当前用户的私有 `device-state`，不写入启动命令或 systemd 单元。

配置后前台运行：

```bash
./start-device.sh
```

关闭页面不会关闭客户端；关闭该命令的终端会停止前台客户端。再次运行无需填地址或密钥，按保存身份自动恢复所有连接。添加另一个可信 Windows 管理端时先停止当前客户端，再运行 `./setup-device.sh` 添加，之后 `./start-device.sh` 同时连接两个管理端。账号、项目、聊天和看板账本仍分别属于各管理端，不会因同名账号自动同步。

## 后台启动与开机恢复

先停止前台 `start-device.sh`，然后明确安装当前用户的 systemd 服务：

```bash
./setup-device.sh autostart install
./setup-device.sh autostart status
```

安装会提示确认并启动保存的全部连接，使用普通用户权限。无界面服务器若需要登出和重启后继续运行，管理员明确执行一次：

```bash
sudo loginctl enable-linger "$USER"
```

这是 systemd 用户服务登出/开机运行条件，不是端口开放。客户端只主动连管理端，不监听设备入站端口。没有 systemd 用户会话、D-Bus 或 linger 权限时，安装会报错；可继续使用前台运行，不会伪报自启动成功。

查看服务名、连接目录及日志：

```bash
./setup-device.sh controllers
./runtime/bin/python3 ./launch.py device autostart status --state "$PWD/device-state"
systemctl --user list-units 'octop-device-*.service'
# 将上一步显示的服务名填入：
journalctl --user -u octop-device-实际服务名.service -n 80 --no-pager
```

停止并移除自动启动（保留设备身份和账本）：

```bash
./setup-device.sh autostart remove
```

移动包目录前先移除自启动，再搬迁并重新安装；单元保存的是绝对 runtime 和状态路径。管理端离线会独立退避重连，不需要重装。身份被撤销或配置损坏时该管理端显示需要处理，其他端继续运行；停止客户端后修复/重新授权即可。

## 验收边界

至少在目标 Linux 验证：CPU/runtime 匹配、向导加入、Windows 设备页在线、共享文件读取、经确认的命令执行、停掉一个管理端后另一端仍可操作、重启自动连接、授权撤销和日志无明文密钥。原生导入冒烟不能替代这些实机行为。

当前命令属于派工管理端；该连接断开会取消其命令并保留未确认状态，不会转移到另一个管理端。文件上传中断需重新开始，未提供断点续传。无界面 Linux 不提供桌面捕获或键鼠操作。

## Filing-period transition (0010)

Default remains https://octop.effaf.me. Before domain filing:

`ash
export OCTOP_DEVICE_SERVER=http://111.228.42.228:8188
./open-device.sh
# or: ./open-device-transition.sh
`

Unset OCTOP_DEVICE_SERVER to return to the HTTPS product default.

