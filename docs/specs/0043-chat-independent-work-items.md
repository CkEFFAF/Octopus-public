# 0043 聊天与独立工作项分离（G3）

- Revision: **2026-11-07.2**（Asia/Shanghai）｜Contract: **Ready**
- Owner: Octopus 架构师 → 总管派 Coder｜权威源：本文件
- Decision basis: 用户授权开发；交接 `docs/handoffs/2026-11-07-grok/`（03-independent-task-runtime + design-report + README）；Codex 负责「工作时继续聊天 / 进度展示」UI，本规格只冻结**后端/协议**
- Code baseline: `CkEFFAF/Octopus-public` **`origin/main` @ `ca771fd1e466b97bea26c433be505c6a053aa7cb`**（`ca771fd 0042: reminders origin-thread delivery (G2)`；本轮已 `git fetch` 核对）
- Delivery: **compact SDD**（build-adaptively）｜Verification: **strict**（进度只读 / 不串设备 / 重启恢复）｜Continuity: collaborative（GPT 交接）
- 编号说明：tip 已有 `0040` / `0041`（G1）/ `0042`（G2）；本规格取 **0043**（G3）
- 依赖：功能依赖 **0041** `emit_thread_changed` / `push_to_user`（tip 已合）；**不**功能依赖 0042，但结果投递到 origin thread 时须与 0042 一样「先持久化再通知」
- 约束：**只写 docs/specs**；不改产品代码、不改 `dashboard/`、不碰 `octopus1/chat-task-work`；不 commit / push / PR / 部署；不派 Coder；不替换 Harness；不做全量重构 PR；0039 Mac **搁置勿动**；密钥不明文进日志

---

## 0. 给 Coder / GPT / Codex 的阅读顺序

1. §1 Goal / Non-goals / 模块边界  
2. §2 复用映射（tip 现状 → 缺口）  
3. §3 DEC（已拍板）  
4. §4 Codex 契约面（HTTP + JSON + 事件）  
5. §5 REQ / AC  
6. §6 迁移 / 错误码 / 授权 / 取消语义  
7. §7 Coder 实现指南与测试命令  
8. §8 与 0041 / 0042 / G4 / G5 关系  

---

## 1. Goal / Non-goals / 模块边界

### Goal

用户发起**长任务**后，仍能在交互会话里聊天或**只读查询进度**，无需中断或向正在执行的工具流插入消息。工作项有**持续可读**的权威状态与事件；换电脑 / 刷新 / 重启后仍可查看。最终结果回到**来源会话**（稳定事件 ID），不在所有会话各写一遍。

### In scope（S0 = 最小端到端工作项）

- 创建后台工作项（幂等 `command_id`、来源 thread、任务说明、明确执行目标与资源引用）
- 列出：当前会话相关工作项 + 账户未完成工作项
- 读详情与游标事件（阶段 / 工具名 / 时间 / 阻塞原因 / 成果引用）
- **读进度 = 只读查询**（见 DEC-0043-06）
- 追加任务要求 = 显式 work-item input（非 0033 steer）
- 取消准确 task 或 attempt；区分「请求取消」与「已确认终止」
- 人工审批 / 凭据 / 权限拒绝用独立字段；禁止假成功
- 调度：输入先持久化再启动；asyncio 调度并为交互保留容量；Jobs/设备回执恢复；不盲目重放副作用工具
- 账户提示：新增 `task.changed`；结果投递 origin 时**另调** 0041 `emit_thread_changed`
- 成对迁移 **036**；单元 + 集成（含真实 lifecycle/Jobs，禁止只 mock status）
- OpenAPI / 交接 JSON 契约供 Codex

### Non-goals

- **不**修改 `dashboard/`（入口、进度面板、继续聊天 UI 由 Codex）
- **不**误删 / 绕过 **agent lifecycle 锁**或 **per-(agent,thread) 执行锁**（同专家不同 thread 已可并发；本规格不靠删锁「假并发」）
- **不**削弱 0033 队列 / 插入 / 显式中断（仍服务「修改同一个正在运行的交互 turn」）
- **不**为每次问进度启动完整专家推理，**不**取消工作工具来响应查询
- **不**新建外部队列服务（Kafka 等）；**不**让一个可变 agent target 同时指向多个设备
- **不**替换 Harness 完整多 agent 编排；**不**拷贝 DeepSeek 全部实现（GitHub 假设 / 文件夹即安全边界 / DI）
- **不**引入共享无锁 checkpoint 或绕过设备授权
- **不**把迁移 / P2P（G4）/ ACP token（G5）/ UI 混进同一次重构 PR
- **不**部署云端；**不**动 0039 macOS

