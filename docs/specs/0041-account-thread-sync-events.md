# 0041 账户内会话变更事件与运行快照（G1）

- Revision: **2026-11-07.1**（Asia/Shanghai）｜Contract: **Ready**
- Owner: Octopus 架构师 → 总管派 Coder｜权威源：本文件
- Decision basis: 用户授权开发；交接 `docs/handoffs/2026-11-07-grok/`（README / design-report / 01-chat-sync-events）；Codex 负责 dashboard UI，本规格只冻结**后端/协议**
- Code baseline: `CkEFFAF/Octopus-public` **`origin/main` @ `dee39636ebeac44ed179bd27929340c3a5ecdceb`**（`dee3963 Merge pull request #63`；handoff 记 dee39636 / PR#63，本轮已重新 `git fetch` 核对）
- Delivery: **compact SDD**（build-adaptively）｜Verification: **strict**（跨设备同步 / 账号隔离）｜Continuity: collaborative（GPT 交接）
- 编号说明：tip 已有 `0039-device-acp-runners`、`0040-scheduled-report-options`；本规格取 **0041**（G1）。G2 见 **0042**。
- 约束：**只写 docs/specs**；不改产品代码、不改 `dashboard/`、不碰 `octopus1/chat-task-work` 工作树；不 commit / push / PR / 部署；不派 Coder；不替换 Harness；不做全量重构 PR；密钥不明文进日志

---

## 0. 给 Coder / GPT 的阅读顺序

1. §1 Goal / Non-goals / 模块边界  
2. §2 现状（相对 tip）与缺口  
3. §3 DEC（已拍板）  
4. §4 事件 / subscribe 快照契约（JSON）  
5. §5 REQ / AC  
6. §6 迁移 / 错误码 / 授权  
7. §7 Coder 实现指南与测试命令  
8. §8 与 0042 / G3 关系  

---

## 1. Goal / Non-goals / 模块边界

### Goal

同一账号下，工位上创建/运行会话时，笔记本等其它已登录客户端能收到**账户内会话变更提示**；断线重连后通过**重读列表 + history + subscribe 快照**补齐结果与终态，而不是只依赖事后 token 流。

### In scope（S0）

- 在创建会话、接受输入、开始运行、进入需用户处理（attention）、结束运行（completed / failed / cancelled）时，向该 thread **owner** 的通知连接发送 `thread.changed`
- 统一 infra helper（供 **0042 / G3** 调用），禁止各处手写同名事件
- 允许合并高频 `running` 进度提示；**禁止**把 token / 未授权正文 / 凭据扇出到账户通知通道
- 扩展 chat WS `subscribe` 返回的运行快照（复用/扩展现有 `turn_status` + `runtime`，不开第二套矛盾状态源）
- 事件发出前，相关历史/状态须已可从既有 HTTP API 读取
- 单元 + 集成测试；OpenAPI / 交接 JSON 契约

### Non-goals

- **不**修改 `dashboard/`（空闲重连、前台对账、列表刷新由 Codex）
- **不**要求首版重放全部 token；**不**把事件当作唯一真相
- **不**新增可重放游标表（→ Evolution；宣称可靠同步不得依赖未实现游标）
- **不**改变历史列表的账号/专家权限；不按当前设备隐藏其它设备会话
- **不**替换 Harness；不改 G3 独立工作项模型（仅预留 helper）
- **不**部署云端

### 模块边界

| 层 | 职责 | 禁止 |
| --- | --- | --- |
| `infra/gateway/`（helper + 调用点） | 组装并 `push_to_user`；生命周期挂钩 | 路由里拼事件 JSON；广播 token |
| `infra/gateway/ws/ws_hub.py` | 已有 `push_to_user` / `push_to_thread` | 为 token 复用 `push_to_user` |
| `api/routers/chat/notify_ws.py` | `/api/notifications/ws` 承载账户帧 | 在 notify 通道推 token |
| `api/routers/chat/ws.py` | `subscribe` → 快照 | 另开平行 status 协议 |
| HTTP history / threads | 权威数据 | 事件替代 REST |

---

## 2. 现状（tip `dee39636`）与缺口

核对 worktree：`/workspace/octopus-g1g2` @ `dee39636`。

