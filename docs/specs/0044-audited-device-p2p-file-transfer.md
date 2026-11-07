# 0044 云端管理和审计的设备 P2P 文件渠道（G4）

- Revision: **2026-11-07.1**（Asia/Shanghai）｜Contract: **Ready**
- Owner: Octopus 架构师 → 总管派 Coder｜权威源：本文件
- Decision basis: 用户授权开发；交接 `docs/handoffs/2026-11-07-grok/`（04-audited-p2p-transfer + design-report + README）；用户已确认「须云端授权与审计、不可偷偷直传」；Codex 负责传输 UI / 渠道展示 / 预览卡片消费，本规格只冻结**后端/协议 + 设备端协商契约**
- Code baseline: `CkEFFAF/Octopus-public` **`origin/main` @ `99719e2de0e086cd49e86f94640a27cd98858b2b`**（`99719e2 docs(handoff): Codex UI after G1/G2 @ ca771fd`；本轮已 `git fetch` 核对）
- Delivery: **compact SDD**（build-adaptively）｜Verification: **strict**（审计完整性 / 无绕过云端 / Hub≠P2P）｜Continuity: collaborative（GPT 交接）
- 编号说明：tip 已有 `0040`–`0043`；本规格取 **0044**（G4）
- 依赖：复用 tip 既有 `DeviceService` / 设备 WS / `files.*` 原子写 / `device_operations`；**不**功能依赖 0043（可并行）。与 U1 资源预览：传输完成后目标侧可走既有 resource/preview API，本规格不做 UI
- 约束：**只写 docs/specs**；不改产品代码、不改 `dashboard/`、不碰 `octopus1/chat-task-work`；不 commit / push / PR / 部署；不派 Coder；不替换 Harness；不做全量重构 PR；0039 Mac **搁置勿动**；密钥 / enrollment token / 传输票据明文不进日志与测试快照

---

## 0. 给 Coder / GPT / Codex 的阅读顺序

1. §1 Goal / Non-goals / 模块边界  
2. §2 复用映射（tip 现状 → 缺口）  
3. §3 DEC（已拍板）  
4. §4 Codex + 设备契约（HTTP / WS / 票据 JSON）  
5. §5 REQ / AC  
6. §6 迁移 / 错误码 / 授权 / 取消与回退  
7. §7 Coder 实现指南与测试（含真实双机证据）  
8. §8 与 0041 / 0043 / G5 / 0001 关系  

---

## 1. Goal / Non-goals / 模块边界

### Goal

为**同一账号下的已注册设备**增加**云端授权与审计的文件传输渠道**：当设备在内网可达时，可在短期票据约束下做 **TLS 文件直连（P2P 数据面）**；不可直连时**回退 Hub 中继**。所有传输必须先经云端校验与记账，再下发协商；**禁止**设备间绕过云端偷偷传文件。首版验收对象 = **文件传输**（含中文路径二进制、校验、流式、取消/回退），不是远程桌面视频或 P2P MCP。

### In scope（S0 = LAN-direct + Hub-fallback 端到端）

- 在现有 `POST /api/devices/transfers` 上扩展（旧客户端兼容）：创建经授权的 transfer 会话，签发短期、一次用途、绑定双方身份 + 文件摘要的传输票据
- 经已认证设备 WS 下发协商；执行端**不信任**消息里自报的 peer 名，只信任票据与云端已绑定的 device_id
- 可达时：两端验证票据后建 **TLS 文件直连**；载荷**不**经 Hub、**不**进模型上下文
- 不可达 / 两端无入站：同一 `transfer_id` 回退 **Hub**（复用/演进现有 `_transfer` 分块路径）；保留尝试记录与 `fallback_reason`；**禁止**把 Hub 中转标成 P2P / direct 成功
- 目标写临时文件 → 校验 size/sha256 → 原子提交；默认不覆盖已有文件
- 双方经原设备连接上报回执；云端核对后 `completed`；日志不完整 → `pending_receipt` / `unknown`，不可宣称审计完成
- 持久化传输会话字段（见 DEC-0044-05）；路径仅对有权读该设备范围的用户可见
- 设备 capabilities / `transfer_protocol_version` 上报；状态机与进度字段供 Codex 展示
- 成对迁移 **037**（见 §6；避让 0043 的 036）；单元 + 集成 + **真实双机**证据
- OpenAPI / 交接 JSON 契约供 Codex

