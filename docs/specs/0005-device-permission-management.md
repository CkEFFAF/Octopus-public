# 0005 设备权限管理与便携发布（管理端可直接授权重设计）

- Spec ID: `0005-device-permission-management`
- Revision: `2026-10-12.3`
- Contract state: `ready`（设计已授权落盘；实现待 feature 分支）
- Owner: Octopus 架构师；Authoritative path: `docs/specs/0005-device-permission-management.md`
- Decision basis: 总管指派 + 用户产品预期（对标 UU：管理端可直接授予/调整权限）；拓扑=工位唯一管理端
- Delivery: full SDD（共享权限契约 + 多端）；verification=strict（信任边界）；continuity=resumable（GPT/Coder 交接）
- Relates: `0001`、`0003`（迁云/入口稳定精神）、`0004-same-account-auto-enroll.md`、`device-network-contract.md`、`device-acp.md`、`desktop/portable/*`、`.github/workflows/octop-desktop.yml`
- Non-overwrite: 不修改 Accepted `0004-same-account-auto-enroll.md` 正文；本规格修订其「扩大须重登记」MVP 与「几乎无权限」默认表述（默认权限集以本规格 REQ-007 为准）

## Goal and boundaries

**Goal:** 同账号所有者在管理端 Dashboard 可直接查看并授予/调整设备权限与共享目录（查看桌面、桌面输入、读/写文件、执行命令、本机 ACP 等），不再停留在「只能缩减 + 此设备不支持点不动」。新建设备默认已具备桌面查看/输入与读文件授权；写文件、命令、ACP 由管理端后续勾选。同里程碑提供 Win GitHub Release 开箱便携包（Linux 全量可延后），用户无需自配 uv/Node。稳定公网入口优先采用 Cloudflare Tunnel + 自定义域名（HTTPS），执行端只配域名与账号，不依赖内网 IP 或长期 `--allow-insecure`。

- **In scope:** 权限数据模型与信任边界；默认 permissions 集合；管理端下发 vs 设备端生效；roots 选择/请求；旧设备迁移；API/WS/UI 契约；Coder 实现指南；便携 Release 产物与验收；**稳定入口（Cloudflare Tunnel + 公网域名 HTTPS）**及迁云时仅改 Tunnel 指向。
- **Non-goals:** 跨管理端同步；自研 NAT/P2P 穿透；强制用户自签证书（Tunnel 终止 HTTPS）；把 Cloudflare 账号/API Token 细节写入产品密钥库；云中继（产品内建）；手机原生执行端；取消 `odv_`；Wails 壳替代绿包验收；源码开发机环境文档化；任意路径自动 `mkdir`；全自动 Tunnel 安装器（本里程碑文档+配置步骤即可）。
- **Constraints:** 单管理端（Win 工位 24h）；设备=笔记本 + Ubuntu GPU；正式路径为公网域名 HTTPS（Tunnel）；`capabilities` 仍为硬件/客户端上限；Agent 不得自增设备权限；`command_exec`/`acp_run` 即使 `owner_auto` 仍强制设备 confirm；迁云时执行端 `--server` 域名与账号不变（对齐 0003）。

## Requirements and acceptance

### REQ-001 — 管理端可授予与调整权限（不再只能缩减）

- Source: 用户产品预期 / 总管指派
- Requirement: 设备 `owner_user_id` 对应当前账号时，管理端可将 `permissions` 设置为任意 ⊆ 该设备当前 `capabilities` 的子集（可增可减）；成功后设备端在约定信任模式下生效，`grant_version` +1。授予 `command_exec` 或 `acp_run` 时无论 `remote_grant_mode` 为何，均须走设备端 confirm（见 DEC-005 / 原 OQ-005）。
- AC-001: Given 设备在线且 `capabilities` 含 `desktop_view`，When 管理端授予 `desktop_view`（若尚未具备），Then 设备页不再显示该能力为不可用，且 `desktop.capture` 可按既有协议成功（`owner_auto` 下自动生效；若仅此增权且模式为 confirm 则确认后成功）。
- AC-002: Given 管理端请求的 permission ∉ `capabilities`，When 提交，Then API 拒绝且 UI 说明「设备不支持」，不得静默写入。
- AC-003: Given 非 owner 账号，When PATCH 权限，Then FORBIDDEN。
- Verification: API 集成测试 + Dashboard 手测录屏/清单；对照 `protocol.py` 动作映射。

