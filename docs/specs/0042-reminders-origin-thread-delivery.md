# 0042 提醒 origin_thread 固定、关怀持久化与投递幂等（G2）

- Revision: **2026-11-07.1**（Asia/Shanghai）｜Contract: **Ready**
- Owner: Octopus 架构师 → 总管派 Coder｜权威源：本文件
- Decision basis: 用户授权开发；交接 `docs/handoffs/2026-11-07-grok/`（02-reminders-delivery + design-report）；Codex 负责通知呈现/会话跳转 UI
- Code baseline: `CkEFFAF/Octopus-public` **`origin/main` @ `dee39636ebeac44ed179bd27929340c3a5ecdceb`**（已重新 `git fetch` 核对）
- Delivery: **compact SDD**（build-adaptively）｜Verification: **strict**（路由漂移 / 幂等 / 跨会话）｜Continuity: collaborative（GPT 交接）
- 编号说明：接 0041（G1）；本规格 **0042**（G2）
- 依赖：**功能依赖 0041 helper**（`emit_thread_changed` / 账户事件信封）。可并行开发，但 G2 合入须能调用 G1 API（同分支串联或先合 0041 再 rebase）
- 约束：只写 docs/specs；不改 `dashboard/`；不碰 `chat-task-work`；不 commit/push/PR/部署；不派 Coder；不替换 Harness；不改定时报告 `report-{cron_id}` 隔离设计；密钥不明文进日志

---

## 0. 给 Coder / GPT 的阅读顺序

1. §1 Goal / Non-goals  
2. §2 已证实错误路径（tip）  
3. §3 DEC  
4. §4 数据 / 投递 / 通知契约  
5. §5 REQ / AC  
6. §6 迁移与旧数据  
7. §7 Coder 指南与测试  
8. §8 与 0041 / 0018 / 0040 边界  

---

## 1. Goal / Non-goals

### Goal

1. 在会话 A 创建的自提醒，执行/加锁/写 history/推正文/发通知**全程固定**到创建时的 thread，不随 dashboard `session_key` 重绑漂到 B。  
2. 主动关怀正文先进入 Harness **canonical history**，再推送与发 G1 事件；刷新后仍在。  
3. 投递幂等：同一投递事件重试不重复写正文；两次合法提醒各一条。  
4. 账号级 toast ≠ 正文广播；通知带稳定 id，供 Codex 去重并跳到正确会话。

### In scope（S0）

- `schedule_self_check` / self-reminder 创建时写入不可变 **`origin_thread_id`**（+ 已有 `agent_id` / `user_id`）
- `CronDeliveryService` / job 锁与 history 写入改用固定目标 thread（dashboard 路径）
- 主动关怀：固定目标策略（§3）；`aappend_messages` + 投影 + push + G1 事件
- `dashboard_push` 扩展稳定 `event_id` / `delivery_id` / `origin_thread` / `created_at` / `source_kind`
- 复用 **0041** `thread.changed`，不另造同名事件
- 旧提醒回填策略；单元 + 集成（含 history 重读，不只 mock Gateway）

### Non-goals

- 不修改定时报告独立 `report-{cron_id}` 会话设计（0040 / 现网）
- 不把已隔离报告改回共享 session
- 不禁止账号通知（错误修复不是关 toast）
- 不用消息文本哈希做永久去重
- 不改 IM 渠道路由语义（channel/subject 保持）；本规格修 **Dashboard** 目标漂移
- 不改 dashboard UI；不部署云端

---

## 2. 已证实错误路径（tip `dee39636`）

| 现象 | 证据 | 判断 |
| --- | --- | --- |
| Dashboard `session_key` 按 user/agent，显式发 thread 时 **rebind** | `ThreadRegistry.dashboard_key`；`rebind()` | 键不等于固定 thread |
| self_check 只存 `session_key`，执行时再解析当前绑定 | `cron/tools.py` `schedule_self_check` → `CronCreateSpec.session_key`；`delivery.command_from_row` 用 `row.session_key` | A 创建后用户切到 B → 可能写入 B |
| 关怀每次挑近会话 | `proactive/scheduler.py` `list_by_agent(..., limit=10)` 偏好 IM 否则 `sessions[0]` | 目标不稳定 |
| 关怀可能刷新消失 | `ProactiveCareService` → `push_text_from_session`；`push_session_text` 走通道 push + `_bump_virtual_session`（标题/未读），**无** `aappend_messages` | 缺 canonical 持久化 |
| cron text 投递已有 canonical 模式可借鉴 | `delivery._deliver_text` 使用 `harness.aappend_messages` + `cron:{delivery_id}:*` | 关怀应对齐；self-reminder agent 路径须锁在 origin thread |
| 通知 | `notify_dashboard_push`：`type=dashboard_push`，无稳定 delivery_id | Codex 难去重/跳转 |