### Non-goals

- **不**做远程桌面 / 视频 P2P；**不**做 P2P MCP；**不**做跨用户目录共享
- **不**做 NAT 穿透 / ICE / STUN / TURN / WebRTC（另开规格记库、部署、证书、带宽、成本）；S0 **不**暗中开第三方中继
- **不**绕过云端授权「先直传再补日志」；**不**把 Hub 中转伪装成 P2P
- **不**把用户 token / Cookie / enrollment token 随文件共享或当 P2P 通行证
- **不**监听未鉴权通用文件服务端口
- **不**修改 `dashboard/`（渠道选择、进度条、失败提示、Hub 回退文案由 Codex）
- **不**实现交付物预览 UI（U1）；可引用「传输完成后 resource 可被既有 preview API 消费」
- **不**替换 Harness；**不**与 0043 / G5 混进同一次重构 PR；**不**动 0039 macOS；**不**部署云端

### 模块边界

| 层 | 职责 | 禁止 |
| --- | --- | --- |
| `api/routers/devices.py` | 薄 HTTP：创建/查询/取消 transfer；扩展响应字段 | 在路由里签发票据明文到日志；实现数据面 |
| `infra/devices/service.py` | 授权校验、会话状态机、票据签发/核销、协商下发、Hub 回退编排、回执核对 | 信任客户端自报 peer；跳过审计落库 |
| `infra/devices/transfer_session.py`（新建，建议） | transfer 会话领域模型、状态迁移、ticket 绑定校验 | SQL 散落；把 enrollment token 当 ticket |
| `infra/db/repos/device_transfers.py`（新建） | `device_file_transfers`（或 `file_transfers`）持久化 | 业务状态机 |
| `infra/devices/executor.py` + 客户端 | 验证票据、TLS 直连数据面、临时文件/原子提交、回执上报 | 未授权监听；自改 peer/hash/路径 |
| 既有 `_transfer` / `files.*` | Hub 回退数据面复用 | 回退时另造第二份冲突落盘 |
| `infra/bridge` | **Octop 实例间**隧道 | **≠** 设备 P2P；禁止复用为设备直连宣称 |

---

## 2. 复用映射（tip `99719e2`）与缺口

核对 worktree：`/workspace/octopus-g4` @ `99719e2`。

| 能力 | tip 现状 | 对 G4 的复用 | 缺口（才新增） |
| --- | --- | --- | --- |
| **`DeviceService.transfer` / `_transfer`** | `POST /devices/transfers` → `files.transfer` operation；Hub 编排 source `files.stat`/`files.read` → target `files.write_*`；base64 分块经云端；sha256 校验 | **Hub 回退路径**的权威实现基线；授权（source `files.read` + target `files.write_begin`）与 grant_version 模式 | **无** direct transport；**无** 独立 transfer 会话表；进度只在 `device_operations.result`；**无** 票据 / 协商 / 回执对账 |
| **`NativeTransfers` / `fs.upload.*` `fs.download.*`** | 执行端流式会话、临时文件、digest、存在则需 expected_sha256 | 直连数据面可借鉴原子写与校验；`transfer_protocol_version=1` 已在 hello metadata | **无** peer TLS；协议动作为 Hub/云端 call，不是设备间 |
| **设备 WS** | 设备主动连 Hub；`_connections`；派发 action/params | 协商帧、撤权、取消、进度/回执仍走此通道（控制面） | 需新增协商/回执消息类型；执行端须校验票据绑定 |
| **`infra/bridge`** | Octop↔Octop 隧道 | **不复用为设备 P2P** | 文档与 UI 文案必须区分 |
| **0001 设计** | 曾列 `file_transfers` 概念；明确「首版由控制中心中继」「无需 NAT 穿透」 | 表名/字段意图可对齐；**不能宣称 tip 已有 P2P** | 本规格正式引入直连 + 审计会话 |
| **资源 publish/stat** | 执行端 publish → 不可变 resource；`device_transfer` 工具注释建议跨设备用 publish+deliver | **下载与传输分离**：能访问 GitHub 的设备先落本地并 `files.stat` 固定 size/sha256，再开 transfer；**不**共享用户 token | S0 不强制每次经 resource；若源已是 resource，仍须在源设备落盘路径上 stat |
| **capabilities** | `files_read` / `files_write`；`transfer_protocol_version` | 扩展上报 `p2p_file_transfer`（或 bump `transfer_protocol_version`≥2）表示支持直连协商 | 旧客户端缺能力 → 仅 Hub；Codex 按真实能力展示 |

