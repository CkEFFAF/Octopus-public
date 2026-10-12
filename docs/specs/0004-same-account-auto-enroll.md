# 0004 同账号自动登记设备网（对标 UU 远程）

- Status: Accepted（用户 2026-10-12 定稿入库）
- Revision: 1 — 2026-10-12 MVP 实现说明：`POST /devices/enroll` 第三凭证为密码/SSO 用户 JWT（`Authorization: Bearer`）；key-session JWT（`auth_key_id`）拒绝登记，须改用 access_key 或密码登录；默认空 capabilities/permissions 入网；扩权仍走既有 PATCH 拒绝扩大（须设备端重新同意/登记）；CLI `--username`/`--password`/`--account-token`；配对码与 `--key-file` 保留。未实现可选 `POST /auth/device-login`（复用 `/auth/login`）。
- 建议路径: `docs/specs/0004-same-account-auto-enroll.md`
- 关联: `0001-account-device-network.md`、`device-network-contract.md`、`device-acp.md`、`0003-workstation-migration.md`

## Summary

各执行端用同一账号登录控制中心后自动登记进设备网；同账号可见全部已登记设备。登记与详细能力配置解耦：先入网，名称/共享目录/权限等事后配置。之上再挂「不同设备 × 不同 Agent」（会话/看板选设备或专家 `config.device_binding`）。中枢现为工位管理端，以后可按 0003 迁移；手机现阶段指挥，未来可执行（另规格）。

## 1. 问题与目标体验

### 问题

今日执行端进入设备网的主路径是：管理端发放配对码或设备接入密钥 → 本机 `setup-device` / `start-device` 显式 `enroll`。多机时密钥分发与重复登记摩擦大，不像 UU 远程「同一账号登录 → 机器出现在设备列表」。

### 目标体验（对标 UU）

1. 各执行端（笔记本、GPU 等）用**同一账号**在设备客户端登录控制中心。
2. 登录成功后**自动登记**为该账号下的一台设备（颁发或恢复 `odv_` 设备令牌）。
3. 同账号在任意控制端（工位 Dashboard / 手机浏览器）可见全部已登记设备及在线状态。
4. 名称、共享目录、桌面/命令等能力**事后在配置中修改**（见 §3）。
5. 之上挂不同设备 × 不同 Agent：会话/看板选 `device_id`，或专家 `config.device_binding`（既有语义，见 `device-acp.md`）。
6. 中枢现为工位机；以后可迁云/迁机（`0003`），账号与设备归属跟随所选控制中心。
7. 手机：现阶段浏览器指挥；未来作执行端另开规格。

## 2. 与现状差距

| 维度 | 现状（0001 / 合同） | 本规格 |
|---|---|---|
| 登记触发 | 配对码或 `allow_devices` 接入密钥 + `POST /devices/enroll`；AC-02 强调用户明确加入 | 设备客户端**账号登录成功 → 自动 enroll** |
| 能力确认时机 | 登记时确认名称/能力/共享目录 | **登记与配置解耦**：先入网，事后配置 |
| 日常重连 | `device-state` + `odv_`，无参 `start-device` | 保持 |
| 浏览器密钥 | `allow_browser` → JWT | 仍用于 Dashboard / 手机指挥 |
| 设备接入密钥 | 可 enroll；撤密钥不自动撤设备 | 保留为备用路径 |
| Agent × 设备 | 按次选设备；专家 `device_binding` | 不改语义 |

关键缺口：缺少「用账号会话在设备端完成登记」的一等公民流程。

## 3. 建议模型

### 3.1 身份

- **账号（User）**：控制中心用户；`owner_user_id` 仅由服务端从认证结果写入，禁止客户端自报（延续 AC-08）。
- **控制会话**：浏览器 JWT，或设备端账号登录短会话（可与 key-login 同源扩展）。
- **设备身份（Device）**：稳定 `device_id` + `odv_`；服务端只存 `token_hash`（沿用 `devices` 表）。

### 3.2 登记与配置解耦

- **登记（enroll）**：设备客户端持有效账号凭证调用登记 API → 创建或恢复本机在该账号下的设备行 → 返回 `odv_` 写入本地 `device-state`。默认以最小能力入网（例如仅在线心跳 + 基础元数据）；具体默认集实现时写清并文档化。
- **事后配置**：显示名、`roots`/共享目录、permissions（文件/桌面/命令/ACP 等）在设备客户端或管理端配置界面后续修改。
  - **缩减**权限：允许（管理端或设备端）。
  - **扩大**权限：必须经**设备端同意**（延续合同「不能单方面扩大」）；不得仅靠管理端 PATCH 加权。
- **重连**：已有未撤销的 `device-state` → 只做 WS `hello`，不新建设备。
- **撤销**：`POST /devices/{id}/revoke`；或设备端「退出并注销本机」。撤销账号登录密钥仍不自动撤销已登记设备（延续 AC-10）。P1 可提供「撤销该账号全部设备」。

### 3.3 在线

沿用 WS `/api/devices/connect/ws`，首帧 `hello{device_id,token}`；更新 `last_seen_at`；离线请求明确失败。

### 3.4 与专家绑定（正交）

- `devices` 行 = 机器挂在账号下（本规格）。
- `config.device_binding` = 专家固定操作某 `device_id` + 可写 `root_id`（`device-acp.md`）。**禁止**用 `device_binding` 表示「机器登记进账号」。
- 会话/看板当次选设备派工保留；有专家绑定时仍受绑定约束。

