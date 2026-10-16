# 0019 设备目标：专家默认 + 会话/任务统一

- Spec ID: `0019-device-target-defaults-and-session-unify`
- Status: **Ready**
- Revision: `2026-10-16.1`
- Date: 2026-10-16
- Mode: PRODUCT / IMPLEMENTATION PATCH（叠在 0015 之上，**不修订** 0015 正文）
- Authoritative path: `docs/specs/0019-device-target-defaults-and-session-unify.md`
- Code baseline: `CkEFFAF/Octopus-public`（本地工作区相对 `main` @ `97fccd2b`；`git fetch` 曾因网络失败，以该 tip 与工作区源码为准）
- Relates:
  - **0015 rev3（权威架构）**：`docs/specs/0015-device-execution-and-context-inspection.md` — DEC-03 ExecutionContext；优先级「会话明确 → 专家默认 → 账户默认」；冻结；子任务继承；无列表推断
  - 配置归属：`docs/octopus/configuration-ownership.md`（Expert device binding / Session execution selection）
  - 权限 / enroll：`docs/specs/0005-device-permission-management.md`、`docs/specs/0004-account-auto-device-enrollment.md`（**勿改 Accepted 0004 正文**）
  - 桌面目标独立（0008）：`src/octop/infra/devices/service.py`（desktop target ≠ `device_binding`）
  - 解析实现：`src/octop/infra/execution/service.py`（`resolve` / `default_target` / `save_default_target` / `has_target`）
  - 持久化：`src/octop/infra/db/repos/execution.py`（`ExecutionContext`、`thread_execution_settings`）
  - 专家绑定：`agent.config.device_binding`；API `PATCH` `src/octop/api/routers/agents.py`；UI `dashboard/src/pages/Experts/components/EditAgentDrawer.tsx`
  - 会话选择：`src/octop/api/routers/devices.py`（`/devices/execution-selection/{thread_id}`、`/execution-default`）；turn 解析 `src/octop/api/routers/chat/turn.py`；UI `dashboard/src/pages/Chat/components/DeviceTargetSelect.tsx`
  - 提示词可见性：`src/octop/infra/agents/middleware/device_target.py`
  - 团队继承：`src/octop/infra/agents/teams/device_context.py`、`team_manager.py`、`service.py`；文档 `docs/agent-call-agent.md`、`docs/agent-delegation.md`
  - 装载绑定：`src/octop/infra/agents/manager.py`（读 `device_binding` 注入 middleware）
- Non-overwrite: **不修改** 0015 / Accepted 0004 / 业务代码；本回合 **只新建本文件**；不 commit。

---

## 0. 给 Coder 的阅读顺序

1. §1 Goal / Non-goals + 背景示例  
2. §2 铁律（复述 0015）+ 决策表  
3. §3 DEC（房间统一 ≠ 抹专家默认）  
4. §4 UI / API  
5. §5 ask_agent / AgentTeams 继承  
6. §6 REQ / AC  
7. §7 MVP 切片（可勾选）+ 精确路径  
8. §8 风险 / OQ  

仓库根（Windows）：`D:\Agent_Workspace\octopus\Octopus-public`

---

## 1. Goal / Non-goals

### 1.1 Goal

| ID | 目标 |
|----|------|
| **G1** | 每个专家可绑定一台**默认设备**（已有 `device_binding`；补齐可见性与文档化产品语义）。 |
| **G2** | 「**统一连接设备**」：单任务只需 1 台设备时，多专家（含团队房间成员）默认都跑同一台——用 **会话/房间 scoped override**，**不写回**各专家默认。 |
| **G3** | 多设备协作：各专家可用自己的默认；或在派工时**显式跨设备**新建可见 ExecutionContext。 |
| **G4** | 团队协调者可读：`agent_list` / 团队检视暴露成员 **default target（device/local）** 与当前会话 **model_ref（只读）**。 |

### 1.2 Non-goals