**结论**：tip **只有 Hub 中继文件传输**，没有设备 P2P。S0 须新增 **transfer 会话权威账本 + 票据 + 协商 + 直连数据面**，并保留 Hub 回退；禁止用 bridge 或假状态冒充直连。

---

## 3. DEC（拍板）

| ID | 决议 | 状态 |
| --- | --- | --- |
| **DEC-0044-01** | **分层**：云端 = **控制面**（授权、票据、审计、状态）；执行端 = **短期授权数据面**（直连或接受 Hub 转发的分块）。无云端授权意图落库 → **不得**开始新传输 | resolved |
| **DEC-0044-02** | **S0 传输选择**：优先 **LAN/已有路由可达时的 TLS 文件直连**；不能直连 → **同一 `transfer_id` 回退 Hub**。两端都无入站可达 → 首版走 Hub。禁止 S0 引入 WebRTC/ICE/TURN/第三方中继 | resolved |
| **DEC-0044-03** | **Hub 回退 ≠ P2P**：`transport` 实际值必须如实为 `direct` 或 `hub`。UI/日志/事件**禁止**在 Hub 路径宣称「直连成功」或「P2P」 | resolved |
| **DEC-0044-04** | **兼容**：扩展既有 `POST /api/devices/transfers` 与 `GET .../operations/{id}`（或新增 `GET /api/devices/transfers/{transfer_id}` 别名指向同一会话）。旧客户端不传 `preferred_transport` → 行为可默认 `auto`（先试 direct 再 hub）或 `hub`（若源/目标缺直连能力则强制 hub）；响应增加字段，旧客户端忽略未知字段 | resolved |
| **DEC-0044-05** | **持久化会话字段**（权威）：`transfer_id`、`request_id`（客户端幂等）、`owner_user_id`、`actor`（user/agent_id）、source `device_id`/`root_id`/`path` scope、target 同、`size`、`sha256`、授权与策略/grant 版本、票据到期、`actual_transport`、`status`、进度（bytes）、创建/更新时间、双方回执、连接尝试与 `fallback_reason`。路径仅对有权读该设备范围的用户可见。日志**不**保存通用设备 token / 票据明文 | resolved |
| **DEC-0044-06** | **状态枚举**（权威 `status`）：`queued` \| `negotiating` \| `transferring` \| `verifying` \| `pending_receipt` \| `completed` \| `failed` \| `cancelled` \| `unknown`。缺回执或审计不全 → 不得标 `completed` | resolved |
| **DEC-0044-07** | **票据**：短期、一次用途（或单次 transfer 绑定）、绑定 `transfer_id` + source/target device_id + size + sha256 + path scope + grant 版本 + expiry。持票者**不可**替换 peer / size/hash / 路径范围。重放、跨 owner、跨 transfer → 拒绝。不用 enrollment token 当通行证 | resolved |
| **DEC-0044-08** | **信任边界**：执行端不信任协商消息里自报的 peer 名称/地址作为授权依据；只信任云端下发且与本地 device_id/票据一致的绑定。数据载荷不进模型上下文 | resolved |
| **DEC-0044-09** | **落盘**：目标写临时文件 → 校验 size/sha256 → 原子提交。默认**不覆盖**已有文件（已存在且未提供匹配 expected → 拒绝）。Hub 回退**不**创建第二份冲突文件 | resolved |
| **DEC-0044-10** | **流程顺序**：① 请求云端创建 → 校验源读/目标写/执行模式/路径范围/覆盖策略 → ② 先记授权意图与状态再签票据 → ③ 经已认证设备连接下发协商 → ④ 验身份+票据建加密连接 → ⑤ 流式写临时+校验+提交 → ⑥ 双方回执 → 云端核对 `completed` 并向 UI 发事件 → ⑦ 失败/取消/离线/校验不符/未确认均有明确状态 | resolved |
| **DEC-0044-11** | **云端不可达 / 撤权**：云端不可达 → 不开始新传输。票据到期或权限撤销 → 停止新分块；已在飞分块尽快中止；撤权经设备连接传播；心跳/租约与失败记录写清。断线恢复为可解释状态，**不**静默删审计行 | resolved |
| **DEC-0044-12** | **渠道切换**：直连失败后**至多**在同一 `transfer_id` 内切换到 Hub 一次（或按策略有限次，但须保留每次尝试记录）；不得开平行 transfer 导致重复落盘 | resolved |
| **DEC-0044-13** | **下载与传输分离**：能访问外网的设备可先下载；开 transfer 前必须在源设备对最终字节 `stat` 固定 size/sha256。禁止把用户 GitHub token/Cookie 传给目标设备 | resolved |
| **DEC-0044-14** | **协议版本**：直连能力要求设备上报 `transfer_protocol_version >= 2`（或显式 capability `p2p_file_transfer`）。S0 选一实现并在 OpenAPI/交接写死；缺能力 → 仅 Hub，且 `actual_transport=hub` | resolved |
| **DEC-0044-15** | **迁移编号**：成对 **`037_device_file_transfers.sql` + `037_device_file_transfers.pg.sql`**。tip 最高迁移 **035**；0043 已提案 **036**（work_items）。若合并时 036/037 被占用 → **待总管确认编号**，禁止改已上线迁移、禁止擅自跳号撞车 | resolved |
| **DEC-0044-16** | **事件**：向 owner 通知通道推送 `transfer.changed`（`schema_version=1`），经既有 `push_to_user`；载荷仅不透明 id + status + transport + 进度摘要 + 时间，**无**路径明文给无权限端、无票据。可选复用 0041 风格 helper，但不改 `thread.changed` schema | resolved |
| **DEC-0044-17** | **验收证据**：LAN 直连通路径须有真实双机（或等价可控双执行端）证明 Hub **未**转发载荷；仅 mock 不能宣称 AC-0044-01 通过 | resolved |