### 模块边界

| 层 | 职责 | 禁止 |
| --- | --- | --- |
| `api/routers/work_items.py`（新建） | 薄 HTTP：鉴权、校验、调 service | 在路由里拼事件、启 worker、写 checkpoint |
| `infra/work_items/`（新建 service + models） | 创建/列表/详情/事件/input/取消；状态机；调度入口 | 直接 SQL 散落；绕过 ExecutionService 选设备 |
| `infra/db/repos/work_items.py` | `work_items` / `work_item_inputs` SQL | 业务状态机 |
| `infra/db/repos/run_events.py` + `execution` | 扩展可选 `work_item_id`；进度事件落库 | 用假 status 冒充 Job 完成 |
| `infra/gateway/thread_events.py` + Gateway | `emit_thread_changed`（0041）；新建 `emit_task_changed` | 手写同名 JSON；经账户通道推 token |
| `infra/gateway/input_queue.py` / chat inputs | **仅**交互 thread 的 0033 路径 | progress API 调用 steer / queue |
| `infra/task_board/` | 既有看板规划/评审/定时 | S0 **不**强制每个聊天工作项进 task-board JSON |
| Harness / AgentManager | worker thread 上跑 turn；保留锁 | 为进度查询开第二套图执行 |

---

## 2. 复用映射（tip `ca771fd`）与缺口

核对 worktree：`/workspace/octopus-g3` @ `ca771fd`。

| 能力 | tip 现状 | 对 G3 的复用 | 缺口（才新增） |
| --- | --- | --- | --- |
| **task-board** | `task_boards` JSON 账本；状态 `planning/todo/running/done/failed`；`Run` 挂 board task；执行用 `board-{task\|run}` session_key + CronDelivery | 概念参考（目标、run、验收分离）；可选后期关联 `board_task_id` | **无** origin/worker thread 分离；状态集不含 waiting_* / unknown；无按工作项游标事件 API；JSON blob 不宜作聊天后台权威账本 → **S0 不复用为权威存储** |
| **run_events** | 表含 owner/agent/thread/run/context/kind/status/payload；`ChatInputRepo` 用 `chat-input:{owner}:{command_id}` 幂等；Jobs `kind=job`；inspection `GET .../run-events` | **进度事件与 Job 回执权威落点**；input 幂等模式可抄 | 无一等 `work_item_id`；列表按 thread 而非工作项；缺 work-item 生命周期 kind |
| **ExecutionContext** | `execution_contexts` 不可变快照：device/working_dir/policy/grant/work_mode；`ExecutionService.for_run` | **每次 attempt 绑定一条 immutable context** | 无 `work_item_id` 列 |
| **Jobs / reconciler** | `ExecutionReconciler` 对 due jobs 调 `jobs.status`；不重放命令；容量 Semaphore(4) | 重启核实 Jobs/设备回执；外部进程可继续 | 须与 worker turn / 子 agent 生命周期字段可区分（payload 已有 job_id；工作项层再挂 attempt） |
| **child invocation / 协作资源** | peer/child 回执 + `collaboration_resources`；publish_artifact → resource_id/version | 成果只暴露已授权 resource 引用 | 不是用户级「独立工作项」主模型 |
| **0033 steering** | `GET/POST .../inputs`、`steer`；默认排队；显式插入/中断 | **保留**：改「同一交互 turn」仍走此路 | **硬边界**：progress / 普通聊天 **不得**走 steer；追加工作项要求走 work-item input |
| **0041 helper** | `Gateway.emit_thread_changed` → `thread_events.py` → `push_to_user`；`thread.changed` schema_version=1 | 结果写入 origin 后发 `thread.changed`；账户通道复用 | 工作项状态变更若只靠 `thread.changed` 会与会话列表提示混淆 → **另增 `task.changed`**（仍 `push_to_user`） |
| **Thread 锁** | `ws_channel` per-thread 锁；`AgentManager._thread_execution_locks[(agent,thread)]`；同专家不同 thread 可并发 | worker 用**独立** thread → 不挡 origin 聊天 | **禁止**删锁 |
| **Sidebar background_tasks** | history/sidebar 聚合 `kind=job` 摘要 | 可继续展示 Job；S0 另提供 work-items 列表 | 不是完整工作项 API |

