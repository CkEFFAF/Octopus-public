# Codex UI 交接：G1(0041) + G2(0042) 已合 main

- 日期：2026-11-07（Asia/Shanghai）
- 作者：Octopus Coder（后端实现方）→ Codex（dashboard UI）
- **main tip**: `ca771fd1e466b97bea26c433be505c6a053aa7cb`
- 规格权威：`docs/specs/0041-account-thread-sync-events.md`、`docs/specs/0042-reminders-origin-thread-delivery.md`
- **禁止**：改本仓库 `dashboard/` / `src/octop/dashboard/`；改后端 emit 契约；把 WS 事件当唯一真相

---

## 0. 一句话

后端已在账户通知 WS 推送 `thread.changed` 与扩展 `dashboard_push`；chat WS `subscribe` 返回扩展 `turn_status`。

Codex 负责：听通知 → 刷新列表/跳转会话；重连/前台对账 → **HTTP history + subscribe 快照**；提醒 toast 按 `delivery_id`/`event_id` 去重。

---

## 1. 通道与鉴权

| 通道 | Path | Auth | 用途 |
| --- | --- | --- | --- |
| 账户通知 | `WS /api/notifications/ws?token=` | 现网 JWT query | `thread.changed`、`dashboard_push` |
| 会话流 | `WS /api/agents/{agent_id}/chat/ws?token=` | 同上 | token 流 + `subscribe` → `turn_status` |
| 权威历史 | `GET /api/agents/{agent_id}/threads/{thread_id}/history` | Bearer/Cookie 同现网 | **消息正文权威源** |
| 会话列表 | `GET /api/agents/{agent_id}/threads` | 同上 | 列表/侧栏权威源 |

事件只提示「去拉」；**不得**用事件正文替代 history。

---

## 2. 事件契约（冻结 `schema_version=1`）

### 2.1 `thread.changed`（0041；G2 复用）

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

| 字段 | 说明 |
| --- | --- |
| `reason` | `created` \| `input` \| `running` \| `attention` \| `completed` \| `failed` \| `cancelled` |
| `run_id` | 无运行时 `null` |
| `updated_at` | Unix **秒** |
| `event_id` | 客户端去重；`running` 可合并，终态/`created`/`attention` 不可丢 |

**永不出现**：token 文本、工具 args、API key、完整消息 body、其它用户 id。

UI 建议：

- `created` / `input` / `running` → 刷新侧栏/列表；当前未打开该 thread 可角标
- `attention` → 强提示并支持一键打开该 `thread_id`
- `completed` / `failed` / `cancelled` → 若当前查看该会话则 **GET history** + 再 `subscribe`；否则列表态更新即可
- 同 `event_id` 去重；不要按正文哈希去重

### 2.2 扩展 `dashboard_push`（0042）

```json
{
  "type": "dashboard_push",
  "event_id": "01JB...",
  "delivery_id": "01JB...",
  "agent_id": "opaque-agent-id",
  "agent_name": "显示名",
  "thread_id": "origin-thread-id",
  "text": "摘要或正文",
  "created_at": 1794028800,
  "source_kind": "self_reminder",
  "schema_version": 1
}
```

| 字段 | 说明 |
| --- | --- |
| `delivery_id` | 投递幂等键；**toast/跳转去重优先用它**（缺省可回退 `event_id`） |
| `source_kind` | `self_reminder` \| `proactive_care` \| `cron` \| …（未知值当普通推送，勿崩） |
| `thread_id` | **固定 origin**；点击应打开该会话，不要打开「当前活绑定」会话 |
| `text` | 可展示摘要；完整正文仍以 history 为准 |

同一提醒成功时，后端还会再发一条 `thread.changed`（通常 `reason=input` 或终态）；UI 勿对同一 `delivery_id` 刷两次历史写入动画。

### 2.3 `subscribe` → `turn_status` 快照（0041）