---

## 3. DEC（拍板）

| ID | 决议 | 状态 |
| --- | --- | --- |
| **DEC-0042-01** | 创建自提醒时记录不可变 **`origin_thread_id`**、`agent_id`、`owner_user_id`（owner = 行内 `user_id`）。执行、锁、history、正文推送、通知**全部**用该目标 | resolved |
| **DEC-0042-02** | Dashboard 锁键 = `thread:{origin_thread_id}`（与现 `run_in_session` dashboard 分支一致），**禁止**因 rebind 用 B 的 thread 持锁却写 A（或相反） | resolved |
| **DEC-0042-03** | 目标 thread 已删除 / 移交 / 当前用户不可访问 → **明确失败**（attempt 失败态 + 可观测错误）；**禁止**投递到「当前会话」或最近会话 | resolved |
| **DEC-0042-04** | 旧提醒缺 `origin_thread_id`：仅当能从已有记录**证明唯一**目标时回填；否则标记 `needs_retarget=true`（meta），**禁止**静默绑最近会话；UI/工具可提示用户重选（Codex 另做） | resolved |
| **DEC-0042-05** | **关怀目标（可逆默认）**：① 若配置了已授权固定 `thread_id` 则用之；② 否则使用稳定专用关怀会话，键建议 `care:{agent_id}:{owner_user_id}`（首次明确创建后复用）；③ **禁止** `list_by_agent(limit=10)` 自动挑选。配置存储：agent/user 设置或 proactive 配置现有入口（实现选一处写清，禁止散落魔法） | resolved |
| **DEC-0042-06** | 关怀正文：先 `harness.aappend_messages`（稳定 message id）→ 更新投影 → 再 `push`/`notify` → 再 **0041** `emit_thread_changed(reason=input|completed)`。持久化失败 → **不得**宣称已交付 | resolved |
| **DEC-0042-07** | 幂等：每次触发有稳定 **`delivery_id`**（优先复用 `cron_attempts.attempt_id`；无 attempt 则 ULID 并持久化）。canonical 消息 id = `care:{delivery_id}:assistant` 或 `cron:{delivery_id}:*` 既有模式。重试同一 `delivery_id` 不重复 append（依赖 harness/投影去重或先查） | resolved |
| **DEC-0042-08** | 渠道回执丢失：状态区分 `persisted` / `pushed` / `notify_sent` / `channel_unknown`；已持久化则**不**因 push 失败而重复 append；channel_unknown **不**无限重发 | resolved |
| **DEC-0042-09** | 通知：复用 0041 账户事件；`dashboard_push` **扩展**字段（§4.3），保持 `type=dashboard_push` 兼容。**禁止**用正文哈希永久去重 | resolved |
| **DEC-0042-10** | 持久化位置：S0 将 `origin_thread_id` 写入 **`cron_jobs.meta`**（键名冻结），避免与 0040/未发布迁移抢号；若 Coder 评估 meta 不足（查询/约束），可另提 **036** 成对 SQLite+PG 列迁移——须总管确认无编号冲突后再加 | resolved |
| **DEC-0042-11** | 不替换 Harness；不直接改 checkpoint SQL 绕过 `aappend_messages` | resolved |
| **DEC-0042-12** | IM 投递路径保持原 channel/subject；本规格回归不得破坏 IM | resolved |

---

## 4. 契约

### 4.1 `cron_jobs.meta` 键（自提醒）

```json
{
  "self_reminder": true,
  "origin_thread_id": "opaque-thread-id",
  "origin_bound_at": 1794028800,
  "needs_retarget": false
}
```