### REQ-002 — 信任边界：远程扩权模式可配置

- Source: 安全约束 + UU 体验张力
- Requirement: 每台设备具备 `remote_grant_mode`：`confirm` | `owner_auto`（**MVP 默认 `owner_auto`**，见 DEC-001）。模式写入设备策略（服务端 + 设备本地可见）。`owner_auto` 适用于除 `command_exec`/`acp_run` 外的增权；这两项**强制 confirm**（DEC-005）。
- AC-004: `confirm` 下扩权：管理端提交 desired grants → 设备弹确认（GUI）或 CLI 提示 → 同意后生效；拒绝则保持旧 grants，管理端可见 pending/rejected。
- AC-005: `owner_auto` 下：对 `desktop_*` / `files_read` / `files_write` 的增权，设备在线时自动应用；离线则标记 `pending_grant`，上线后应用或超时失败（DEC-002）。对 `command_exec`/`acp_run` 的增权仍须设备 confirm，不得自动落地。
- AC-006: 缩减权限在两种模式下均可由管理端立即生效（延续「可减」）。
- Verification: `owner_auto` 授 `files_write` 自动生效一条；授 `command_exec` 必须确认一条；恶意/错账号扩权为负例。

### REQ-003 — 共享目录可由管理端请求或选择

- Source: 用户要管理端配目录，非仅重配对
- Requirement: 设备定期或按需上报 `root_candidates`（本机建议/已允许浏览的根，可为空）。管理端可：(a) 从候选中启用 read/write；(b) 请求新路径字符串。新路径必须经设备同意（`confirm`）；**禁止**管理端下发任意路径并在设备上自动 `mkdir`（DEC-003 / 原 OQ-002）。仅候选根或已授权父路径下的路径可在 `owner_auto` 下自动启用（仍不得 mkdir 新目录树）。
- AC-007: 从候选启用可写 root 后，`files_write` 可用且文件往返成功。
- AC-008: 请求设备上不存在的路径 → 明确失败；**不得**自动创建该路径或任意系统目录。
- Verification: 笔记本与 GPU 各一共享根；管理端操作，设备侧落盘；负例：不存在路径拒绝且无 mkdir。

### REQ-004 — 与 enroll / device-state / Dashboard 数据流一致

- Requirement: 登记（含 0004 账号自动登记）按 **REQ-007 默认 permissions** 入网（不再以「几乎无权限」为本规格落地默认）；事后权限走本规格通道，不强制撤销重登记。`device-state` 保存本地 policy 与 `remote_grant_mode`；WS `grants` / `grant_proposal` 携带 `grant_version`。聊天/看板派工仍绑定 `device_id`+`grant_version`；专家 `device_binding` 语义不变。
- AC-009: 新登记设备在 capabilities 支持时，登记后即具备默认桌面查看/输入与 `files_read`（见 REQ-007）；若尚无可读 root，文件列表为空，管理端可通过候选根启用后再列目录——**无需**为默认三项再走一次「仅授 files_read」的重登记。
- AC-010: 换权后旧 `grant_version` 的派工快照失效（延续 0001 AC-04）。
- Verification: 合同测试 + 一则派工用例 + 登记后默认可 capture（capabilities 允许时）。

### REQ-005 — 旧「只能缩减」设备迁移

- Requirement: 旧客户端不识别远程授杈时，管理端 UI 显示「需升级客户端」并保留缩减+重登记路径（**双轨过渡**，见 DEC-004）。新客户端首次连接可提示选择 `remote_grant_mode`（默认 `owner_auto`，DEC-001）。
- AC-011: 旧客户端收到扩权提案 → 忽略或报 unsupported；管理端不伪称已授权。
- AC-012: 升级后一次 migrate 成功，无需删除 `device-state`（除非 token 失效）。
- Verification: 版本门禁字段（如 `client_protocol_version`）+ 兼容矩阵。

### REQ-006 — 便携 GitHub Release 开箱包（同里程碑）