---

## 4. Codex + 设备契约（冻结）

鉴权：与现网 devices API 相同（`current_user` + 设备 owner）。旧字段保留；新字段 `schema_version=1`。

### 4.1 创建传输

`POST /api/devices/transfers`（既有，202）

请求（扩展，旧字段仍必填）：

```json
{
  "request_id": "01JBCLIENTREQ...",
  "source_device_id": "opaque-source",
  "source_root_id": "opaque-root",
  "source_path": "文档/报告.bin",
  "target_device_id": "opaque-target",
  "target_root_id": "opaque-root",
  "target_path": "inbox/报告.bin",
  "preferred_transport": "auto",
  "overwrite": false,
  "schema_version": 1
}
```

| 字段 | 说明 |
| --- | --- |
| `request_id` | 可选幂等键；同一 owner+request_id 重放返回同一 `transfer_id` |
| `preferred_transport` | `auto`（默认）\| `direct` \| `hub`。`direct` 但能力不足/不可达 → 按策略失败或回退（见 DEC；S0 建议 `auto` 可回退，显式 `direct` 不可达 → 409/失败且不静默改口） |
| `overwrite` | 默认 `false` |

**响应 202**（示例）：

```json
{
  "transfer_id": "01JBXFER...",
  "operation_id": "01JBOP...",
  "status": "negotiating",
  "preferred_transport": "auto",
  "actual_transport": null,
  "bytes_total": 204800,
  "bytes_done": 0,
  "source_device_id": "opaque-source",
  "target_device_id": "opaque-target",
  "sha256": "ab12...64hex",
  "fallback_reason": null,
  "audit_id": "01JBAUDIT...",
  "capabilities": {
    "source": {"transfer_protocol_version": 2, "p2p_file_transfer": true},
    "target": {"transfer_protocol_version": 2, "p2p_file_transfer": true}
  },
  "schema_version": 1
}
```