- **不重做** 0015 ExecutionContext / DeviceTrustPolicy / Job 架构。
- **不修复** 团队 `work_step` / evidence 校验 bug（Coder 另轨）。
- **不合并** 0008 桌面目标与专家 `device_binding`（保持独立）。
- 不静默把「列表第一台设备」当作默认。
- 本架构师回合不改业务代码、不 commit。

### 1.3 背景示例（非硬编码产品数据）

云端实况（写进规格便于验收对照，**不是** schema 常量）：

| 专家 | 现状理解 |
|------|----------|
| `27N3HD` | 绑 GPU：`device_id=01M4W2V33NV33E8DSNXN0PQ9ZB`，`working_dir=/home/wjh/workspace` |
| `main` | 似乎无 `device_binding` → 解析落到 **local**（或账户默认）；工作区 root=`/` 属本机/local_shell 语义，**不是**「偷偷选了某台远程」 |

痛点：团队房间协调者看不到成员默认设备 / 当前模型，派工后难以判断「会跑在哪」。

---

## 2. 铁律（复述 0015 rev3 DEC-03 / AC-06）

1. **ExecutionContext 冻结**：Run 开始时冻结 `target_kind` / `device_id` / `working_dir` / `grant_version` / `source`；切换选择只影响**新** Run。  
2. **优先级（写死）**：`session_selection` → `expert_default` → `account_default`。  
3. **无推断列表第一台**：三者皆空 → 明确要求用户选择（现有：`OctopError`「choose an execution device」），禁止按设备列表顺序回退。  
4. **子任务继承父上下文**；**仅显式跨设备派工**才新建可见上下文，并校验账户归属。  
5. **并发复用专家**：目标走 request-scoped（`octop_execution_context` / `octop_device_target`），不得改写共享 agent 实例上的全局绑定。  
6. **无设备绑定时**：允许显式 `target_kind=local`（admin/本机）或账户已存 local；与 `main` 现状一致——**不是**静默挑远程第一台。

现有解析已基本落地：`ExecutionService.resolve` 候选序为  
`(turn 显式, session_selection) → (thread_execution_settings, session_selection) → (device_binding, expert_default) → (preferences.execution_default, account_default)`。

本规格补的是 **产品层「统一」语义、团队房间一键、继承规则写清、agent_list 可见性**。

---

## 3. 决策表（何时生效）

| 层级 | 存储位置 | 何时生效 | 不生效 / 被盖住 | 会不会改专家默认 |
|------|----------|----------|-----------------|------------------|
| **A. 专家默认** | `agents.config_json.device_binding`：`{target_kind, device_id?, root_id?, working_dir?}` | 无会话/房间统一目标，且 turn 未显式选设备 | 有 thread/room `session_selection`，或 turn 带 `device_id`/`target_kind` | —（它本身就是默认） |
| **B. 账户默认** | `users.preferences_json.execution_default` | A 为空且无会话选择 | 有 A 或会话选择 | 否 |
| **C. 会话统一目标** | `thread_execution_settings`（按 `thread_id`） | 该会话已保存明确目标；turn 解析 `source=session_selection` | turn **当次**显式另一目标（仍写 session，供后续 Run） | **否** |
| **D. 团队房间统一目标** | **房间 host thread** 的 `thread_execution_settings`（= C 的一种用法）；派工时经 `device_context` 继承到成员 request | 用户/主持人一键「全体用同一设备」后，成员 `ask_agent` **默认**继承房间目标 | 成员派工参数**显式**指定另一台 / 「用我的默认」 | **否**（禁止批量 PATCH 成员 `device_binding`） |
| **E. 成员覆盖** | 单次 `ask_agent` / 子 Run 的 request-scoped 字段 | 显式跨设备或显式「回退专家默认」 | — | **否** |

### 3.1 优先级链（一句话）

> **当次显式（turn / 派工 override） → 会话/房间统一（thread_execution_settings） → 专家 `device_binding` → 账户 `execution_default` → 强制选择；永不列表第一台。**

### 3.2 冲突例