- Source: 总管补充需求
- Requirement: `v*` tag 触发的 GitHub Release **必须**提供 Windows 开箱 zip：解压即可跑管理端与设备端入口，**不要求**用户安装 uv/Node/系统 Python。Linux amd64 全量管理端包**本里程碑不硬门禁**，可延后（DEC-006）；若仅有 device-only Linux 包须在 Release 说明标注。
- AC-013: Release 资产至少含 `Octop-portable-windows-amd64-<ver>.zip`；内含 `open.bat`/`start.bat` 与 `start-device.bat`/`setup-device.bat`。
- AC-014: Linux amd64 全量包（`Octop-portable-linux-amd64-*.zip`）为**非硬门禁 / 可延后**目标；本里程碑以 Win 全量包 +（可选）Linux 设备包即可称 MVP 发布完成，须在 Release 说明写明 Linux 全量状态。
- AC-015: 解压后 `open.bat|sh --home <dir>` 可起管理端；`start-device` 可连；数据在 `--home`/`data/`/`OCTOP_HOME` 约定下可升级保留。
- AC-016: 校验：Release 附 SHA256；包内 `verify`/启动自检失败有明确错误（沿用/补齐现有 verify_imports）。
- Verification: 干净 Win 机一次开箱（无预装 uv/Node）；Linux 全量开箱不阻塞本里程碑关闭。

### REQ-007 — 新建设备默认权限集合

- Source: 用户 2026-10-12 产品决议（覆盖本规格初稿 / 0004「几乎无权限」在本通道的落地默认）
- Requirement: 设备**新建或账号登记成功**写入的初始 `permissions`（在对应项 ∈ `capabilities` 时）必须包含：`desktop_view`、`desktop_control`、`files_read`。初始**不得**包含：`files_write`、`command_exec`、`acp_run`（这三项仅能由管理端后续授予，且后两项强制 confirm）。若某默认项 ∉ `capabilities`（如无头 Linux 无桌面），则跳过该项并在设备/管理端标明不支持，不得伪造授权。
- **无 root 时的读文件策略：** `files_read` 可已授，但若 `roots` 为空，则文件列表为空、读写 API 无根可用；管理端须能拉取 `root_candidates` 并启用可读根后，列表才有内容。登记未选 `--share` 不等于撤销 `files_read`。
- AC-017: Given 新登记 Windows 设备且 capabilities 含桌面与文件读，When 登记完成且未再 PATCH，Then `permissions` 含 `desktop_view`/`desktop_control`/`files_read`，不含 `files_write`/`command_exec`/`acp_run`；`desktop.capture` 与（在授权后）`desktop.input` 可用。
- AC-018: Given 新登记设备无共享根，When 管理端打开文件区，Then 列表空或提示无根；When 从候选启用可读 root，Then `files.list` 成功——全程无需重登记。
- AC-019: Given `owner_auto`，When 管理端授予 `files_write` 并选定可写 root，Then 设备自动生效且文件上传成功；When 授予 `command_exec` 或 `acp_run`，Then 保持 pending 直至设备 confirm。
- Verification: 登记后权限快照断言；桌面/读文件/写文件/命令四条路径。


### REQ-008 — 稳定入口：Cloudflare Tunnel + 公网域名 HTTPS

- Source: 用户确认（稳定入口 = CF Tunnel + 自定义域名）；对齐 0003 迁云精神
- Requirement: 管理端（工位控制中心）经 **Cloudflare Tunnel** 暴露**公网域名** HTTPS 入口（稳定 URL）。执行端开箱/登记**只配置**：`--server https://<公网域名>`（或等价配置项）+ **账号密码/登录密钥**；**不要求**用户记忆或填写内网 IP，**不要求**用户长期使用 `--allow-insecure`。Tunnel 终止到本机控制中心，须覆盖 HTTP `/api/` 与设备 WebSocket `/api/devices/connect/ws`（及同类设备连接路径）。**迁云**：换机器或上云时，仅改 Tunnel 指向新源站；执行端已配置的域名与账号**不变**。便携包 README / deploy 文档 / 默认示例一律使用公网域名示例（如 `https://octop.example.com`），**不以** `http://192.168.x.x` 为正式路径示例。
- AC-020: Given Tunnel 已指向本机控制中心且域名证书由 Cloudflare 提供，When 执行端以 `--server https://<公网域名>` + 有效账号完成登记或重连，Then 登记/WS 握手成功，且全程无需 `--allow-insecure`、无需内网 IP。
- AC-021: Given 已登记设备使用域名入口，When 管理端迁到新机器且仅更新 Tunnel 源站指向，Then 执行端不改 `--server` 与账号即可重连成功（对齐 0003）。
- AC-022: Given 便携包或 deploy 文档，When 用户按开箱 README 配置执行端，Then 示例与步骤以 `https://<公网域名>` 为主路径；内网 IP / `--allow-insecure` 仅可作为局域网调试附录，不得标为正式推荐。
- AC-023: Given Tunnel 配置，When 设备经公网域名连接，Then `/api/` REST 与 `/api/devices/connect/ws`（或合同约定等价路径）均可经同一域名可达。
- Verification: 至少一条真机验收——设备用域名+账号完成登记或重连；迁云演练可文档级。本里程碑接受「文档+配置步骤」先于全自动 cloudflared 安装器。