说明：`bytes_total`/`sha256` 可在源 `stat` 完成后填充；创建瞬间可为 null，随后经 `transfer.changed` / GET 更新。`operation_id` 可与既有 operations 查询兼容（一对一或 transfer 为父会话）。

### 4.2 查询

`GET /api/devices/transfers/{transfer_id}`

```json
{
  "transfer_id": "01JBXFER...",
  "status": "transferring",
  "actual_transport": "direct",
  "bytes_total": 209715200,
  "bytes_done": 104857600,
  "fallback_reason": null,
  "failure_direction": null,
  "error_code": null,
  "audit_id": "01JBAUDIT...",
  "attempts": [
    {"transport": "direct", "result": "unreachable", "at": 1794028800},
    {"transport": "hub", "result": "started", "at": 1794028810}
  ],
  "receipts": {"source": true, "target": false},
  "created_at": 1794028700,
  "updated_at": 1794028810,
  "expires_at": 1794029600,
  "schema_version": 1
}
```

路径字段：仅当调用者有权读对应设备范围时返回 `source_path`/`target_path`；否则省略或脱敏。

兼容：`GET /api/devices/operations/{operation_id}` 对 `files.transfer` 须能反映同一进度/status 子集（或文档写明以 transfers API 为权威）。

### 4.3 取消

`POST /api/devices/transfers/{transfer_id}/cancel`  
（或复用 `POST /api/devices/operations/{operation_id}/cancel`，须映射到同一会话）

- 设取消意图 → 停新分块 → 目标 abort 临时文件 → 终态 `cancelled`（或短暂 `pending_receipt` 后 cancelled）
- 不得破坏目标**已有**正式文件

### 4.4 账户事件 `transfer.changed`

经 `/api/notifications/ws`（`push_to_user`）：

```json
{
  "type": "transfer.changed",
  "event_id": "01JB...",
  "transfer_id": "01JBXFER...",
  "status": "completed",
  "actual_transport": "direct",
  "bytes_total": 204800,
  "bytes_done": 204800,
  "fallback_reason": null,
  "updated_at": 1794028900,
  "schema_version": 1
}
```

**禁止**：票据、设备 token、完整本地绝对路径（无权限时）、文件正文。

### 4.5 设备 WS：协商与回执（控制面）

方向：Hub → Device（已认证连接）

**协商下发（示意）**

```json
{
  "type": "transfer.negotiate",
  "transfer_id": "01JBXFER...",
  "role": "source",
  "peer_device_id": "opaque-target",
  "ticket": "<opaque-short-lived>",
  "ticket_expires_at": 1794029600,
  "size": 204800,
  "sha256": "ab12...64hex",
  "path_scope": {"root_id": "opaque-root", "path": "文档/报告.bin"},
  "preferred_transport": "direct",
  "listen": {"mode": "lan_tls", "port_hint": null},
  "schema_version": 1
}
```

对端 `role=target` 对称。`ticket` 仅经已认证设备通道下发；执行端校验：本地 device_id、peer_device_id、size、sha256、path_scope 与票据声明一致，否则拒绝。

**回执上报 Device → Hub**

```json
{
  "type": "transfer.receipt",
  "transfer_id": "01JBXFER...",
  "device_id": "opaque-source",
  "phase": "completed",
  "bytes_done": 204800,
  "sha256": "ab12...64hex",
  "transport_used": "direct",
  "schema_version": 1
}
```

`phase`：`negotiating` \| `transferring` \| `verifying` \| `completed` \| `failed` \| `cancelled`。

**直连数据面（S0 要求）**

