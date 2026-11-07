# Codex UI 交接：G3(0043) work_items + task.changed（已合 main）

- 日期：2026-11-07（Asia/Shanghai）
- 作者：Octopus Coder（后端实现方）→ Codex（dashboard UI）
- **main tip（含 #67 squash）**: `21c8e32f09c929d7897446c72d20aa72e96a4451`
- 规格权威：`docs/specs/0043-chat-independent-work-items.md`
- **禁止**：改本仓库 `dashboard/` / `src/octop/dashboard/`；改后端 emit 契约字段名；把 `task.changed` 当唯一真相；用进度 GET 去 steer / cancel worker

---

## 0. 一句话

后端已提供独立工作项 HTTP API（`/api/work-items*`）与账户通知 WS 事件 `task.changed`。  
Codex 负责：列表/详情/进度展示；听 `task.changed` → 刷新；输入追加与取消；**权威状态以 HTTP detail/events 为准**。

与 G1/G2 同通道：`WS /api/notifications/ws`（另有 `thread.changed` / `dashboard_push`）。勿混进 chat token 流。

---

## 1. 通道与鉴权

| 通道 | Path | Auth | 用途 |
| --- | --- | --- | --- |
| 账户通知 | `WS /api/notifications/ws?token=` | 现网 JWT query | `task.changed`（及既有 thread/dashboard 事件） |
| 工作项 HTTP | `/api/work-items*` | Bearer/Cookie 同现网 | **权威源**：创建/列表/详情/进度/事件/输入/取消 |

事件只提示「去拉」；**不得**用事件正文替代 detail/events。

---

## 2. HTTP 契约（`schema_version=1`）

### 2.1 创建

`POST /api/work-items`

```json
{
  "command_id": "client-idempotency-key",
  "agent_id": "opaque-agent-id",
  "origin_thread_id": "opaque-thread-id",
  "title": "短标题",
  "instructions": "任务说明",
  "execution": {"target_kind": "device", "device_id": null, "working_dir": null},
  "resources": [{"resource_id": "res_...", "version": 1}],
  "schema_version": 1
}
```

- `command_id`：同一 owner 下幂等；冲突语义见错误码 `WORK_ITEM_COMMAND_CONFLICT` / `WORK_ITEM_RUN_CONFLICT`
- 调用者须对 `agent_id` 有访问权（与现网 agent 访问一致）

### 2.2 列表 / 详情 / 进度 / 事件

| Method | Path | 说明 |
| --- | --- | --- |
| GET | `/api/work-items?origin_thread_id=&status_group=open|all&limit=&before=` | 列表；`status_group=open` 默认 |
| GET | `/api/work-items/{task_id}` | 详情（含 instructions、execution、progress、artifacts） |
| GET | `/api/work-items/{task_id}/progress` | **只读**进度子集；**禁止**当作控制面 |
| GET | `/api/work-items/{task_id}/events?before=&limit=` | cursor 事件；权威时间线 |

### 2.3 追加输入 / 取消

`POST /api/work-items/{task_id}/inputs`

```json
{
  "command_id": "…",
  "text": "补充要求",
  "target_run_id": null,
  "target_attempt_id": null,
  "schema_version": 1
}
```

`POST /api/work-items/{task_id}/cancel`

```json
{
  "command_id": "…",
  "scope": "task",
  "attempt_id": null,
  "schema_version": 1
}
```

`scope`：`task` \| `attempt`。取消为请求语义；终态以 detail `status` / 后续 `task.changed` 为准。

---

## 3. 事件契约 `task.changed`

经 `/api/notifications/ws`（`push_to_user`）：

```json
{
  "type": "task.changed",
  "event_id": "01JB...",
  "task_id": "opaque-task-id",
  "agent_id": "opaque-agent-id",
  "origin_thread_id": "opaque-thread-or-null",
  "run_id": "opaque-run-or-null",
  "reason": "created",
  "status": "queued",
  "updated_at": 1794028800,
  "schema_version": 1
}
```