| 场景 | 结果 |
|------|------|
| 专家绑 GPU，会话选 Notebook | 本会话 Run → Notebook；专家默认仍 GPU |
| 房间一键统一到 GPU，成员 A 默认 Notebook | 成员被 `ask_agent` 时默认跑 GPU（继承）；A 的 `device_binding` 仍是 Notebook |
| 房间统一 GPU，派工时显式 `target=member_default` | 该次子任务用成员自己的 Notebook；房间统一保留给其他成员 |
| 房间统一 GPU，派工显式另一台 `device_id=X` | 新建可见子 ExecutionContext（source 标明跨设备），校验 owner |
| 专家无绑定、账户无默认、会话未选 | 报错/UI 要求选择；**不**自动 `devices[0]` |
| 专家无绑定、账户默认 local | → local（与 main 可对齐） |

---

## 4. DEC（建议决议）

### DEC-001 — 会话/任务「统一目标」= scoped override

- 统一目标只写入 **`thread_execution_settings`**（及由其冻结出的 `ExecutionContext`）。  
- **禁止**为了「统一」去改写各专家 `device_binding`。  
- 清除统一 = 清空该 thread 的 selection（或 UI「恢复专家/账户默认」），专家默认原样回来。

### DEC-002 — 团队「一键全体同设备」= 设房间 host 的统一 Execution 选择

- UI：团队房间 / host 会话工具条提供「全体用同一设备」。  
- 实现：对 **host `thread_id`** 调用现有 `PUT /devices/execution-selection/{thread_id}`（可复用 `DeviceTargetSelect` 的 save 路径）。  
- 成员 `ask_agent`：默认走 `teams/device_context.py` 已捕获的 `octop_device_target` / `octop_execution_context`（继承父）。  
- **不**循环 PATCH 成员 config。

### DEC-003 — 账户默认保留槽位（已实现，MVP 只保证可见）

- 已有：`GET/PUT /execution-default` + `preferences.execution_default`。  
- MVP：团队检视 / 设置入口能读到；不必新表。若某环境未设账户默认，优先级槽位仍保留。

### DEC-004 — 无绑定 = local 或「待选择」，禁止静默远程

- `device_binding` 缺失 ≠ 第一台远程。  
- 显式 local：`target_kind=local, device_id=null`（admin 本机）。  
- 普通账户无设备且无账户默认 → 必须选择。

### DEC-005 — agent_list / 团队检视只读暴露

每条成员至少：

```text
agent_id, name,
default_target: { target_kind: local|device, device_id?, device_name?, working_dir? } | null,
model_ref: string | null   # 专家默认模型或当前会话只读；无则 null
```

不在本规格展开证据校验。

---

## 5. UI / API

### 5.1 哪里设「本专家默认设备」

| 面 | 路径 |
|----|------|
| UI | 专家编辑抽屉：`EditAgentDrawer` →「运行设备」/`deviceBindingLabel`（已有） |
| API | `PATCH /agents/{agent_id}`，`config.device_binding` 白名单键：`device_id` / `target_kind` / `root_id` / `working_dir`（`agents.py` 已校验） |
| 语义 | 清空绑定 = 删除 `device_binding` 键（UI `allowClear` → 继承账户默认） |

### 5.2 哪里设「本会话/本任务统一设备」

| 面 | 路径 |
|----|------|
| UI | 聊天顶栏 / 工作台：`DeviceTargetSelect`（已有 session save） |
| API | `GET/PUT /devices/execution-selection/{thread_id}`；turn 体可带 `device_id` / `target_kind` / `working_dir`（`chat/turn.py`） |
| 语义 | 写入 thread 级 selection；`source=session_selection`；**不**碰 `device_binding` |

### 5.3 团队「一键全体同设备」（本规格新增产品动作）