- 传输 TLS（证书/钉扎策略由实现选定并在交接写明：可用短期票据派生的双向认证或云端签发的一次性连接凭证；**禁止**无认证明文 TCP）
- 流式分块；内存不随整文件线性增长
- 应用层帧须再次绑定 `transfer_id` + 偏移 + 摘要进度；与票据不一致则中止

Hub 回退时：不走直连 listen；沿用/演进 `_transfer` 的 `files.read` / `files.write_*`；`transport_used=hub`。

### 4.6 Codex 展示硬规则

- 仅当 `actual_transport=direct` 且状态进入 `transferring`/`completed` 时可展示「直连 / P2P」
- `actual_transport=hub` 或仅有 hub 尝试成功 → 展示「经云端中转」，**禁止**假「直连成功」
- `pending_receipt` / `unknown` → 明示审计未完成，不显示成功绿勾冒充完成
- 渠道选项根据双方 `capabilities` / `transfer_protocol_version` 禁用不可用项

---

## 5. REQ / AC

### Requirements

| ID | 要求 |
| --- | --- |
| **REQ-0044-01** | 创建 transfer 前云端校验：源读、目标写、执行/授权模式、路径在允许 root 内、覆盖策略 |
| **REQ-0044-02** | 先持久化授权意图与会话行，再签票据、再下发协商 |
| **REQ-0044-03** | 直连与 Hub 均须绑定同一 `transfer_id` 审计；无云端会话不得传 |
| **REQ-0044-04** | 票据绑定不可变：peer、size、sha256、path scope、owner、expiry |
| **REQ-0044-05** | 目标临时文件 + 校验 + 原子提交；默认不覆盖 |
| **REQ-0044-06** | 双方回执齐全且摘要一致 → 才可 `completed`；否则 `pending_receipt`/`failed`/`unknown` |
| **REQ-0044-07** | 直连失败回退 Hub 保留 attempts 与 `fallback_reason`；无重复落盘 |
| **REQ-0044-08** | 取消/过期/撤权/重放/伪 peer/伪票/源变更/磁盘满 → 明确错误码与状态 |
| **REQ-0044-09** | 流式：≥200MB 场景内存不随文件线性涨 |
| **REQ-0044-10** | 日志与事件无设备 token、无票据明文、无跨权路径泄露 |
| **REQ-0044-11** | 下载与传输分离；不传播用户外网凭据 |
| **REQ-0044-12** | Codex 可仅凭本 §4 实现传输进度 UI（无猜后端私有字段） |

### Acceptance

| ID | Given / When / Then |
| --- | --- |
| **AC-0044-01** | 两台 LAN 设备传含中文路径二进制；源/目标 sha256 一致；审计显示 `actual_transport=direct`；Hub **不**转发载荷（双机证据） |
| **AC-0044-02** | 接收端不能访问 GitHub，另一端可下载；交付成功 + 云端完整会话/回执记录 |
| **AC-0044-03** | 直连不可达 → 自动或明确策略下回退 Hub；同一 `transfer_id` 可追踪；目标无重复文件 |
| **AC-0044-04** | 纯 NAT 无穿透 → UI/API 明确 Hub 回退，不把中转称 P2P |
| **AC-0044-05** | 200MB 流式；进程内存不随整文件线性涨；取消/重试不破坏目标已有正式文件 |
| **AC-0044-06** | 伪 peer、伪票据、过期、重放、撤权、源变更、目标磁盘满均有回归（拒绝或 failed，审计保留） |
| **AC-0044-07** | 云端中断/设备断线后状态可解释恢复；不静默删除审计行；缺回执不得假 completed |

---

## 6. 迁移 / 错误码 / 授权 / 取消与回退

### 6.1 迁移

成对新增（建议名）：

- `src/octop/infra/db/migrations/037_device_file_transfers.sql`
- `src/octop/infra/db/migrations/037_device_file_transfers.pg.sql`

表建议名：`device_file_transfers`（对齐 0001 的 `file_transfers` 概念，加 device 前缀避免歧义）。

最低列（实现可拆 JSON 列，但下列语义必须可查）：