### 3.5 多管理端

延续 AC-11：可加入多个控制中心；每端独立凭据与账本；本规格不引入跨库同步。

### 3.6 对 0001 AC-02 的修订

AC-02 增加：在设备客户端完成账号认证并成功登记，视为「明确加入设备网」。登记时可不收集完整能力清单（改事后配置）。仍禁止「仅打开网页 / 登录另一独立实例」把浏览端静默登记为执行设备。

## 4. 安全边界

1. 登记 API 必须验证账号凭证；`owner_user_id` 仅服务端赋值。
2. 设备长连接信任 `odv_`，不是账号密码或浏览器 JWT；JWT/登录密钥不得写入 `device-state`。
3. 同账号多设备合法；每设备独立 `odv_`；泄漏则只 revoke 该 `device_id`。
4. revoke 后断开 WS、拒绝新操作；进行中按 AC-03。
5. 远程默认 HTTPS；正式验收不得依赖 `--allow-insecure`。
6. 扩大权限必须设备端同意。
7. 配对码与设备接入密钥路径保留作备用。

## 5. 分阶段

### MVP（本规格交付）

1. 设备客户端：账号登录控制中心 → 自动 enroll → 出现在同账号设备列表。
2. 详细名称/目录/权限事后配置（扩大须设备端同意）。
3. 保留配对码与 `--key-file` 路径。
4. Agent × 设备仍用选择器 / 看板 `device_id` / 既有 `device_binding`。
5. 回写合同 enroll 入参与 `deploy-other-devices.md` 步骤说明。

### P1+（完整 UU 体验，非本交付）

- 账号级一键下线全部设备、异常登录告警。
- 「信任本机 N 天」等会话策略细化。
- 手机原生执行端登记。
- 管理端迁移后设备列表跟随（对齐 0003）。
- 可选：Agent 默认设备字段（产品若要「一 bot 一机」持久绑定）。

## 6. 明确非目标

- 跨管理端账号/设备库同步；命令 failover。
- 用 `device_binding` 表示机器挂账号。
- 浏览器打开 Dashboard 即把该浏览环境登记为执行端。
- 手机首版后台执行客户端。
- 取消 `odv_`、改用纯账号 JWT 维持设备长连接。
- 管理端单方面扩大设备权限。
- 云中继 / NAT 穿透；小云机 / 第二管理端热备。

## 7. 接口与验收要点（给 Coder）

### API

- 扩展 `POST /devices/enroll`：除 `pairing_code` | `access_key` 外，支持**账号会话**（`Authorization: Bearer` 用户 JWT，且允许 device enroll；或专用 audience）。
- 响应仍为 `device` + `device_token`（`odv_`）；服务端写 `owner_user_id`，只存 `token_hash`。
- 可选：`POST /auth/device-login` → 短 JWT（`allow_device_enroll=true`）。
- 不变：`GET /devices`、`POST /devices/{id}/revoke`、WS hello。
- 配置类 API：在既有 permissions/roots 更新路径上落实「可减；扩大需设备端确认」的挑战/确认流（若尚未具备则 MVP 最小实现）。

### 客户端

- `setup-device` / `octop device connect` 增加「账号登录并登记」模式；成功写入 `device-state`。
- 无参 `start-device`：已登记则只重连。
- 提供事后配置入口（CLI 与/或本地 UI）。

### 验收（MVP）

1. **AE-01** 笔记本与 GPU 用同一账号在设备客户端登录后，工位 Dashboard 设备列表出现两台，`owner_user_id` 正确。
2. **AE-02** 仅打开网页登录、不跑设备客户端 → 不新增执行设备。
3. **AE-03** 事后修改显示名/共享目录成功；扩大权限无设备端同意则失败。
4. **AE-04** 撤销一台后该机不可派工，另一台不受影响。
5. **AE-05** 再无参 `start-device` 不创建重复设备。
6. **AE-06** 旧配对码 / `--key-file` 仍可用。
7. **AE-07** 专家 `device_binding` 与聊天选设备行为不变。
8. **AE-08** 在 HTTPS 正式路径下完成上述（HTTP + `--allow-insecure` 不得算验收通过）。

### 文档回写（可同 PR 或紧随）

- 本文件。
- `0001` AC-02：增加账号登录登记例外与「登记/配置解耦」一句。
- `docs/octopus/device-network-contract.md`：enroll 入参。
- `docs/octopus/deploy-other-devices.md`：增加「账号登录登记」步骤。

## References

- `docs/specs/0001-account-device-network.md`
- `docs/specs/0003-workstation-migration.md`
- `docs/octopus/device-network-contract.md`
- `docs/octopus/device-acp.md`
- `docs/octopus/deploy-other-devices.md`

## Implementation verification (2026-10-12, Coder)

Environment: LAPTOP-ATJ3N57B / Windows / branch `feature/octopus-device-network` / `octop-source`.

Commands:

```text
uv run pytest tests/unit/devices/test_api.py tests/unit/devices/test_service.py tests/unit/devices/test_join.py tests/unit/devices/test_client.py tests/unit/devices/test_device_cli.py -q
```

Result: **59 passed** (AE-01/AE-02 covered by unit/API tests for Bearer enroll + list-without-enroll; AE-06 by pair/key coexistence tests; AE-03 expand-deny already enforced in `DeviceService.update`; AE-04/05/07/08 remain manual/HTTPS field checks).