**结论（S0 存储）**：映射证明 task-board JSON **不够**作权威工作项账本；须 **新表** `work_items` + `work_item_inputs`，并 **ALTER** `run_events` / `execution_contexts` 增加可空 `work_item_id`（迁移 **036**）。

---

## 3. DEC（拍板）

| ID | 决议 | 状态 |
| --- | --- | --- |
| **DEC-0043-01** | **身份分离**：`task_id`（工作项）≠ `origin_thread_id`（用户交互会话）≠ `worker_thread_id`（执行会话）≠ `run_id` ≠ `attempt_id` ≠ input `command_id` ≠ `event_id`。禁止把上述概念全部塞进一个 `session_key` 冒充 | resolved |
| **DEC-0043-02** | **模型**：用户 Thread = 交互；WorkItem 记录 origin_thread / owner / agent / 执行目标 / 当前 run·attempt / 结果资源与报告；每次尝试有独立 worker thread + **immutable** ExecutionContext（创建后只读） | resolved |
| **DEC-0043-03** | **状态枚举**（工作项权威 `status`）：`queued` \| `running` \| `waiting_input` \| `waiting_review` \| `blocked` \| `failed` \| `completed` \| `cancelled` \| `unknown`。模型自报成功仅写入 `reported_outcome`（可选字段）；**禁止**用工具连接结束或 transport completed 直接推断 `completed` / 已验收 | resolved |
| **DEC-0043-04** | **锁**：保留 tip 的 agent lifecycle 锁与 per-(agent,thread) 执行锁；S0 靠 **独立 worker_thread** 实现「聊天不堵后台」，不删锁 | resolved |
| **DEC-0043-05** | **0033 vs 本规格**：交互 turn 的队列/插入/中断 = 0033。工作项 progress = 只读。工作项「追加要求」= `POST .../inputs`（work-items），绑定准确 `task_id` + 可选 `target_run_id`/`attempt_id`；指向已结束/非当前 run → **409 CONFLICT**，不静默改旧 run | resolved |
| **DEC-0043-06** | **进度只读硬边界**：`GET` progress/detail/events **不得**：写入 worker 对话、重启 worker、改 chat_input 队列、调用 steer、取消工具。连续 N 次查询不得产生新的 worker user 消息 | resolved |
| **DEC-0043-07** | **事件**：新增账户通知帧 **`task.changed`**（`schema_version=1`），经同一 `push_to_user`；**禁止**复制 0041 JSON 手写。实现 `emit_task_changed`（可与 thread_events 同文件或旁路模块）。结果 canonical 写入 origin 后**另调** `emit_thread_changed(reason=input|completed|attention)`。`task.changed` **不**与 G1 抢 helper 签名 | resolved |
| **DEC-0043-08** | **origin_thread 删除后**：工作项行**保留**可查（owner 仍可 GET）；`origin_thread_id` 保留作墓碑；**跳过**向已删 thread 的 history append / thread.changed；仍发 `task.changed`；详情里 `origin_thread_missing=true`。用户禁用 / 撤权：停止调度与推送；已落库数据按账号隔离只读或 403（与 tip USER_DISABLED 一致） | resolved |
| **DEC-0043-09** | **取消**：`cancel_requested_at` 与 `status=cancelled`（已确认终止）分离。请求取消后 Jobs/工具可能仍在外部跑 → 观察为 `cancel_requested` 子状态或 `status` 仍 `running` 且 `cancel_requested=true`，直到 reconciler/worker 确认 → 再 `cancelled`。未知回执 → `unknown`，**不**自动第二次执行 | resolved |
| **DEC-0043-10** | **幂等创建**：同一 owner + `command_id` 重试返回同一 `task_id`（200/既有表示例）；冲突载荷 → 409。顺序：**先 INSERT work_item(+input) 持久化**，再异步派发 worker | resolved |
| **DEC-0043-11** | **调度与容量**：现有 asyncio；进程内为交互 turn 保留明确槽位（建议：后台派发不抢占 origin thread 锁；全局可设后台 worker 并发上限，默认 ≥1 且交互优先）。不新建外部队列服务 | resolved |
| **DEC-0043-12** | **执行目标**：创建时冻结 `device_id` / `target_kind` / `working_dir`（及 policy/grant 版本进 ExecutionContext）。两工作项不同设备/目录不得串指令、资源、取消、权限。禁止一可变 target 同时指多设备 | resolved |
| **DEC-0043-13** | **恢复**：重启先读 work_items + Jobs/设备回执；能确认则恢复 `running`/`blocked`/…；不能确认 → `unknown`；**禁止**盲目重放有副作用工具。创建后、派发前崩溃：恢复只看到已持久化行，**不**重复创建（靠 command_id） | resolved |
| **DEC-0043-14** | **结果投递**：最终对用户可见结果（摘要 + 资源引用）写入 **origin_thread** canonical history（稳定 message id，建议 `work:{task_id}:result:{attempt_id}`），并 `task.changed` + `thread.changed`；**不**扇出到账户下所有会话正文 | resolved |
| **DEC-0043-15** | **S0 与 task-board**：权威 API = `/api/work-items*`。不强制写入 task-board JSON。可选字段 `board_task_id` 预留，S0 可 null。禁止为「看起来统一」把聊天工作项塞进 board revision 冲突协议 | resolved |
| **DEC-0043-16** | **迁移编号**：成对 **`036_work_items.sql` + `036_work_items.pg.sql`**（tip 最高 035；0042 未占 036 DDL）。禁止改已上线迁移 | resolved |
| **DEC-0043-17** | **阻塞/审批字段**：`block_reason` 枚举/短码 + 可选 `block_detail`（无密钥）；`needs_credential` / `needs_approval` / `permission_denied` 独立布尔或 reason，**禁止**用 `completed`+空输出伪装成功 | resolved |
| **DEC-0043-18** | **DeepSeek 借鉴边界**：借鉴「工作项 / 输入 / 执行尝试 / 报告 / 通知」分离；不照搬其仓库安全模型与 DI | resolved |