- 主键 / `transfer_id` UNIQUE  
- `request_id`（可空，owner 内唯一）  
- `owner_user_id`、`actor_user_id`、`agent_id`  
- source/target：`device_id`、`root_id`、`path`、`grant_version`  
- `size`、`sha256`  
- `policy_version` / 票据元数据（**哈希**可存，明文禁止落库日志）  
- `ticket_expires_at`  
- `preferred_transport`、`actual_transport`  
- `status`、`bytes_done`、`fallback_reason`、`failure_direction`、`error_code`  
- `audit_id`  
- `attempts_json`、`receipts_json`  
- `operation_id`（可选 FK/关联 `device_operations`）  
- `created_at`、`updated_at`  

索引：`(owner_user_id, created_at DESC)`、`(transfer_id)`、`(owner_user_id, request_id)`。

**编号风险**：0043 占用 **036** 提案；本规格 **037**。若并行合入撞车 → 停写迁移，报总管确认，**不**改历史迁移。

### 6.2 错误码（建议）

| code | HTTP | 语义 |
| --- | --- | --- |
| `TRANSFER_UNAUTHORIZED` | 403 | 源/目标授权失败 |
| `TRANSFER_PATH_DENIED` | 403 | 路径越界 |
| `TRANSFER_TARGET_EXISTS` | 409 | 目标已存在且不允许覆盖 |
| `TRANSFER_TICKET_INVALID` | 401/403 | 伪票/过期/重放/绑定不符 |
| `TRANSFER_PEER_MISMATCH` | 403 | peer 与票据不符 |
| `TRANSFER_SOURCE_CHANGED` | 409 | 源 size/hash 变更 |
| `TRANSFER_DIRECT_UNAVAILABLE` | 409 | 显式要求 direct 但不可用 |
| `TRANSFER_CAPACITY` | 429 | 并发/容量 |
| `TRANSFER_IO` | 507/500 | 磁盘满等（映射明确） |
| `TRANSFER_CANCELLED` | 409 | 已取消 |
| 既有 | | `DEVICE_OFFLINE` / `FORBIDDEN` / `USER_DISABLED` 等保持 |

### 6.3 授权

- `user.id` 必须为两设备 `owner_user_id`
- 源：`files_read`（或等价）+ root 包含 `source_path`
- 目标：`files_write` + root 包含 `target_path`
- agent 发起：沿用 tip `device_transfer` 的选中设备/绑定约束；失败带 `direction`
- 共享专家不得把用户甲设备传给用户乙

### 6.4 取消 / 回退 / 恢复

- 取消：停发新分块；abort 临时文件；保留审计；正式文件未提交则不出现半文件冒充成功
- 回退：同一 transfer；写 `fallback_reason`（如 `direct_unreachable` / `no_inbound` / `capability_missing`）
- 恢复：重启后读会话行 + 设备回执；能确认则恢复状态；不能 → `unknown`/`pending_receipt`；**禁止**自动重放整文件副作用而不经核对

---

## 7. Coder 实现指南

### 分支

- 建议：`feature/0044-audited-device-p2p-file-transfer`
- 基线：**最新** `origin/main`（至少含本规格所记 `99719e2`；开写前再 `git fetch`）
- **禁止**在 `D:\Agent_Workspace\octopus1\chat-task-work` 改后端；**禁止**改 `dashboard/`；**禁止**动 0039 Mac

### 可写路径（建议）

- `src/octop/api/routers/devices.py`（扩展 TransferBody / 查询 / 取消）
- `src/octop/infra/devices/service.py`（编排；保留 `_transfer` 作 Hub）
- `src/octop/infra/devices/transfer_session.py`（新建）
- `src/octop/infra/db/repos/device_transfers.py`（新建）
- `src/octop/infra/db/migrations/037_device_file_transfers.sql` + `.pg.sql`
- `src/octop/infra/devices/executor.py` / `client.py` / `protocol.py`（协商、直连、回执、capability）
- `src/octop/infra/gateway/`（`emit_transfer_changed` 或等价）
- `src/octop/infra/errors.py` + i18n
- `src/octop/api/openapi_meta.py`
- `tests/unit/devices/test_transfer_0044.py`、`tests/integration/test_device_p2p_transfer_0044.py`
- **只读参考**：`transfers.py`（NativeTransfers）、`bridge`（仅对照「不是它」）、0029 资源路由

