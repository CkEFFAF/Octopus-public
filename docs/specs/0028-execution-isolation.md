# 0028 Iso-1：执行隔离（专家 FS/OS / team-host 无 MCP / egress）

- Spec ID: `0028-execution-isolation`
- Status: **Ready**
- Revision: `2026-10-17.1`
- Date: 2026-10-17（Asia/Shanghai）
- Mode: ENHANCEMENT（Enhance 0022 + bwrap/docker；**完全治理**分档，非一次性 OS jail）
- Authoritative path: `docs/specs/0028-execution-isolation.md`
- Sibling: `0022-expert-store-boundary`、`0025-mcp-skill-capability-scopes`、`0015`、`0005`、`0026`、`0027`
- Repository: `CkEFFAF/Octopus-public`
- Git 起点: `origin/main` @ `de5edcef3be4723e4a15e16ba33ad3b01108171e`
- 探测: `/workspace/0026-28-probe/PROBE-REPORT.md`
- 约束: **只规格**；不写生产代码、不直接改 VPS

---

## Goal

1. 专家文件系统（及后续 OS）隔离达到可强制、可验收基线。
2. **Team host 无 MCP** 为 hard invariant——含 0025 设备包 / default_open / 显式名单均不得突破。
3. **Egress 白名单** 与 **开发/生产环境分离** 成文并可阶段性落地。

---

## Non-goals

- S0 不要求每专家独立 OS uid/ns（列为 S1+）。
- 不取消 0025 设备能力包；隔离在「生效工具集」之外继续约束 FS/egress。
- 不把设备 grant（0005）整表重做；与之组合而非替代。
- 不改 Ask/Plan 已清空 mcp/skills 的行为（保留）。

---

## DEC

| ID | 决议 |
| --- | --- |
| **DEC-I01** | **S0 FS 基线**：继承 0022 存储边界；Linux 在 `root_dir` 非宿主根时 **强制 bwrap**（或等价 path rewrite）；缺 bwrap → 拒绝高风险写或明确降级并告警。Docker/opensandbox 为可选加强档。 |
| **DEC-I02** | **S1+ OS jail**：每专家 rootless container / user ns 单独立项；不阻塞 0026/0027/0025 S0。 |
| **DEC-I03** | **Team host 无 MCP = hard invariant**：`is_team_agent` → `_resolve_turn_mcp_servers` **必须** `None`；装配不挂 MCP/技能/插件。回归测试覆盖：专家名单、账号 `default_open`、**设备 `capability_policy_json`（0025）**、Dashboard 显式列表 —— **全部不能**注入 host。 |
| **DEC-I04** | **Egress S0**：管理端元数据出口允许名单（更新源、Tunnel/API 配置域、模型提供商域名可配）；专家工具出口继续走 device grant / 命令 guard / 既有 policy。**S1** 统一 `egress_policy` 对象。 |
| **DEC-I05** | **开发/生产分离**：独立 `OCTOP_HOME`、独立 JWT/连接器凭据；文档+启动检查禁止开发实例指向生产 OctopData（可检测路径/标记文件）。 |
| **DEC-I06** | 与 0025 **无冲突**：0025 Non-goal 已声明不改 team-host；本规格提供验收加固。隔离层不得绕过 resolve-time union 语义，但可在工具执行期再拦 FS/网络。 |

---

## 现状摘要

- 0022 FS 边界 + bwrap/docker 文档 **部分有**；完整 OS jail **无**。
- Team host 无 MCP **代码已强制**（`processor.py`）；需与 0025 设备包交叉验收。
- 产品级 egress 白名单 / 开发生产出口分离 **缺**。

---

## 需求与验收

| ID | 需求 |
| --- | --- |
| **REQ-I01** | S0 强制 FS 隔离门禁（bwrap/等价）可开关策略但生产默认开。 |
| **REQ-I02** | Team host 在任何 MCP 来源下工具集仍为空（无 MCP）。 |
| **REQ-I03** | Egress 允许名单可配置；默认收紧管理端出口。 |
| **REQ-I04** | 开发/生产 home 与凭据分离有检查清单与可选启动断言。 |

| ID | AC |
| --- | --- |
| **AC-I01** | Given team host；When 专家/设备包/default_open/显式 mcp 均试图注入；Then 生效 MCP 仍为空。 |
| **AC-I02** | Given Linux + 非根 root_dir + 无 bwrap；When 执行写文件工具；Then 拒绝或安全降级（按 DEC-I01），不静默写宿主敏感路径。 |
| **AC-I03** | Given 生产标记的 OCTOP_HOME；When 开发配置误指同一路径；Then 检查失败或强警告。 |
| **AC-I04** | Given egress 允许名单；When 管理端访问名单外域名（测桩）；Then 被拦或告警（S0 至少文档+钩子位）。 |

---

## 实施切分

| 切片 | 范围 | 必过 |
| --- | --- | --- |
| **S0** | AC-I01 回归矩阵（含 0025 设备包）；bwrap 门禁；开发/生产分离清单；egress 配置骨架 | AC-I01–I03 |
| **S1** | 统一 egress_policy；强化 Docker sandbox 档 | AC-I04 |
| **S2** | 每专家 OS jail | DEC-I02 |

可与 **0025 S0 并行**，但 **AC-I01 必须同迭代或先于设备包合入**。

---

## Coder brief

```text
规格: docs/specs/0028-execution-isolation.md（Rev 2026-10-17.1）
必测: team host × (expert mcp | default_open | device capability_policy | explicit list) → 无 MCP
Enhance: processor.py invariant 测试；bwrap 门禁；docs 开发/生产分离
不要: 削弱 0022；让设备包突破 host；现场改 VPS
与 0025: 交叉引用 DEC-I03；无字段冲突（勿占 028 迁移号做隔离 schema，另编号）
```

---

## 与 0025 冲突检查

| 点 | 结论 |
| --- | --- |
| Team host 无 MCP | **无冲突** — 0025 已声明保留；0028 验收加固 |
| 设备 capability_policy | **协同** — 仅非 host 专家生效；host 豁免测试必过 |
| default_open | **协同** — host 仍不注入 |

---

## Evolution

| Rev | 变更 |
| --- | --- |
| `2026-10-17.1` | 首版 Ready（完全治理 Iso-1）。 |