## Interfaces（草图，非最终代码）

### HTTP

- 保留 `PATCH /devices/{id}`：允许 permissions **增减**（⊆ capabilities）；可选 `roots` 变更提案。
- 新增或扩展：
  - `GET /devices/{id}/grant-status` → `{grant_version, permissions, roots, remote_grant_mode, pending_proposal?}`
  - `POST /devices/{id}/grant-proposals` → body desired `{permissions, roots[], mode_hint?}` → `proposal_id`
  - `POST /devices/{id}/grant-proposals/{proposal_id}/resolve`（设备端凭证）`{accept|reject}`
- 错误：`UNSUPPORTED_CAPABILITY`、`PENDING_CONFIRM`、`CLIENT_OUTDATED`、`ROOT_NOT_ALLOWED`、`ROOT_MKDIR_FORBIDDEN`。
- Enroll / 自动登记响应中的初始 `permissions` 必须符合 REQ-007。

### WS（设备）

- 服务端 → 设备：`grant_proposal` / `grants`（含 version）
- 设备 → 服务端：`grant_resolve`、`root_candidates`、`hello` 报 `client_protocol_version` 与 `remote_grant_mode`
- 生效规则：最终有效权限 = 按模式应用后的 grants，且不得超过本地 `capabilities`（硬件探测上限）。**废除**「远端 grants 只能与本地 consent 求交以致永远无法扩权」的旧语义；改为「capabilities 为上限，grants 为当前授权」。本地用户仍可通过设备端 UI 拒绝或调低。高危能力提案必须走 confirm 通道。

### Dashboard

- 去掉/改写 `reduceHint`「只能缩减…重新配对」为主路径文案。
- 权限开关：支持的能力可点；不支持的显示「此设备不支持」且禁用；默认三项登记后显示已授予。
- Pending 确认态可见（尤其 command/ACP）。

## 便携发布一节（产物形态）

| 资产 | 说明 |
|---|---|
| `Octop-portable-windows-amd64-<ver>.zip` | **本里程碑必出**；管理+设备入口；解压即用 |
| `Octop-portable-linux-amd64-<ver>.zip` | **可延后**；若仅有 device-only 包须标注 |
| 校验 | SHA256SUMS；可选 sig |

**目录布局（包内）：** runtime/、launch 入口、`open`/`start`/`start-device`/`setup-device`、说明 README。  
**数据：** 包旁 `data/` 或 `--home` / `OCTOP_HOME`（默认 `~/.octop`）。升级保留 home 与各端 `device-state`。  
**与现脚本差距：** `package.sh`+`octop-desktop.yml` 已能打多平台 zip 并挂 Release；本里程碑硬门禁为 Win 全量；Linux 全量不阻塞；禁止验收路径要求用户 `uv sync`/`npm ci`。
**稳定入口示例：** 包内 README / `setup-device` 说明默认示例为 `--server https://<你的域名>` + 账号；附「Cloudflare Tunnel 指向本机控制中心」配置步骤链接或短节；禁止把 `http://192.168.x.x` 写成唯一开箱路径。


## 稳定入口 / Cloudflare Tunnel

**决议（DEC-008）：** 正式稳定入口 = **Cloudflare Tunnel + 自定义域名**（用户确认）。产品不自研 NAT 穿透；不强制用户自签证书（由 Tunnel/Cloudflare 提供公网 HTTPS）；Cloudflare 账号与 API Token **不**进入产品密钥库，仅作宿主机运维配置。

### 拓扑

```
执行端 --HTTPS--> https://<公网域名>  --CF Tunnel-->  工位本机控制中心
                                      （终止 /api/ 与 /api/devices/connect/ws）
```