在 chat WS 发送既有 `subscribe`；服务端回：

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
  "artifacts": [{"resource_id": "res_...", "version": 1}],
  "schema_version": 1
}
```

规则：

- 旧客户端忽略未知字段；缺字段 = `null`/省略，**禁止伪造进度百分比**
- `active_tools` 仅安全工具名；`artifacts` 仅已授权 id（无本地路径）
- **`messages=[]` ≠ 已结束**；以 `active` / `runtime.phase` / 终态 `thread.changed` 为准
- 获取快照不取消工具、不改写 history

---

## 3. 错误码（0042 投递 / 对 Codex 可见语义）

提醒/关怀投递失败时，cron attempt / job `last_error` **直接写下列代码**（非本地化长句）：

| 代码 | 何时 | UI |
| --- | --- | --- |
| `origin_thread_missing` | 无 origin 且 `needs_retarget` | 提示需重新绑定目标会话；勿静默投到当前会话 |
| `origin_thread_unavailable` | 删除/无权限/agent 不匹配 | 目标不可用；勿漂移 |
| `persist_failed` | aappend/投影失败 | 未交付；可提示稍后重试（服务端不会伪造成功） |
| `duplicate_delivery` | 同 `delivery_id` 已 persisted | **当成功幂等**；勿再插入一条气泡 |

其它 cron/stream 错误仍可能是本地化 `format_stream_error` 文案；仅 OriginThread 路径保证为上表码。

---

## 4. 幂等与权威源

| 原则 | 做法 |
| --- | --- |
| 权威消息 | 始终 `GET .../threads/{thread_id}/history`（及既有 list threads） |
| 事件 | 提示刷新；允许丢失；重连必须对账 |
| `delivery_id` | 同一 id：后端不双写 canonical；前端 toast/本地乐观气泡按 id 去重 |
| `event_id` | `thread.changed` / `dashboard_push` 帧去重 |
| 断线恢复 | 重连 notifications + 刷新 threads 列表；打开中的会话：history + subscribe；**不**假设离线期间事件会补齐 |
| 空闲/前台 | visibility / focus 时做一次轻量对账（列表 ± 当前 history），避免只靠长连接 |

后端自提醒生产路径多为 `task_type=agent`，稳定消息 id 形如 `cron:{delivery_id}:assistant`；前端无需解析该 id，但重读 history 时应看到稳定一条而非双写。

---

## 5. Codex 该做的 UI 点

1. **U4 跨设备同步**：订阅 `/api/notifications/ws`；处理 `thread.changed`；列表/角标/打开会话；空闲断线重连 + 可见时对账。
2. **U5 提醒呈现**：`dashboard_push` toast（区分 `source_kind` 文案可选）；点击 → 打开 `thread_id` 对应会话并拉 history。
3. **运行态**：进入/重连会话时 `subscribe`，用扩展 `turn_status` 显示 phase/tools；终态后再拉 history。
4. **失败友好**：若产品面展示提醒任务错误，识别上表错误码给短文案（可 i18n），不要把码当用户长文直接甩出除非现网惯例如此。
5. **回归**：同账号双客户端；异账号隔离；删会话后不再误跳；旧客户端忽略新字段不崩。

---

## 6. Codex 不该动的后端

- 不要改 `emit_thread_changed` / `ThreadEventEmitter` / `notify_dashboard_push` 字段名或通道
- 不要在账户通知通道要 token 流
- 不要新增平行 status 协议；复用 `turn_status`
- 不要改 cron origin 绑定、投递锁、meta `origin_thread_id` / `needs_retarget`
- 不要改账号隔离 / history 授权
- **不要**在 Octopus-public 里改 `dashboard/`（UI 在 Codex 自己的工作树，如既有 `octopus1/chat-task-work`）

若契约不够用：开规格修订（架构师），不要私自扩字段上线。

---

## 7. 验证建议（Codex 侧）

1. 双浏览器同账号：A 开聊，B 仅 notifications → 收到 `thread.changed`，列表更新；B 打开后 history 完整。
2. B 离线期间 A 跑完：B 重连后 history + subscribe `active=false`（或不 active），不丢结果。
3. 触发自提醒：toast 含 `delivery_id`/`source_kind`；点进 **origin** thread；重复投递不出现双气泡。
4. 异账号连接收不到甲的事件。
5. 未知 `source_kind` / 缺可选字段不白屏。

---

## 8. 相关 PR / tip

| 项 | 值 |
| --- | --- |
| 0041 PR | #64 → squash 入 main `9bbfb437…` |
| 0042 PR | #65 → squash 入 main **`ca771fd1e466b97bea26c433be505c6a053aa7cb`** |
| 实现 helper | `src/octop/infra/gateway/thread_events.py`、`Gateway.emit_thread_changed` / `notify_dashboard_push` |
| OpenAPI 摘要 | `src/octop/api/openapi_meta.py`（Streaming chat 段） |

未部署云端与否以总管/运维为准；本交接不授权部署。
