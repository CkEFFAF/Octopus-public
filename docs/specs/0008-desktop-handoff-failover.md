# 0008 设备间桌面交接与故障转移（MVP）

- Spec ID: `0008-desktop-handoff-failover`
- Status: **Implementing / MVP-S1**（OQ 已全部关闭；实现尚未开始；先 S1 桌面目标切换）
- Revision: `2026-10-12.2`
- Date: 2026-10-12
- Authoritative path: `docs/specs/0008-desktop-handoff-failover.md`
- Relates:
  - `0005-device-permission-management.md`（`desktop_view` / `desktop_input`、远程扩权 confirm）
  - `docs/octopus/device-acp.md`（专家 `device_binding`；本规格 **不**自动改绑定）
  - `0003-workstation-migration.md`（迁云/入口稳定精神；本规格不做全量迁站）
  - `0004-same-account-auto-enroll.md`（Accepted；设备身份/enroll 不变）
  - `0006-device-first-run-launcher.md`、`0007-portable-release-packages.md`（设备已在网为前提）
- Non-overwrite: **不修改** Accepted `0004` 正文；不改 enroll 协议；不改 0005 权限模型语义（本规格消费已有 desktop 权限）。业务代码由 Coder 按切片实现；本任务只定规格。

## Problem

同账号下多台已登记设备（工位 / 笔记本 / 云机）时，用户需要：

1. 把「正在看/控的桌面」从一台切到另一台（交接）；
2. 管理端或原桌面源宕机时，有可预期的切主路径（故障转移）。

现状：设备网 + permissions 已能授权 `desktop_view`/`desktop_input`，专家可有 `device_binding`，但 **缺少** 明确的「桌面会话目标切换 / 接管确认 / 冷备切主」产品边界与实现切片，易与「改专家默认设备」「热迁移会话」混淆。

## Goals

1. MVP：Dashboard 可将当前桌面查看/控制 **目标** 切换到另一台已授权设备（人工确认后生效）。
2. 被控端（新目标设备）**必须弹「允许接管」**；拒绝则目标不变。
3. **不**自动改写专家 `device_binding` / 默认运行设备。
4. 故障转移先做 **冷备**（备机已在线+已授权，切主时新建桌面会话；不做热迁移内存态）。
5. 给 Coder 可交接切片与风险；不做手机原生执行端。

## Non-goals（MVP）

- 不做手机作为桌面源/被控执行端。
- 不做跨账号交接；不做 P2P/NAT 穿透新产品。
- 不做桌面会话热迁移（进程内存、未保存剪贴板、未落盘窗口布局等）。
- 不自动修改专家 `device_binding`、ACP 默认设备或聊天临时设备选择的持久默认。
- 不替代 0003 全量工位迁云；不改 Tunnel/域名默认（仍 0005/0006）。
- 本修订不写业务代码、不 git commit。

## MVP 边界（决议后）

| 维度 | MVP 做 | MVP 不做 |
|------|--------|----------|
| 触发 | Dashboard「桌面目标」切换；可选「切到冷备」入口 | 无人值守全自动抢主（无确认） |
| 状态迁移 | 新目标上 **新建** 桌面查看/输入会话；权限仍走 0005 grants | 旧会话进程态、剪贴板、未保存 UI 热迁移 |
| 确认 | **被控端弹「允许接管」**（OQ-001） | 静默接管 |
| 专家/ACP | 桌面目标与 `device_binding` **解耦**；切桌面不改绑定（OQ-002） | 切桌面时自动改专家默认设备 |
| 备机模式 | **冷备**：备机已 enroll、在线、具备所需 desktop 权限（OQ-003） | 热备镜像会话 |
| 顺序 | **先** Dashboard 桌面目标切换（S1），再冷备切主 UX（S2）（OQ-004） | 先做 manager 选举/多活 |

## Requirements and acceptance

### REQ-001 — Dashboard 桌面目标切换（S1 硬门槛）

- Requirement: 同账号所有者在 Dashboard 设备/桌面区，可将「当前桌面目标」从设备 A 切换为设备 B。B 必须：已登记、在线、`permissions` 含切换所需的 `desktop_view`（若要键鼠则还需 `desktop_input`）。切换请求发到 B 后，**B 本机弹「允许接管」**；同意后 Dashboard 桌面流改绑到 B；拒绝或超时则保持 A（或明确无目标），并提示原因。
- AC-001: Given A 为当前桌面目标且 B 在线且已授权 `desktop_view`，When 用户在 Dashboard 选择「切换到 B」且 B 上确认允许，Then 桌面画面来自 B，A 侧旧桌面会话结束或标为非当前目标。
- AC-002: Given 同上，When B 拒绝或超时，Then 桌面目标仍为 A（或切换前状态），Dashboard 可见 rejected/timeout，**无**静默成功。
- AC-003: Given B 缺少 `desktop_view`，When 请求切换，Then API/UI 拒绝并提示需先按 0005 授权，不弹无意义接管框。

### REQ-002 — 接管确认 UX（被控端）

- Requirement: 被控端确认框文案须可读：谁发起（账号/管理端）、要什么（查看 / 查看+输入）、可「允许」或「拒绝」。确认通道复用或对齐 0005 设备 confirm 能力，不得绕过设备本地同意。
- AC-004: 无 GUI 设备（纯 headless）若无法展示确认框，则 MVP 将该设备标为「不支持桌面接管」或提供 CLI 确认等价物；**禁止**无确认自动允许（与 OQ-001 一致）。
- AC-005: 允许后仅建立桌面会话；**不**隐含授予 `command_exec` / `acp_run` / 写文件。