---

## 4. Codex 契约面（冻结）

鉴权：与现网 chat/task-board 相同（`current_user` + agent 访问校验）。所有路径前缀默认挂在现有 `/api` 路由树。

### 4.1 创建工作项

`POST /api/work-items`

```json
{
  "command_id": "01JBCLIENTCMD...",
  "agent_id": "opaque-agent-id",
  "origin_thread_id": "opaque-thread-id",
  "title": "短标题",
  "instructions": "任务说明",
  "execution": {
    "target_kind": "device",
    "device_id": "opaque-device-id",
    "working_dir": "/optional/path"
  },
  "resources": [{"resource_id": "res_...", "version": 1}],
  "schema_version": 1
}
```

**响应 200**（新建或幂等命中）：

```json
{
  "task_id": "01JBTASK...",
  "status": "queued",
  "agent_id": "opaque-agent-id",
  "origin_thread_id": "opaque-thread-id",
  "worker_thread_id": null,
  "current_run_id": null,
  "current_attempt_id": null,
  "created_at": 1794028800,
  "updated_at": 1794028800,
  "idempotent_replay": false,
  "schema_version": 1
}
```

| 规则 | 说明 |
| --- | --- |
| 幂等键 | `(owner_user_id, command_id)` 唯一 |
| `idempotent_replay` | 同 command_id 且同语义载荷 → true；载荷冲突 → **409** `WORK_ITEM_COMMAND_CONFLICT` |
| 派发 | 响应可在 worker 启动前返回（`queued`）；禁止「先跑后写库」 |

### 4.2 列表

`GET /api/work-items?origin_thread_id=&status_group=open|all&limit=50&before=`

- `status_group=open`（默认）：`queued|running|waiting_input|waiting_review|blocked|unknown`（及 `cancel_requested` 仍运行中）
- 无 `origin_thread_id`：账户内未完成（+ 可选最近终态，S0 以 open 为主）
- 有 `origin_thread_id`：该会话发起的工作项（须校验 owner）