- 管理端 24h 跑在工位；`cloudflared`（或等价）将公网域名流量转到 `localhost` 控制中心端口。
- 执行端开箱只配：`--server https://<公网域名>` + 账号密码/登录密钥。
- **迁云：** 换机器或上云时，只改 Tunnel 源站指向新控制中心；执行端域名与账号不变（对齐 0003）。

### 本里程碑交付边界

| 项 | MVP |
|---|---|
| 文档 + 手工配置 Tunnel 步骤 | **必须**（deploy + 开箱 README） |
| 设备用域名+账号登记/重连验收 | **必须**至少一条 |
| 全自动 cloudflared 安装器 / 旁路脚本 | **非必须**（可选后置） |
| 内网 IP + `--allow-insecure` | 仅调试附录，非正式路径 |

## Decisions / assumptions / open questions

| ID | 内容 | State | Affected | Blocking? |
|---|---|---|---|---|
| DEC-001 | MVP 默认 `remote_grant_mode=owner_auto`（个人自托管、同账号）；安装/设置可改 `confirm` | **resolved**（= owner_auto） | REQ-002 | 否 |
| DEC-002 | 离线 pending grant 保留 72h，超时自动取消 | assumed | REQ-002 | 否 |
| DEC-003 | **禁止**任意路径自动 `mkdir`；新绝对路径须设备同意；仅候选根或已授权父路径下可 `owner_auto` 启用已存在路径 | **resolved** | REQ-003 | 否 |
| DEC-004 | 旧设备 **双轨过渡**：旧客户端保留只能缩减+重登记；新客户端走本规格；建议双轨 ≤1 个小版本 | **resolved**（原 OQ-004） | REQ-005 | 否 |
| DEC-005 | `command_exec` / `acp_run` **强制 confirm**（即使 `remote_grant_mode=owner_auto`） | **resolved**（原 OQ-005） | REQ-002、REQ-007 | 否 |
| DEC-006 | Win Release 必出；Linux 全量包本里程碑**不硬门禁**、可延后 | **resolved**（原 OQ-003） | REQ-006 | 否 |
| DEC-007 | 新建设备默认 permissions = `{desktop_view, desktop_control, files_read}`（∩ capabilities）；不含 write/command/acp | **resolved** | REQ-007 | 否 |
| DEC-008 | **稳定入口 = Cloudflare Tunnel + 自定义域名**（公网 HTTPS）；执行端只配域名+账号；迁云只改 Tunnel 指向 | **resolved**（用户确认） | REQ-008 | 否 |
| OQ-001 | （已关）默认 `owner_auto` | **resolved** → DEC-001 | REQ-002 | 否 |
| OQ-002 | （已关）禁止任意路径自动 mkdir | **resolved** → DEC-003 | REQ-003 | 否 |
| OQ-003 | （已关）Linux 全量可延后 | **resolved** → DEC-006 | REQ-006 | 否 |
| OQ-004 | （已关）旧设备双轨过渡 | **resolved** → DEC-004 | REQ-005 | 否 |
| OQ-005 | （已关）command/acp 强制 confirm | **resolved** → DEC-005 | REQ-002 | 否 |

## 风险

- 恶意/被盗管理端会话 + `owner_auto` → 远程扩权至写文件：缓解=短 JWT、撤销设备、**命令/ACP 强制 confirm**、HTTPS、审计日志。
- 默认授予桌面输入：物理键盘鼠标可被远程注入——依赖同账号信任与 HTTPS；用户可缩减 `desktop_control`。
- 局域网假管理端：设备只连已登记 server URL；证书校验；禁 `--allow-insecure` 验收。
- Tunnel 误配/过期导致全网设备断连：缓解=文档化健康检查；迁云前先验证新源站再切 DNS/Tunnel；保留短时局域网调试附录。
- Cloudflare 账号泄露不等于产品密钥泄露：产品密钥库**不得**存 CF API Token；Tunnel 凭证仅宿主机运维配置。
- 权限 UI 与真实 capabilities 不一致 → 「点了无效」：以设备上报 capabilities 为唯一上限源。

## MVP 切片（推荐）