| 字段 | 说明 |
| --- | --- |
| `reason` | `created` \| `running` \| `progress` \| `waiting` \| `blocked` \| `completed` \| `failed` \| `cancelled` \| `unknown` |
| `status` | 工作项权威状态：`queued` \| `running` \| `waiting_input` \| `waiting_review` \| `blocked` \| `failed` \| `completed` \| `cancelled` \| `unknown` |
| `updated_at` | Unix **秒** |
| `event_id` | 客户端去重；`progress` 可合并（后端 ≥1s），终态 / `created` / `waiting` / `blocked` 不可丢 |

**永不出现**：完整 instructions、token、工具 args、跨用户 id、本地绝对路径。

UI 建议：

- `created` / `running` / `progress` → 刷新列表与当前详情进度
- `waiting` / `blocked` → 强提示需要用户输入或处理
- `completed` / `failed` / `cancelled` / `unknown` → 拉 detail（+ events）；清除进行中指示
- 同 `event_id` 去重；不要按正文哈希去重

---

## 4. 错误码（对 Codex 可见）

| code | HTTP | UI |
| --- | --- | --- |
| `WORK_ITEM_NOT_FOUND` | 404 | 任务不存在或无权 |
| `WORK_ITEM_FORBIDDEN` | 403 | 无权操作该任务/agent |
| `WORK_ITEM_INVALID` | 400 | schema/参数不合法 |
| `WORK_ITEM_COMMAND_CONFLICT` | 409 | 同 `command_id` 语义冲突 |
| `WORK_ITEM_RUN_CONFLICT` | 409 | 运行态冲突（如重复启动） |
| 既有 | | `FORBIDDEN` / `USER_DISABLED` / `DEVICE_OFFLINE` 等保持 |

---

## 5. Codex 该做的 UI 点

1. **工作项面板**：按 `origin_thread_id` 或账户级列表展示 open/all；状态徽章映射上表 `status`。
2. **创建入口**：从聊天发起独立任务 → `POST /work-items`；保存返回的 `task_id`。
3. **进度**：订阅 `task.changed`；打开详情时以 GET progress/detail 对账；**progress GET 只读**。
4. **等待输入**：`waiting_input` / `waiting_review` → 输入框 → `POST .../inputs`。
5. **取消**：确认后 `POST .../cancel`；在 `cancel_requested` 与终态之间显示「取消中」。
6. **与会话关系**：`origin_thread_id` 可一键跳回会话；`origin_thread_missing`（detail 字段）时勿死链。
7. **回归**：异账号隔离；旧客户端忽略新通知字段不崩；断线重连后 HTTP 对账。

---

## 6. Codex 不该动的后端

- 不要改 `emit_task_changed` / `TaskEventEmitter` 字段名或通道
- 不要用 progress GET 注入控制指令或取消
- 不要在 Octopus-public 改 `dashboard/`
- 不要把 work item 进度写进 `thread.changed` 或伪造 chat 气泡代替 detail
- 契约不够 → 开规格修订，勿私自扩字段上线

---

## 7. 验证建议（Codex 侧）

1. 创建工作项 → 收到 `task.changed` `reason=created` → 列表出现。
2. 运行中 progress 合并不刷爆；终态必达且 detail 一致。
3. 追加 input / cancel 后状态与 events 一致。
4. 异账号收不到甲的 `task.changed`。
5. 断线重连：仅靠 HTTP list/detail 可恢复，不依赖事件补齐。

---

## 8. 相关 PR / tip

| 项 | 值 |
| --- | --- |
| 0043 PR | #67 → squash 入 main **`21c8e32f09c929d7897446c72d20aa72e96a4451`** |
| 实现 | `src/octop/api/routers/work_items.py`、`src/octop/infra/work_items/`、`src/octop/infra/gateway/task_events.py`、迁移 `036_work_items` |
| OpenAPI 摘要 | `src/octop/api/openapi_meta.py`（work-items / task.changed 段） |
| 前序交接 | `docs/handoffs/2026-11-07-grok/codex-ui-g1-g2.md` |

未部署云端与否以总管/运维为准；本交接不授权部署。