```json
{
  "items": [ { "task_id": "...", "title": "...", "status": "running", "origin_thread_id": "...", "updated_at": 1794028800, "cancel_requested": false } ],
  "has_more": false,
  "schema_version": 1
}
```

### 4.3 详情

`GET /api/work-items/{task_id}`

```json
{
  "task_id": "01JBTASK...",
  "title": "短标题",
  "instructions": "任务说明",
  "status": "running",
  "reported_outcome": null,
  "cancel_requested": false,
  "cancel_requested_at": null,
  "agent_id": "...",
  "origin_thread_id": "...",
  "origin_thread_missing": false,
  "worker_thread_id": "...",
  "current_run_id": "...",
  "current_attempt_id": "...",
  "execution": {
    "target_kind": "device",
    "device_id": "...",
    "working_dir": "...",
    "context_id": "..."
  },
  "progress": {
    "phase": "tool_running",
    "active_tools": ["shell"],
    "last_event_at": 1794028800,
    "block_reason": null,
    "needs_approval": false,
    "needs_credential": false,
    "permission_denied": false
  },
  "artifacts": [{"resource_id": "res_...", "version": 1}],
  "created_at": 1794028800,
  "updated_at": 1794028800,
  "schema_version": 1
}
```

`GET /api/work-items/{task_id}/progress`：返回与详情中 `progress` + `status` + ids 同构的**只读**子集（便于 Codex 轮询）；语义同 DEC-0043-06。

### 4.4 游标事件

`GET /api/work-items/{task_id}/events?before=&limit=100`

```json
{
  "events": [
    {
      "event_id": "01JBEVT...",
      "seq": 42,
      "created_at": 1794028800,
      "kind": "phase",
      "status": "running",
      "phase": "tool_running",
      "active_tools": ["shell"],
      "block_reason": null,
      "message": null,
      "artifacts": [],
      "job_id": null,
      "attempt_id": "01JBATT..."
    }
  ],
  "has_more": false,
  "schema_version": 1
}
```

| 规则 | 说明 |
| --- | --- |
| 权威 | 持久化 `run_events`（`work_item_id` 过滤）± work_item 状态行；WS 仅提示 |
| `active_tools` | 仅安全工具名；无参数 |
| 游标 | S0 用单调 `seq`（表自增 id）或 `before` event seq；**不**宣称跨节点完美有序以外的能力 |
| 禁止 | 事件里出现凭据、绝对本地路径（成果只用 resource_id/version） |

### 4.5 追加任务要求（显式 input）

`POST /api/work-items/{task_id}/inputs`

```json
{
  "command_id": "01JBINPUT...",
  "text": "请改为导出 PDF",
  "target_run_id": "opaque-run-id-or-null",
  "target_attempt_id": "opaque-attempt-or-null",
  "schema_version": 1
}
```

| 结果 | 行为 |
| --- | --- |
| 200 | 接受；写入 `work_item_inputs`；由调度在安全边界注入 **worker**（非 origin） |
| 409 `WORK_ITEM_RUN_CONFLICT` | target 不是当前 run/attempt 或已终态 |
| 409 `WORK_ITEM_COMMAND_CONFLICT` | command_id 冲突 |
| **禁止** | 调用 0033 `steer`；改写无关 thread 队列 |

### 4.6 取消

`POST /api/work-items/{task_id}/cancel`

```json
{
  "command_id": "01JBCANCEL...",
  "scope": "task",
  "attempt_id": null,
  "schema_version": 1
}
```

`scope`：`task` \| `attempt`（attempt 时 `attempt_id` 必填）。

**响应**：

```json
{
  "task_id": "...",
  "cancel_requested": true,
  "cancel_requested_at": 1794028800,
  "status": "running",
  "terminated": false,
  "schema_version": 1
}
```

确认终止后：`status=cancelled`，`terminated=true`（可通过详情/事件观察到；本响应在仅「受理取消」时可为 `terminated=false`）。

### 4.7 账户事件 `task.changed`

通道：`/api/notifications/ws`（与 0041 相同）。