| 键 | 规则 |
| --- | --- |
| `origin_thread_id` | 创建时写入；之后**只读**；更新 API/工具不得改 |
| `needs_retarget` | 旧数据无法证明唯一目标时为 true；为 true 时调度器**跳过投递**并记失败/告警 |
| 现有 self_reminder 字段 | 保留（`self_reminder.py` encode/decode） |

创建时：`session_key` 仍可保存（兼容），但**投递解析顺序** = `origin_thread_id` → 校验 owner/agent → 取该 thread 对应 session；**禁止**只用 `dashboard_key` 当活绑定。

### 4.2 投递状态（逻辑）

| 状态 | 含义 |
| --- | --- |
| `triggered` | 调度触发 |
| `running` | 持锁执行中 |
| `persisted` | canonical append + 投影成功 |
| `pushed` | 通道 push 尝试完成 |
| `notify_sent` | dashboard_push / thread.changed 已 best-effort |
| `succeeded` | 业务成功（至少 persisted） |
| `failed` | 明确失败（含目标不可用） |
| `channel_unknown` | 渠道无回执；不自动无限重试 |

落库：优先写在现有 `cron_attempts`（status/public_error/result_excerpt）；不足则 meta 补充，避免无必要新表。

### 4.3 扩展 `dashboard_push`

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

`source_kind`：`self_reminder` \| `proactive_care` \| `cron` \| …

同时调用 0041：

```json
{
  "type": "thread.changed",
  "reason": "input",
  "thread_id": "origin-thread-id",
  "agent_id": "...",
  "run_id": null,
  "event_id": "...",
  "updated_at": 1794028800,
  "schema_version": 1
}
```

（`reason` 亦可 `completed`，按是否开启 agent 回合选择；同一 delivery 勿刷屏。）

### 4.4 错误码 / 对外语义

| 代码或公开错误 | 何时 |
| --- | --- |
| `origin_thread_missing` | 无 origin 且 needs_retarget |
| `origin_thread_unavailable` | 删除/无权限/agent 不匹配 |
| `persist_failed` | aappend/投影失败（未交付） |
| `duplicate_delivery` | 同 delivery_id 已 persisted（返回成功幂等） |

日志：只记 id，不记密钥；正文可截断。

---

## 5. REQ / AC

| ID | 需求 |
| --- | --- |
| **REQ-0042-01** | 自提醒创建绑定不可变 origin_thread |
| **REQ-0042-02** | 执行全程固定该 thread（锁/history/push/notify） |
| **REQ-0042-03** | 目标不可用 → 失败，不漂到当前会话 |
| **REQ-0042-04** | 旧数据安全回填或 needs_retarget |
| **REQ-0042-05** | 关怀固定目标；禁止最近 10 条挑选 |
| **REQ-0042-06** | 关怀先持久化再通知；失败不伪造成功 |
| **REQ-0042-07** | 同 delivery_id 重试不双写正文 |
| **REQ-0042-08** | 通知带稳定 id；复用 0041 事件 |
| **REQ-0042-09** | IM 与定时报告既有测试继续通过 |

| ID | 验收 |
| --- | --- |
| **AC-0042-01** | 在 A 创建提醒；dashboard key 重绑到 B；触发后**仅 A** history 增加正文 |
| **AC-0042-02** | 等待 A 锁时改绑 B：仍在 A 执行；不得用 A 的锁写 B |
| **AC-0042-03** | 同 delivery 重复执行 → 仅一条 canonical；两次不同提醒 → 两条 |
| **AC-0042-04** | 推送后重读 history 存在；进程重启后仍在 |
| **AC-0042-05** | 删除目标后不投其它聊天、不泄露其它用户 |
| **AC-0042-06** | IM 渠道路由回归通过 |
| **AC-0042-07** | 定时报告复用/新建会话既有测试通过（0040 相关不回归） |
| **AC-0042-08** | 关怀：固定/专用 thread 收正文；刷新/重读 history 可见；notifications 含扩展 dashboard_push + thread.changed |

---

## 6. 迁移与旧数据

### S0 默认