1. API+WS：允许 PATCH 扩权 + `grant_proposal`/`resolve`；默认 `owner_auto`；**登记写入 REQ-007 默认 permissions**；`command_exec`/`acp_run` 强制 confirm。
2. Dashboard：可点授权；pending 态；改文案；默认三项显示已授予。
3. 设备端：应用提案；上报 capabilities/root_candidates；高危能力强制 confirm；禁任意 mkdir。
4. 迁移：协议版本门禁；旧客户端双轨提示升级。
5. Release：**Win 全量 zip 必挂** GitHub Release；Linux 全量可延后并在说明标注。
6. 文档：更新 contract + deploy；0004 增加「扩权与默认权限改走 0005」交叉引用（短补丁，不改 Accepted 正文大段）。
7. **稳定入口（REQ-008）：** 本里程碑以「文档 + Tunnel 配置步骤」为主；验收至少一条——设备用公网域名 + 账号完成登记/重连；全自动 cloudflared 安装器非必须；可选旁路脚本可后置。

## 给 Coder 的实现指南（模块级，不写大段代码）

| 区域 | 改动要点 |
|---|---|
| `infra/devices/service.py` | 去掉「permissions 只能 ⊆ 旧 permissions」；改为 ⊆ capabilities；写 proposal/apply；bump `grant_version`；**enroll 初始 permissions=REQ-007**；command/acp 提案强制 confirm 流程 |
| `infra/devices/executor.py` / client | 废除「远端∩本地导致无法扩权」；capabilities=上限；处理 `grant_proposal`；root_candidates；**禁止 mkdir 任意路径** |
| `api/routers/devices.py` | PATCH 语义；proposal API；错误码；默认权限序列化 |
| `protocol.py` | 新消息类型与版本字段；高危 confirm 标志 |
| Dashboard 设备页 | 开关可点；文案；pending；默认三项已授态 |
| locales zh/en | 替换 reduceHint |
| `desktop/portable` + `octop-desktop.yml` | Win Release 资产与 README 开箱步骤为硬门禁；Linux 按 DEC-006；**README/`--server` 默认示例改为公网域名**，非 `192.168.x.x` |
| deploy 文档 / 开箱 README | 增加 Cloudflare Tunnel 指向本机控制中心（含 `/api/` 与设备 WS）步骤；迁云「只改 Tunnel」说明；可选 `cloudflared` 旁路脚本**非必须 MVP** |
| 测试 | 默认权限快照；扩权/拒权；files_write 自动；command/acp confirm；无 root 空列表；旧客户端；离线 pending |
| 分支 | feature 分支；提交信息按团队标准，便于 GPT 交接 |

**明确不做（Coder）：** 大范围重构 Bridge；改 `device_binding` 语义；在本规格外重做 0004 登记流；实现任意路径自动 mkdir；自研 NAT 穿透；强制自签证书流程；把 Cloudflare 账号写入产品密钥库；本里程碑不做全自动 Tunnel 安装器。

## Implementation and evidence links

| REQ/AC | Task | Impl ref | Check | State |
|---|---|---|---|---|
| REQ-001…005、REQ-007 | feature/octopus-device-permissions | service/executor/client/API/Dashboard | 单测 test_grants_0005 + devices 套件 | implemented (pending review) |
| REQ-006 | Release 流水线验收（Win 硬门禁） | `octop-desktop.yml` | 干净 Win 开箱 | unimplemented |
| REQ-008 | Tunnel+域名文档与开箱示例 | docs/octopus/cloudflare-tunnel-entry.md + portable README | 占位域名示例；手工 Tunnel | documented (pending review) |

## Evolution

- 2026-10-12.1: 初稿 ready；修订 0001/合同「只能减」主路径；0004 扩权从「重登记」升级为本规格通道。
- 2026-10-12.2: 默认 permissions=`desktop_view`+`desktop_control`+`files_read`（写/命令/ACP 默认关）；关闭 OQ-001…005 为 resolved（owner_auto、禁 mkdir、Win 必出/Linux 可延后、旧设备双轨、command/acp 强制 confirm）；增补 REQ-007 与 AC-017…019；修订 REQ-002/004/006 与 DEC 表。
- 2026-10-12.3: 追加「稳定入口 / Cloudflare Tunnel」；新增 REQ-008（AC-020…023）与 DEC-008（resolved=CF Tunnel+自定义域名）；Non-goals 明确不自研穿透/不强制自签/不把 CF 账号写入产品密钥库；MVP 接受文档+配置先于安装器；Coder/便携 README 默认示例改域名。
- Completion: 实现与验证分离；未跑通 AC 前不得称 Verified。
- 2026-10-12 Coder: feature/octopus-device-permissions 落地权限主路径 + Tunnel 文档/占位示例（revision .3）。