| 能力 | tip 现状 | 缺口 |
| --- | --- | --- |
| Thread 流式 | `ws_channel` → `hub.push_to_thread`（token/done/error） | 其它设备未 subscribe 该 thread 则无感知 |
| 账户通知通道 | `chat/notify_ws.py` + `hub.register(..., user_id=)` + `push_to_user` | 仅有 `dashboard_push`（cron/关怀 toast），**无** `thread.changed` |
| 生命周期钩子 | `mark_turn_active` / `mark_turn_idle`；创建 thread 在 registry | **无**统一账户变更发射点 |
| subscribe 快照 | `turn_status`：`active` + `runtime=steering_status` + `input_controls` | 缺稳定 `run_id` / `phase` / 安全 `active_tools` / `last_event_at` / 成果资源引用（在既有字段上扩展） |
| 历史权威 | `HistoryArchive` / history API | 保持；事件只提示 |
| 跨账号 | thread 行含 `user_id` | 发射须按 **owner_user_id**，不得推给其它账号 |

handoff 路径笔误：材料写 `api/routers/notify_ws.py`；tip 实为 **`src/octop/api/routers/chat/notify_ws.py`**。

---

## 3. DEC（拍板）

| ID | 决议 | 状态 |
| --- | --- | --- |
| **DEC-0041-01** | 账户提示事件类型冻结为 **`thread.changed`**（`type` 字段）；通道 = 现有 **`/api/notifications/ws`**（`push_to_user`） | resolved |
| **DEC-0041-02** | 单一 helper：建议 `Gateway.emit_thread_changed(...)` 或 `infra/gateway/thread_events.py::emit_thread_changed`，由 Gateway 注入 hub；**G2/G3 必须调用它**，禁止复制 JSON | resolved |
| **DEC-0041-03** | 权威数据 = 持久化 + 授权 HTTP（threads/history/runtime）；WS 事件 = 提示。断线恢复 **不**依赖事件全送达 | resolved |
| **DEC-0041-04** | **禁止**经账户通道广播 token、凭据、私有工具参数、未授权消息正文。`thread.changed` 载荷仅不透明 id + reason + 时间 | resolved |
| **DEC-0041-05** | `reason` 枚举：`created` \| `input` \| `running` \| `attention` \| `completed` \| `failed` \| `cancelled`。`running` 可合并（同 thread 最短间隔 ≥ 1s 或阶段变化才发）；终态与 `created`/`attention` **不可丢** | resolved |
| **DEC-0041-06** | 发射前序：先完成可使 API 读到的持久化（thread 行 / history 投影 / turn 标记），再 `push_to_user`。失败只记日志，不回滚业务 | resolved |
| **DEC-0041-07** | 收件人 = thread **`owner_user_id`**（会话行 `user_id`）。共享专家按**对话 owner**隔离；用户乙不得收到用户甲的提示 | resolved |
| **DEC-0041-08** | subscribe 快照：扩展现有 `turn_status`（及 `runtime` 对象），**不开**第二套状态源。S0 字段见 §4.2；取不到则 `null`/省略，不得伪造百分比 | resolved |
| **DEC-0041-09** | 删除会话或撤销访问后：停止对该 thread 发 `thread.changed`；subscribe 继续 404/not found；通知不得泄露资源 id | resolved |
| **DEC-0041-10** | S0 **无新表 / 无新迁移**。可重放游标 → Evolution，不得宣称已实现 | resolved |
| **DEC-0041-11** | `event_id`：稳定 ULID（或 `tc:{thread_id}:{reason}:{bucket}` 对合并后的 running）。客户端可去重；不以正文哈希去重 | resolved |
| **DEC-0041-12** | 旧投影回填未完成：**仍可** subscribe；空消息列表 ≠ 工作已结束（以 `active`/runtime/终态为准） | resolved |

---

## 4. 契约

### 4.1 `thread.changed`（账户通知 WS）

方向：Server → Client（`/api/notifications/ws`，鉴权同现网 `?token=`）。