```json
{
  "type": "task.changed",
  "event_id": "01JB...",
  "task_id": "01JBTASK...",
  "agent_id": "opaque-agent-id",
  "origin_thread_id": "opaque-thread-id-or-null",
  "run_id": "opaque-run-id-or-null",
  "reason": "created",
  "status": "queued",
  "updated_at": 1794028800,
  "schema_version": 1
}
```

`reason`：`created` \| `running` \| `progress` \| `waiting` \| `blocked` \| `completed` \| `failed` \| `cancelled` \| `unknown`。`progress` 可合并（同 task ≥1s 或阶段变化）；终态与 `created`/`blocked`/`waiting` **不可丢**。

**不出现**：token、工具 args、密钥、完整 instructions 正文（可用短 title）。

### 4.8 与 0033 / 交互聊天的边界（契约摘要）

| 用户意图 | API | 是否动 worker |
| --- | --- | --- |
| 闲聊 / 无关问题 | 既有 chat WS/HTTP → **origin_thread** | 否 |
| 看进度 | `GET .../progress` 或 detail/events | **否** |
| 修改进行中的**交互** turn | 0033 inputs/steer | 是（同一 thread） |
| 修改**后台工作项** | `POST .../work-items/{id}/inputs` | 是（仅该 worker） |
| 停止后台工作项 | `POST .../cancel` | 请求取消该 task/attempt |

---

## 5. REQ / AC

| ID | 需求 |
| --- | --- |
| **REQ-0043-01** | 可幂等创建工作项；持久化先于派发 |
| **REQ-0043-02** | origin 会话可继续聊天；不占用 worker 执行锁 |
| **REQ-0043-03** | 进度查询只读；不产生 worker user 消息、不取消工具 |
| **REQ-0043-04** | 列表/详情/事件跨设备一致（同账号授权 API） |
| **REQ-0043-05** | 两工作项执行目标隔离（设备/目录/权限/取消） |
| **REQ-0043-06** | 客户端断线不取消工作项 |
| **REQ-0043-07** | 取消区分请求与确认终止 |
| **REQ-0043-08** | 恢复：未知不自动重放副作用；用户可见 `unknown` |
| **REQ-0043-09** | origin 删除后工作项仍可查；结果不再写入已删 thread |
| **REQ-0043-10** | 审批/凭据/权限拒绝独立字段 |
| **REQ-0043-11** | 结果回 origin + 稳定 id；发 `task.changed` 与 `thread.changed` |
| **REQ-0043-12** | 保留 0033 与线程锁行为；回归不破坏 |

| ID | 验收 |
| --- | --- |
| **AC-0043-01** | A 发起长任务（含可观测外部 Job/工具）；在 origin 问无关问题；任务与外部进程继续 |
| **AC-0043-02** | 连续查询进度 ≥10 次：无新 worker user 消息、无工具取消、无 steer 调用 |
| **AC-0043-03** | 两工作项不同 device/working_dir：指令、资源引用、取消、权限互不串 |
| **AC-0043-04** | 换电脑（同账号）GET 列表/详情/事件一致；断线重连不导致 cancel |
| **AC-0043-05** | 创建持久化后、派发前杀进程：恢复不出现第二 task；同 command_id 仍同一 task_id |
| **AC-0043-06** | Job/设备回执 unknown：status=`unknown`；不自动第二次执行副作用工具 |
| **AC-0043-07** | 删除 origin_thread：工作项仍 GET 成功且 `origin_thread_missing=true`；无向坟头 append；用户禁用后推送/调度停 |
| **AC-0043-08** | 集成测试使用真实 lifecycle + Jobs（或设备 fake 但走 reconciler 路径），**禁止**仅 mock 一个 status 字段宣称 AC 通过 |
| **AC-0043-09** | 回归：0033 队列/插入；同专家两 thread 并发；0041 `thread.changed` 仍可用 |

---

## 6. 迁移 / 错误码 / 授权 / 兼容

### 6.1 迁移 036（成对）

`036_work_items.sql` / `036_work_items.pg.sql`（列类型按方言调整；语义如下）：