- **无强制 DDL**（DEC-0042-10 meta 方案）
- 启动或首次投递前：对 `kind=self_reminder`（或 meta.self_reminder）缺 `origin_thread_id` 的行：
  1. 若 `session_key` → session 行存在且 `thread_id` 唯一且 `user_id`/`agent_id` 匹配 → 回填 meta
  2. 否则 `needs_retarget=true`，跳过投递

### 可选 036（仅当 meta 不够）

须总管确认编号未占用后：

- `036_reminder_origin_thread.sql` + `.pg.sql`
- `ALTER TABLE cron_jobs ADD COLUMN origin_thread_id TEXT;`（及必要索引）
- 双文件成对；**禁止**改已上线迁移

关怀专用会话：复用 `ThreadRegistry` 创建 API；不删用户历史。

---

## 7. Coder 实现指南

### 分支

- 建议：`feature/0042-reminders-origin-thread-delivery`
- 或与 0041 同仓串联：`feature/0041-0042-chat-sync-and-reminders` 两 PR（先 0041 后 0042）
- 基线：最新 `origin/main`；**禁止** `chat-task-work` 树；**禁止**改 `dashboard/`

### 可写路径

- `src/octop/infra/cron/tools.py`（创建时写 origin）
- `src/octop/infra/cron/self_reminder.py`（meta 编解码键）
- `src/octop/infra/cron/delivery.py` / `job.py` / `manager.py`（解析与锁）
- `src/octop/infra/gateway/gateway.py`（`notify_dashboard_push` 扩展；可选 `persist_and_push_text`）
- `src/octop/infra/proactive/scheduler.py` / `service.py`（目标 + aappend）
- `src/octop/infra/db/repos/cron.py`（若需辅助读写 meta）
- `tests/unit/cron/test_self_reminder_0018.py`、`test_cron_delivery.py`、新建 `test_reminders_origin_0042.py`
- `tests/unit/proactive/`（新建关怀持久化测试）
- `tests/integration/test_notifications_ws.py`（扩展字段）
- **调用** 0041 helper（只读依赖其模块）

### 禁止

- 改 `dashboard/`  
- 用「当前打开页面」决定正文写入目标  
- 直接改 checkpoint SQL  
- 文本哈希永久去重  
- 把 report 会话改回共享  

### 测试命令

```bash
uv run pytest tests/unit/cron/test_self_reminder_0018.py tests/unit/cron/test_cron_delivery.py -q
uv run pytest tests/unit/cron/ -q -k "origin or reminder or delivery or care"
uv run pytest tests/unit/gateway/test_gateway_push.py tests/integration/test_notifications_ws.py -q
# 新增 AC 文件后一并跑
make all
```

必含：**真实 DB + history 重读**（禁止仅 mock Gateway 宣称 AC-0042-04 通过）。

### 交付记录须写清

- 旧数据处理结果（回填数 / needs_retarget 数）  
- 幂等键 = 何字段  
- 事务边界（append 与 attempt 状态顺序）  
- 「已 persisted 但 push 丢失」的处理（DEC-0042-08）  
- 给 Codex 的 JSON 示例  

---

## 8. 与其它规格

| 规格 | 关系 |
| --- | --- |
| **0041 G1** | 事件信封与 helper；本规格调用方 |
| **0018** | 自提醒产品能力；本规格修路由/持久化/幂等缺陷 |
| **0040** | 定时报告选项；**不**改 report 隔离；回归保护 |
| **G3** | 后续独立工作项；本规格不预演 task_id 模型 |
| **0039 macOS** | 搁置；无关 |

### 风险

| 风险 | 缓解 |
| --- | --- |
| 与 0041 并行接口漂移 | 冻结 §4；0042 以 0041 Ready 契约为准 |
| meta 被其它特性覆盖 | 深合并 meta；单测保护键 |
| 关怀专用会话增多 | 每 owner+agent 至多一个 care thread |
| 误伤报告投递 | AC-0042-07；代码路径按 kind 分流 |

---

## 9. Ready 检查

- [x] 观察行为与失败态可测  
- [x] 与 0041 边界清晰  
- [x] 旧数据策略已定  
- [x] 可派 Coder（**建议 0041 先合或同 PR 先提交 helper**；0042 单独分支须 rebase 0041）  

**Contract: Ready · Rev 2026-11-07.1**