| 步骤 | 行为 |
|------|------|
| 1 | 协调者在团队房间选择一台设备（或 local） |
| 2 | 调用与 §5.2 相同的 execution-selection API，目标 = **host thread** |
| 3 | Toast：「已统一本房间执行设备；未修改各专家默认绑定」 |
| 4 | 可选只读条：列出成员 default_target，标注「本房间将覆盖为 X（派工时可改）」 |
| 5 | 「取消统一」→ 清空 host thread selection |

**禁止**：批量改成员 `device_binding`；禁止改账户 `execution_default`（除非用户显式点「设为账户默认」——已有 DeviceTargetSelect 能力，与一键统一分离）。

### 5.4 检视 API / 工具

| 面 | 改动 |
|----|------|
| `agent_list` 工具 | 响应增补 `default_target`、`model_ref`（只读） |
| Dashboard 团队面板 | 成员行展示默认设备名 + 模型；离线/无绑定明确文案 |
| 实现锚点 | harness `teams/tools.py` 的 list 载荷；Octopus 侧 enrichment 可在 `AgentManager` / peer 钩子注入（`manager.py` 已区分 team tools） |

---

## 6. ask_agent / AgentTeams 继承规则

对齐 0015：「子任务继承父上下文；显式跨设备才新建」。

```text
Host Run 已冻结 ExecutionContext C_host（可能来自房间统一 / 会话选择 / host 专家默认）
    │
    ├─ ask_agent(member) 无 target 覆盖
    │     → 成员 Run 继承 C_host（device_context.restore_peer_context）
    │     → source 可记 inherited_from_parent；不读成员 device_binding（本次）
    │
    ├─ ask_agent(member, use_member_default=true)  【显式】
    │     → 按成员 device_binding → 账户默认 解析新上下文
    │     → 与父不同设备则 new ExecutionContext（可见）
    │
    └─ ask_agent(member, device_id=... / target_kind=...)  【显式跨设备】
          → 校验 owner + grant；new ExecutionContext；不得默默改绑定
```

现状：`device_context.py` 已把父的 `octop_device_target` / `octop_execution_context` 打进子请求，并校验 `grant_version`。MVP 需：

1. 文档化上述三岔；  
2. 若缺「用成员自己默认」开关，给 `ask_agent` 增加可选参数（或 metadata 约定），默认 = 继承父；  
3. 单测：`tests/unit/agents/test_team_device_context.py` 扩「继承 vs 成员默认 vs 显式第三台」。

---

## 7. REQ / AC

| ID | 要求 | 可观测验收 |
|----|------|------------|
| **AC-01** | 专家默认可设可清 | EditAgentDrawer 保存后 `config.device_binding` 正确；清空后回落到账户默认或待选择 |
| **AC-02** | 会话统一优先于专家默认 | 同专家：会话选 A、绑定 B → Run 的 `ExecutionContext.source=session_selection` 且 device=A；绑定仍为 B |
| **AC-03** | 房间一键统一不抹默认 | 一键后 host selection=统一设备；所有成员 `device_binding` 字节级不变；成员 ask 默认跑统一设备 |
| **AC-04** | 成员显式覆盖 | 派工指定成员默认或另一台 → 仅该子 Run 换目标；房间统一仍在 |
| **AC-05** | 无推断第一台 | 无绑定+无账户默认+无会话选择 → 错误或 UI 强制选择；自动化断言不调用「第一台」逻辑 |
| **AC-06** | agent_list 可见性 | 协调者调用 `agent_list` 见每成员 `default_target` + `model_ref`；Dashboard 团队检视同源字段 |
| **AC-07** | 冻结 | 切换会话设备不影响已开 Run/Job 的原 context（复述 0015 AC-06） |
| **AC-08** | 桌面目标独立 | 切换 0008 desktop target 不改 `device_binding` / thread selection（已有文案 `desktopTargetNote`） |

---

## 8. Coder 最小切片（MVP，可勾选）

> 原则：复用现有 resolve / selection / device_context；先可见性与房间一键，再精细派工参数。