```sql
-- work_items（权威工作项行）
CREATE TABLE work_items (
  task_id TEXT PRIMARY KEY,
  owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  agent_id TEXT NOT NULL,
  command_id TEXT NOT NULL,
  origin_thread_id TEXT,
  worker_thread_id TEXT,
  title TEXT NOT NULL,
  instructions TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  reported_outcome TEXT,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  cancel_requested_at REAL,
  current_run_id TEXT,
  current_attempt_id TEXT,
  context_id TEXT,
  target_kind TEXT NOT NULL DEFAULT 'device',
  device_id TEXT,
  working_dir TEXT,
  board_task_id TEXT,
  block_reason TEXT,
  needs_approval INTEGER NOT NULL DEFAULT 0,
  needs_credential INTEGER NOT NULL DEFAULT 0,
  permission_denied INTEGER NOT NULL DEFAULT 0,
  artifacts_json TEXT NOT NULL DEFAULT '[]',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  UNIQUE (owner_user_id, command_id)
);
CREATE INDEX idx_work_items_owner_status ON work_items(owner_user_id, status, updated_at);
CREATE INDEX idx_work_items_origin ON work_items(owner_user_id, origin_thread_id, updated_at);

CREATE TABLE work_item_inputs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  input_id TEXT NOT NULL UNIQUE,
  task_id TEXT NOT NULL REFERENCES work_items(task_id) ON DELETE CASCADE,
  owner_user_id INTEGER NOT NULL,
  command_id TEXT NOT NULL,
  target_run_id TEXT,
  target_attempt_id TEXT,
  status TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  UNIQUE (owner_user_id, command_id)
);

ALTER TABLE run_events ADD COLUMN work_item_id TEXT;
CREATE INDEX idx_run_events_work_item ON run_events(owner_user_id, work_item_id, id);

ALTER TABLE execution_contexts ADD COLUMN work_item_id TEXT;
```

PG 文件使用等价 DDL（`BOOLEAN`、`BIGSERIAL` 等按项目惯例）。`_schema_version → 36`。

### 6.2 错误码

| code | HTTP | 何时 |
| --- | --- | --- |
| `WORK_ITEM_NOT_FOUND` | 404 | 无此 task 或非 owner |
| `WORK_ITEM_COMMAND_CONFLICT` | 409 | command_id 载荷冲突 |
| `WORK_ITEM_RUN_CONFLICT` | 409 | input/cancel 指向错误 run/attempt |
| `WORK_ITEM_INVALID` | 400 | 字段非法 |
| `WORK_ITEM_FORBIDDEN` | 403 | agent/设备/授权失败（或复用 `FORBIDDEN`） |
| 既有 | | `USER_DISABLED` / `DEVICE_OFFLINE` / `EXECUTION_TARGET_REQUIRED` / `NOT_FOUND` 等保持 |

S0 可在 `ErrorCode` 增补上表；映射进 `ERROR_HTTP_STATUS`。

### 6.3 授权

- 所有 API：`user.id == work_item.owner_user_id`
- 创建时：`origin_thread` 必须存在且 `user_id/agent_id` 匹配（除非产品允许无 origin——S0 **要求** origin）
- 设备目标：走既有 ExecutionService / grant；失败 → 明确错误，不假成功
- 通知：仅 push 给 owner（同 0041）

### 6.4 兼容

- 旧客户端忽略 `task.changed` / 未知字段 → 安全
- 不修改 0033 / task-board 既有路径语义
- OpenAPI 增补 tag `work-items`

---

## 7. Coder 实现指南

### 分支

- 建议：`feature/0043-chat-independent-work-items`
- 基线：**最新** `origin/main`（至少含 `ca771fd` / 0041+0042）
- **禁止**在 `D:\Agent_Workspace\octopus1\chat-task-work` 改后端；**禁止**改 `dashboard/`

### 可写路径（建议）

- `src/octop/api/routers/work_items.py`（新建）+ `api/app.py` 挂载
- `src/octop/infra/work_items/`（`service.py` / `models.py` / 调度）
- `src/octop/infra/db/repos/work_items.py`
- `src/octop/infra/db/migrations/036_work_items.sql` + `.pg.sql`
- `src/octop/infra/db/repos/run_events.py` / `execution.py`（可空 `work_item_id`）
- `src/octop/infra/gateway/thread_events.py` 或旁路 `task_events.py`：`emit_task_changed`
- `src/octop/infra/gateway/gateway.py`（暴露 helper）
- `src/octop/infra/errors.py` + i18n 键
- `src/octop/api/openapi_meta.py`
- `tests/unit/work_items/`、`tests/integration/test_work_items_0043.py`
- **只读参考**：`task_board/service.py`、`chat_inputs.py`、`execution/reconciliation.py`、`input_queue.py`、0033 路由