### REQ-003 — 与 `device_binding` / ACP 解耦

- Requirement: 桌面目标切换 **不得** 自动修改专家 `device_binding`、默认运行设备或 ACP runner 绑定。专家编辑页仍是改绑定的唯一产品入口（见 `device-acp.md`）。
- AC-006: Given 专家绑定设备 X，When 用户将桌面目标切到 Y，Then 该专家绑定仍为 X；聊天里临时选设备规则不变。
- AC-007: 文档与 UI 注明：「桌面目标」≠「专家默认运行设备」。

### REQ-004 — 冷备故障转移（S2，在 S1 之后）

- Requirement: 冷备 = 预先指定或可选的一台已在线、已授权桌面权限的备机。当当前桌面源不可达（离线超时 / 用户显式「切到备机」）时，走与 REQ-001 相同的切换+「允许接管」流程，在备机上 **新建** 会话；不恢复旧机未同步状态。
- AC-008: Given 备机 B 冷备就绪，When A 离线且用户确认切到 B（或产品规定的显式切主），Then B 弹允许接管 → 同意后桌面目标为 B。
- AC-009: MVP **不**要求自动选举、不要求无用户参与的秒级切换；可先「检测不可达 → Dashboard 提示 → 用户一键切冷备」。

### REQ-005 — 审计与安全最小集

- Requirement: 切换/拒绝/超时写入可查询审计（谁、从哪到哪、结果）。仅 owner 同账号可发起。跨账号禁止。
- AC-010: 非 owner 发起 → FORBIDDEN。
- AC-011: 成功与拒绝均有服务端记录（字段足以排障，不含桌面帧内容）。

## Decisions

| ID | 决策 | State |
|----|------|-------|
| DEC-001 | 被控端 **必须**弹「允许接管」；无确认不得切换成功 | **resolved**（原 OQ-001；用户选「按建议」） |
| DEC-002 | 桌面目标切换 **不**自动改专家默认运行设备 / `device_binding` | **resolved**（原 OQ-002） |
| DEC-003 | 故障转移 **先冷备**（新建会话）；热迁移不做 | **resolved**（原 OQ-003） |
| DEC-004 | 实现顺序 **先** Dashboard 桌面目标切换（S1），再冷备切主（S2） | **resolved**（原 OQ-004） |
| DEC-005 | 桌面目标与 ACP/`device_binding` 解耦；改绑定仍走专家编辑页 | **resolved** |
| DEC-006 | MVP 不做手机执行端；不做无人值守抢主 | **resolved** |

## Open Questions（已关闭）

| ID | 问题 | 决议 | State |
|----|------|------|-------|
| OQ-001 | 被控端是否要弹「允许接管」？ | **要弹**；拒绝/超时则不切换 | **resolved** 2026-10-12 |
| OQ-002 | 切桌面时是否自动改专家默认运行设备？ | **不自动改**；与 `device_binding` 解耦 | **resolved** 2026-10-12 |
| OQ-003 | 先冷备还是先热迁移？ | **先冷备** | **resolved** 2026-10-12 |
| OQ-004 | 先做哪一切片？ | **先** Dashboard 桌面目标切换（S1），再冷备切主（S2） | **resolved** 2026-10-12 |

## Coder 实现切片

| 序 | 切片 | 产出 | 验收 |
|----|------|------|------|
| **S1** | Dashboard 桌面目标切换 + 被控端「允许接管」 | API + WS/确认框 + Dashboard 选择器；审计 | AC-001..005, AC-010..011 |
| **S2** | 冷备标记 + 「切到备机」/源不可达提示 | 冷备配置 UX + 复用 S1 切换管线 | AC-008..009 |
| **S3** | 文案/文档：桌面目标 ≠ 专家绑定 | Dashboard 提示 + `device-acp` 交叉一句 | AC-006..007 |
| **S4** |（可选）headless CLI 确认等价物 | 无 GUI 设备可确认或明确 unsupported | AC-004 |

**建议 Coder 先做 S1**（与 DEC-004 一致）。S2 依赖 S1 管线。禁止在本规格任务内改 0004 / 改 enroll。

### 可写路径（实现阶段，非本修订）

- Dashboard 桌面/设备相关前端
- 设备端桌面会话与 confirm UI（对齐 0005）
- 服务端桌面目标/会话路由与审计
- 文档：`device-acp.md` 交叉说明（一句即可）

### 风险

| 风险 | 缓解 |
|------|------|
| 与专家绑定混淆导致 ACP 跑错机器 | DEC-002/005 + AC-006/007 文案；UI 分栏 |
| 无确认静默接管被滥用 | DEC-001 硬门槛；审计 AC-011 |
| 热迁移预期过高 | Non-goals + DEC-003 写清冷备 |
| headless 无法弹窗 | AC-004 unsupported 或 CLI；不默认允许 |
| 与 0005 grant confirm 双弹窗 | 复用同一 confirm 通道；产品文案合并「接管=使用已有 desktop 权限建立会话」 |

## Evolution

- 2026-10-12.1: 初稿 Draft MVP（范围/切片/OQ）；未改业务代码。
- 2026-10-12.2: OQ-001..004 全部按用户「按建议」关闭并写入 DEC-001..004；Status = Draft / Ready for MVP-S1；明确先 S1 桌面目标切换。REQ/AC ID 自本修订起稳定。
- 2026-10-12.3: MVP-S1 落地——API `/devices/desktop-target*`、WS `desktop_takeover`、Dashboard 切换确认、CLI 确认路径；冷备；不改 device_binding。S2 冷备入口 UX / S3 文案强化 / S4 headless GUI 仍开放。
