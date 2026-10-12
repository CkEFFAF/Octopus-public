# 同账号自动登记运维说明（0004）

规格：docs/specs/0004-same-account-auto-enroll.md（Accepted）。
合同：docs/octopus/device-network-contract.md。

本文件可被 git 跟踪，供交接与验收引用。本机局域网 IP、防火墙规则等私有步骤仍写在被 ignore 的 deploy-other-devices.md，勿把本机地址提交进仓库。

## 推荐：账号登录登记

同一账号在设备客户端登录控制中心后即可自动登记进设备列表，无需先发配对码或接入密钥。默认以最小能力入网（可空 capabilities/permissions/roots）；名称、共享目录、桌面/命令等事后再配。

`at
REM Windows：首次登记（密码优先交互输入，勿把明文挂在命令行）
octop device connect --server https://<controller> --username <账号>
REM 成功后写入 ~/.octop-device（或 --state），之后无参 start-device / device run 即可重连
`

`ash
# Linux
octop device connect --server https://<controller> --username <account>
# 或交互：setup-device / device join，选择「账号密码登录」
`

也可先密码登录拿到短 JWT，再：

`ash
octop device connect --server https://<controller> --account-token <短JWT>
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

## 扩权现状（MVP）

扩大权限 **不能** 仅靠管理端 PATCH /devices/{id}。

当前实现：

- **拒扩大**：DeviceService.update / PATCH 只能减到客户端已声明能力内；扩大请求失败。
- **重登记**：需要更大能力时，在控制中心撤销旧设备（或使用新的独立 --state），在设备端用更大本地能力声明重新 enroll（账号登录 / 配对码 / 接入密钥均可）。

现状 = **拒扩大 + 重登记**，属 **非完整** 设备端确认协议（无独立 challenge/ACK 扩权流）。完整设备端同意流属 P1+；验收 AE-03「扩大权限无设备端同意则失败」由拒扩大覆盖。

## 备用路径（保留）

- 配对码：octop device connect --server URL --pair-code CODE ...
- 接入密钥：推荐 --key-file 私有 UTF-8 文件，避免进程参数留下明文。

## 验收指针

见 0004 §7 AE-01…AE-08。单元测试入口：

`	ext
uv run pytest tests/unit/devices/test_api.py tests/unit/devices/test_service.py tests/unit/devices/test_join.py tests/unit/devices/test_client.py tests/unit/devices/test_device_cli.py -q
`