### 实现要点

1. Worker session_key 建议：`{agent_id}:dashboard:{user_id}:work-item-{task_id}`（与 board- 前缀区分）；`continue` 同 task 复用同一 worker thread。  
2. 派发：持久化 → `task.changed(created)` → asyncio 任务启动 worker turn；失败写 `failed`/`blocked`。  
3. 进度：worker/工具/Job 观察写入 `run_events`（带 `work_item_id`）；GET 只读聚合。  
4. Input：先入 `work_item_inputs`；在 worker 边界应用（可复用 Harness 插入语义，但 **API 不得**暴露为 0033 steer）。  
5. 取消：设 `cancel_requested` → 合作取消 worker + 观察 Jobs → 终态 `cancelled` 或超时后 `unknown`。  
6. 密钥：日志/测试快照禁止明文 token。

### 测试命令

```bash
uv run pytest tests/unit/work_items/ tests/integration/test_work_items_0043.py -q
uv run pytest tests/integration/test_chat_inputs.py tests/unit/agents/test_immediate_steering.py -q
uv run pytest tests/integration/test_thread_changed_0041.py -q
# 须含：真实 DB + Jobs/reconciler 路径（AC-0043-08）
make all   # 须绿；CI Linux + Windows
```

### 交付物（Coder → Codex / 总管）

- 本 §4 JSON 冻结示例 + OpenAPI 摘要  
- 实际测试命令与结果  
- 未实现项显式列出（例如：task-board 双向同步、跨用户委托、百分比进度）  
- 迁移 036 已在 SQLite+PG 成对验证  

---

## 8. 与其它规格

| 规格 | 关系 |
| --- | --- |
| **0041 G1** | 复用 `emit_thread_changed` / `push_to_user`；本规格**新增** `task.changed`，不改 `thread.changed` schema |
| **0042 G2** | 无硬依赖；结果写入 origin 的「先持久化再通知」与 0042 对齐 |
| **0033** | 交互 steering 保留；硬边界见 DEC-0043-05/06 |
| **0028 / 0005** | 执行隔离与设备授权继续生效；不得绕过 |
| **0031 协作资源** | 成果只暴露 resource_id/version |
| **task-board / background-tasks** | 并存；S0 不合并权威模型（DEC-0043-15） |
| **G4 P2P** | 无关；文件直连另约 |
| **G5 ACP/token** | 可复用本规格状态枚举作后续契约；本 PR 不实现 |
| **0039 macOS** | **搁置**；勿派 |

### Evolution（非 S0）

- work-item ↔ task-board 双向链接 UI  
- 可重放账户事件游标（与 0041 Evolution 统筹）  
- 子工作项树 / 多 attempt 并行  
- 百分比进度（无观测依据则禁止伪造）  

### 风险

| 风险 | 缓解 |
| --- | --- |
| 进度查询误走 steer | DEC-0043-06；AC-0043-02 断言无 worker user / 无 cancel |
| 与 task-board 概念混淆 | 独立路由与表；文档写清 |
| 取消后外部 Job 仍跑 | DEC-0043-09；UI 显示 cancel_requested |
| 恢复误重放 | DEC-0043-13；unknown + AC-0043-06 |
| 迁移号冲突 | 036 已核对 tip max=35；合并前再 fetch |

---

## 9. Ready 检查

- [x] 第二实现者无需猜测可实现观察行为（HTTP+JSON+事件已冻）  
- [x] 复用映射已写；新表理由充分  
- [x] 进度只读 vs 0033 边界硬性  
- [x] 失败 / 取消 / 删除 origin / 禁用 / 未知恢复已写  
- [x] 无阻塞 OQ（容量具体数字为实现细节，DEC-0043-11 给默认）  
- [x] **可立刻派 Coder**（基线已含 0041 helper；建议分支 `feature/0043-chat-independent-work-items`）  

**Contract: Ready · Rev 2026-11-07.2**