- [ ] **S0 基线断言** — 单测锁定 `ExecutionService.resolve` 四层优先级 + 无目标报错；路径：`src/octop/infra/execution/service.py`，测试 `tests/unit/`（新建或扩现有 execution 测）。  
- [ ] **S1 agent_list enrichment** — list 结果带 `default_target`（解析 `device_binding`，附 device 名）+ `model_ref`（专家默认模型）；锚点：harness team tools + `src/octop/infra/agents/manager.py` / teams 钩子。  
- [ ] **S2 团队检视 UI** — 成员列表只读展示默认设备与模型；路径：Dashboard 团队/Chat 相关组件（接 S1 或 agents list API）。  
- [ ] **S3 房间一键统一** — Host 会话「全体用同一设备」→ `PUT execution-selection`（host thread）；文案声明不改专家默认；路径：`DeviceTargetSelect.tsx` 旁或团队工具条；API 已有 `devices.py`。  
- [ ] **S4 继承 vs 覆盖** — 文档化 +（若缺）`ask_agent` 可选 `target_policy=inherit|member_default|explicit`；扩 `tests/unit/agents/test_team_device_context.py`。  
- [ ] **S5（可延后）账户默认入口提示** — 团队/设置中展示当前 `execution_default`；API 已有 `/execution-default`。

**非 MVP**：批量改绑定向导、跨账户设备、自动把「最空闲设备」当默认。

---

## 9. 数据形状（现状约定，勿 invent 新表 unless 必要）

```text
# 专家默认（已有）
device_binding: {
  target_kind: "device" | "local",
  device_id: string | null,   # local 时必须 null
  root_id?: string,
  working_dir?: string
}

# 账户默认（已有）
preferences.execution_default: {
  target_kind, device_id?, working_dir?
}

# 会话/房间统一（已有表）
thread_execution_settings(thread_id, owner_user_id, device_id, working_dir, work_mode, target_kind)

# 冻结 Run（已有）
ExecutionContext.source ∈ { session_selection, expert_default, account_default }
# 建议（S4）：inherited_from_parent 可作为 source 扩展或 metadata；若改枚举需迁移——MVP 可用 metadata 避免破库
```

---

## 10. 风险 / OQ

| 风险 | 缓解 |
|------|------|
| 误把「一键统一」做成写成员绑定 | DEC-002 + AC-03 回归：断言成员 config_json 不变 |
| 继承父目标导致成员「以为」在用自己的 GPU | UI/提示词标明 effective target；agent_list 同时给 default 与（可选）effective |
| `source` 枚举加值需迁移 | MVP 用 metadata；OQ-1 |
| harness `agent_list` 在 wheel 内 | 优先 Octopus 侧 enrich；不够再 bump harness（OQ-2） |
| fetch 失败、工作区有 0016 dirty | 本规格只加 `??` 文件；实现前 Coder 应对齐最新 main |

**OQ-1**：子 Run `source` 是否扩展 `inherited_from_parent`，还是仅 metadata？  
**OQ-2**：`agent_list` enrichment 能否纯 Octopus 包装，无需 harness bump？  
**OQ-3**：`use_member_default` 是工具参数还是仅 host 系统提示约定？（建议真参数，避免提示词漂移）

**假设**：房间 = team host 的 dashboard thread；一键统一只作用该 thread 的 selection，与 0015「会话明确选择」同层。

---

## 11. Consequences

- 产品语义与已实现 resolve 对齐，减少「统一设备却改坏专家默认」的操作风险。  
- 团队可观测性补齐后，协调者可在派工前看到成员默认目标/模型。  
- 0015 继续作为架构主文档；本文件是可交付的产品/实现补丁，Ready 后可直接派 Coder。

---

## References

- [0015 设备执行与上下文](0015-device-execution-and-context-inspection.md)（rev3）  
- [0005 权限](0005-device-permission-management.md) · [0004 enroll](0004-account-auto-device-enrollment.md)（只读）  
- [configuration-ownership](../octopus/configuration-ownership.md)  
- [agent-call-agent](../agent-call-agent.md) · [agent-delegation](../agent-delegation.md)  