```json
{
  "type": "thread.changed",
  "event_id": "01JB...",
  "agent_id": "opaque-agent-id",
  "thread_id": "opaque-thread-id",
  "run_id": "opaque-run-id-or-null",
  "reason": "created",
  "updated_at": 1794028800,
  "schema_version": 1
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `type` | string | 恒为 `thread.changed` |
| `event_id` | string | 去重用；同一次逻辑变更稳定 |
| `agent_id` / `thread_id` | string | 不透明 id |
| `run_id` | string \| null | 无运行时 null |
| `reason` | string | DEC-0041-05 枚举 |
| `updated_at` | number | Unix 秒（与项目现有 ts 惯例一致；若代码统一用 ms 则在实现指南注明并保持全局一致） |
| `schema_version` | int | S0 = **1**；破坏性变更递增 |

**不出现**：token 文本、工具 args、API key、完整消息 body、其它用户 id。

### 4.2 `subscribe` → `turn_status` 快照（chat WS）

现有帧扩展（兼容：旧客户端忽略未知字段）：

```json
{
  "type": "turn_status",
  "thread_id": "opaque-thread-id",
  "active": true,
  "runtime": {
    "phase": "running",
    "run_id": "opaque-run-id-or-null",
    "active_tools": ["web_search"],
    "last_event_at": 1794028800
  },
  "input_controls": true,
  "artifacts": [
    {"resource_id": "res_...", "version": 1}
  ],
  "schema_version": 1
}
```

| 规则 | 说明 |
| --- | --- |
| `active_tools` | **仅**安全工具名；无参数 |
| `artifacts` | 仅已授权 `resource_id`/`version`；无本地绝对路径 |
| 获取快照 | **不**取消工具、**不**改写 worker 消息历史 |
| `runtime` | 优先扩展 `steering_status` / execution 已观测字段；缺失则 null |

可选：独立 `GET /api/.../threads/{id}/runtime` **仅当** subscribe 扩展不足以支撑 Codex；若新增，须同构 JSON 且同授权。S0 默认**不强制**新 GET。

### 4.3 调用点（最小集合）

| 时机 | reason | 建议挂钩 |
| --- | --- | --- |
| 新建 dashboard thread | `created` | thread 创建成功且可 list 之后 |
| 用户 turn 入队/开始处理 | `input` | WS/HTTP 入站接受后 |
| 标记 turn active / 阶段变化 | `running` | `mark_turn_active` + 合并策略 |
| HITL / 需用户处理 | `attention` | 现有 ask/interrupt 出口 |
| turn 成功结束 | `completed` | `mark_turn_idle` 且成功路径 |
| 错误结束 | `failed` | 错误帧路径 |
| 取消 | `cancelled` | cancel_stream / 用户取消 |

---

## 5. REQ / AC

| ID | 需求 |
| --- | --- |
| **REQ-0041-01** | Owner 的所有通知 WS 连接收到该账号 thread 的 `thread.changed` |
| **REQ-0041-02** | 非 owner 永不收到 |
| **REQ-0041-03** | 账户通道无 token |
| **REQ-0041-04** | 终态后重读 history 可得完整结果；`active=false` 且 runtime 终态 |
| **REQ-0041-05** | 中途 subscribe 得当前安全快照；不取消工具、不改历史 |
| **REQ-0041-06** | 投影回填中仍可 subscribe |
| **REQ-0041-07** | 删除/撤销后无新事件、无资源泄露 |
| **REQ-0041-08** | 既有「不串流 / 双订阅 / 断线恢复」测试保持通过 |

| ID | 验收 |
| --- | --- |
| **AC-0041-01** | 双客户端同账号；禁元数据生成；A 创建/运行，B 的 notifications WS 收到对应 `thread.changed` |
| **AC-0041-02** | 同场景用户乙连接收不到甲的事件 |
| **AC-0041-03** | B 离线期间 A 完成；B 重连后 GET history 完整且 subscribe `active=false` |
| **AC-0041-04** | 运行中 subscribe：可见 phase/tools（若有）；工具仍在跑；history 未被快照调用改写 |
| **AC-0041-05** | 模拟投影未完成：subscribe 成功；不得因 messages=[] 断言已结束 |
| **AC-0041-06** | 回归：既有 thread WS 不串流、双订阅、断线恢复 |
| **AC-0041-07** | 删除 thread 后无新 `thread.changed`；事件与快照无未授权 resource |

---

## 6. 授权 / 错误码 / 迁移

### 授权

- 通知 WS：现有 `resolve_user_from_token`；帧只推 `user.id == thread.user_id`
- chat subscribe：保持 tip 校验 `row.agent_id` + `row.user_id == user.id`（及后续 share 规则若已存在则复用，**不**借 G1 放宽）

### 错误语义（subscribe）

| 情况 | 行为 |
| --- | --- |
| 缺 `thread_id` | `{type:error, message:"subscribe requires thread_id"}`（保持） |
| 无权限/不存在 | `{type:error, message:"thread ... not found"}`（保持；不区分存在性过度泄露时维持现状话术） |
| 服务器未就绪 | 连接级 close 1011（notify 已有） |

账户事件发送失败：不向业务层抛；不重试风暴（最多 best-effort）。

### 迁移

**无。** Schema version 不变。

---

## 7. Coder 实现指南

### 分支

- 建议：`feature/0041-account-thread-sync-events`
- 从 **最新 `origin/main`** 开独立 worktree（如 `octopus-g1g2`）；**禁止**在 `D:\Agent_Workspace\octopus1\chat-task-work` / `hotfix/chat-task-continuity` 改后端
- **禁止**改 `dashboard/`、`src/octop/dashboard/`

### 可写路径（建议）

- `src/octop/infra/gateway/thread_events.py`（新建）或 `gateway.py` 内聚方法
- `src/octop/infra/gateway/ws/ws_channel.py`（生命周期挂钩）
- `src/octop/infra/gateway/threads.py` / 创建 thread 出口（`created`）
- `src/octop/api/routers/chat/ws.py`（快照字段）
- `src/octop/api/openapi_meta.py`（文档）
- `tests/unit/gateway/`、`tests/integration/test_notifications_ws.py`（扩展）
- **只读参考**：`ws_hub.py`、`notify_ws.py`、`execution/events.py`、`input_queue.py`

### 实现要点

1. Helper 签名示例：`async def emit_thread_changed(*, owner_user_id: int, agent_id: str, thread_id: str, reason: str, run_id: str | None = None, updated_at: float | None = None) -> None`
2. 内部：校验 reason → 生成 `event_id` → `hub.push_to_user(owner_user_id, frame)`
3. running 合并：进程内 `(thread_id -> last_emit_monotonic)`；终态旁路
4. 快照：在 `steering_status` 之上填充可得字段；工具名白名单/剥离 args
5. 密钥：测试与日志禁止明文 token

### 测试命令

```bash
uv run pytest tests/integration/test_notifications_ws.py tests/unit/gateway/test_dashboard_ws.py -q
uv run pytest tests/unit/gateway/ -q -k "thread_changed or notify or subscribe"
# 新增后：
# uv run pytest tests/unit/gateway/test_thread_changed_0041.py tests/integration/test_thread_changed_0041.py -q
make all   # 须绿；CI Linux + Windows
```

### 交付物（Coder → Codex）

- 冻结 JSON 示例（本 §4）+ OpenAPI 摘要  
- 实际测试命令与结果  
- 未实现项（游标等）明确列出  

---

## 8. 与其它规格

| 规格 | 关系 |
| --- | --- |
| **0042（G2）** | 提醒/关怀投递后调用本 helper；扩展 `dashboard_push` 稳定 id；**不**另造 `thread.changed` |
| **G3** | 进度提示复用 helper；工作项模型另规格 |
| **0018** | 自提醒产品语义；投递目标漂移由 0042 修 |
| **0002** | UI 信息层级；本规格不改 dashboard |
| **0038** | 跨账号隔离；本规格发射须遵守 owner 边界 |
| **0039 macOS** | **无关且搁置**；勿派 Coder |

### Evolution

- 可重放 cursor（per-owner、保留期、过期全量对账）
- 多 worker 下 running 合并的分布式限流
- 独立 GET runtime（若 Codex 需要）

### 风险

| 风险 | 缓解 |
| --- | --- |
| 事件早于持久化 | DEC-0041-06 顺序；AC 重读 history |
| 通知风暴 | running 合并；终态必达 |
| 误推其它用户 | 单测 + AC-0041-02 |
| 与 0042 并行冲突 | 0041 先合 helper；0042 rebase；或同分支两 PR 时 0041 文件所有权归 G1 |

---

## 9. Ready 检查

- [x] 第二实现者无需猜测可实现观察行为  
- [x] 失败/权限/删除边界已写  
- [x] 无阻塞 OQ（游标显式延期）  
- [x] 可立刻派 Coder（可与 0042 **并行开分支**，但 0042 合并前须能调用本 helper——见 0042 依赖说明）  

**Contract: Ready · Rev 2026-11-07.1**
