# 同账号自动登记运维说明（0004）

规格：docs/specs/0004-same-account-auto-enroll.md（Accepted）。
合同：docs/octopus/device-network-contract.md。

本文件可被 git 跟踪，供交接与验收引用。本机局域网 IP、防火墙规则等私有步骤仍写在被 ignore 的 deploy-other-devices.md，勿把本机地址提交进仓库。

## 开箱主路径（0006）

便携包双击 **`open-device.bat`**（Linux：`./open-device.sh`）：

1. 默认管理端 `https://octop.effaf.me`（可改）
2. 输入账号密码（优先交互；勿把密码写进脚本）
3. 按 0004 自动登记后保持连接；名称/共享/细权限事后在管理端配置（0005）

已登记后再次打开同一入口会直接重连。CLI 仍可用（见下）。

## 推荐：账号登录登记

同一账号在设备客户端登录控制中心后即可自动登记进设备列表，无需先发配对码或接入密钥。登记时按 0005 REQ-007 默认授予 desktop_view/desktop_control/files_read（∩ capabilities）；写文件/命令/ACP 事后在管理端勾选。名称与共享目录仍可事后配置。

`at
REM Windows：首次登记（密码优先交互输入，勿把明文挂在命令行）
octop device connect --server https://octop.effaf.me --username <账号>
REM 成功后写入 ~/.octop-device（或 --state），之后无参 start-device / device run 即可重连
`

`ash
# Linux
octop device connect --server https://octop.effaf.me --username <account>
# 或交互：setup-device / device join，选择「账号密码登录」
`

也可先密码登录拿到短 JWT，再：

`ash
octop device connect --server https://octop.effaf.me --account-token <短JWT>
`

--account-token 仅用于当次登记请求，**不得**写入 device-state。

## CLI 约定

| 项 | 约定 |
| --- | --- |
| --password | **优先交互输入**（仅 --username 时 CLI 会 click.prompt 隐藏输入）。不要鼓励把明文密码挂在命令行或脚本参数里；自动化可用 --account-token（短 JWT）或受控环境变量，仍勿写入 device-state。 |
| 凭证互斥 | 首次连接三选一：--pair-code / --key-file（或 --access-key）/ --username（或 --account-token）。 |
| 重连 | 已有未撤销 device-state 时无参重连，不新建设备行。 |
| 浏览器 | 仅打开网页登录 **不会** 把浏览端登记为执行设备。 |

CLI help 已注明：--password prefer interactive prompt；--account-token never stored in device-state。

## 扩权与默认权限（改走 0005）

账号自动登记的**登记入口**仍按本文件 / 0004。扩权与默认权限集以 **`docs/specs/0005-device-permission-management.md`**（revision 2026-10-12.3+）为准：

- 新建设备默认 permissions：`desktop_view` + `desktop_control` + `files_read`（∩ capabilities）
- 管理端可 PATCH 扩权至 capabilities；`files_write` 等在 `owner_auto` 且设备在线时立即生效
- `command_exec` / `acp_run` **强制设备端确认**（即使 owner_auto）
- 旧客户端（无 grant_proposal）扩权返回 CLIENT_OUTDATED，保留双轨提示升级

稳定入口：`--server https://octop.effaf.me`（Cloudflare Tunnel + 公网域名）；内网 IP / `--allow-insecure` 仅调试附录。

## 备用路径（保留）

- 配对码：octop device connect --server https://octop.effaf.me --pair-code CODE ...
- 接入密钥：推荐 --key-file 私有 UTF-8 文件，避免进程参数留下明文。

## 验收指针

见 0004 §7 AE-01…AE-08。单元测试入口：

`	ext
uv run pytest tests/unit/devices/test_api.py tests/unit/devices/test_service.py tests/unit/devices/test_join.py tests/unit/devices/test_client.py tests/unit/devices/test_device_cli.py -q
`