### 实现要点

1. **控制面先落库**：INSERT 会话 `negotiating` → 签票 → WS 下发；禁止先直连后补行。  
2. **直连**：仅当双方 online + protocol≥2 + 地址协商成功；TLS 必开。  
3. **Hub 回退**：调用演进后的 `_transfer`（或共享分块例程）；`actual_transport=hub`。  
4. **进度**：更新会话 `bytes_done` + 可选 operation.result；推送可合并（≥1s）但终态不可丢。  
5. **安全**：票据单次/短 TTL；核销；重放拒绝；撤权打断。  
6. **密钥**：测试与日志用红片/哈希，禁止原文。

### 测试命令

```bash
uv run pytest tests/unit/devices/test_transfer_0044.py tests/integration/test_device_p2p_transfer_0044.py -q
# 须含：伪票/重放/过期/撤权/目标已存在/源变更
# AC-0044-01/02/05：真实双机或双 Native executor 夹具 + 断言 Hub 侧无 payload 转发
make all   # 须绿；CI Linux + Windows
```

### 交付物（Coder → Codex / 总管）

- §4 JSON 冻结示例 + OpenAPI 摘要  
- 实际测试命令与结果；**双机直连证据**（时间、两 device_id、hash、transport=direct、Hub 无载荷证明）  
- 未实现项显式列出（NAT 穿透、断点续传、WebRTC、预览 UI）  
- 迁移 037 成对验证；若编号冲突已升级总管  

---

## 8. 与其它规格

| 规格 | 关系 |
| --- | --- |
| **0001** | 曾排除 NAT、首版 Hub 中继；本规格在**不开放 NAT 穿透**前提下增加**可选 LAN 直连**；审计表落地 0001 的 `file_transfers` 意图 |
| **0041 G1** | 可复用 `push_to_user` 模式发 `transfer.changed`；不改 `thread.changed` |
| **0043 G3** | 无硬依赖；可并行。工作项若触发跨设备交付，应调用本 API，不自建旁路 |
| **0029 / 资源** | 传输完成后预览走既有 resource API；本规格不实现 U1 卡片 |
| **G5 ACP/token** | 启用 ACP **不**自动获得 P2P 或全盘文件权；本 PR 不实现 G5 |
| **bridge** | 实例间隧道 ≠ 设备 P2P |
| **0039 macOS** | **搁置**；勿派 |

### Evolution（非 S0）

- WebRTC/ICE/TURN（须单独规格：依赖、TURN 成本、证书、带宽）  
- 断点续传 / 并行多分片  
- 跨用户受控共享目录  
- 与 U1 深度集成的传输进度卡片（Codex）  

### 风险

| 风险 | 缓解 |
| --- | --- |
| 假直连状态 | DEC-0044-03；Codex 硬规则；AC-0044-04 |
| 绕过云端偷传 | DEC-0044-01/08；无票拒连；AC-0044-06 |
| 迁移号与 0043 冲突 | DEC-0044-15；开写前再 fetch |
| Hub 回退重复落盘 | DEC-0044-09/12；同一 transfer_id |
| 审计不全却显示成功 | DEC-0044-06；`pending_receipt` |
| 内存涨爆 | REQ-0044-09；流式 AC-0044-05 |

---

## 9. Ready 检查

- [x] 第二实现者无需猜测可实现观察行为（HTTP + WS + 票据语义已冻）  
- [x] 明确「无云端授权不得传」与「Hub 回退 ≠ P2P」  
- [x] 复用映射已写；确认 tip 无现成 P2P  
- [x] 失败 / 取消 / 撤权 / 回退 / 缺回执已写  
- [x] 迁移 037 避让 0043 的 036；冲突升级总管  
- [x] 0039 Mac 未触及  
- [x] **可立刻派 Coder**（建议分支 `feature/0044-audited-device-p2p-file-transfer`；基线 `99719e2`+）  

**Contract: Ready · Rev 2026-11-07.1**
