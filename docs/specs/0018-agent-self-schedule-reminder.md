# 0018 Agent 自我调度提醒（Session Self-Reminder）

- Spec ID: `0018-agent-self-schedule-reminder`
- Status: **Ready**
- Revision: `2026-10-15.1`
- Date: 2026-10-15
- Authoritative path: `docs/specs/0018-agent-self-schedule-reminder.md`
- Code baseline: `CkEFFAF/Octopus-public` @ `97fccd2b` (main)
- Relates:
  - 现有用户/专家 Cron（**相关但不等同**）：`src/octop/api/routers/cron.py`（`/agents/{id}/cron` CRUD + `run-now`）、`src/octop/infra/cron/manager.py`、`trigger.py`（`cron:` / `interval:` / `date:` / `agently:`）、`job.py`、`delivery.py`、`task_type.py`（`text`\|`agent`）、`tools.py`（`cronjob_*` LangChain tools）
  - 会话投递：`CronDeliveryService.deliver` → `gateway.run_in_session`；`ThreadRegistry` / session_key
  - 系统作业：`CronManager.schedule_system_job`（进程级，非用户 cron）
- Non-overwrite: 不替换 Cron 产品页；不改 Accepted `0004`；本回合 **只交 docs**。

---

## 0. 给 Coder / GPT 的阅读顺序

1. §1 Goal / Non-goals  
2. §2 与现有 Cron 的关系（复用点 + 差异）— **先读再写代码**  
3. §3 Tool + 唤醒语义（写死）  
4. §4 REQ / AC  
5. §5 Coder 切片 + 路径  
6. §6 风险 / §7 Evolution  

---

## 1. Goal / Non-goals

### 1.1 Goal

长任务进行中，Agent 可设置 **绝对时间点** 或 **时长** 提醒；到点 **唤醒同一会话思维链**：检查进度、向用户汇报、调整计划或继续执行。

解决的问题：

- 跑久了不知进度  
- 无持续思维链 / 时间不精准（「做 30 分钟」）  
- 卡住无自检  

### 1.2 Non-goals

- **不替代** 用户配置的 Cron 产品页（`/agents/{id}/cron` UI）。  
- 不做手机系统闹钟、不做跨 Agent 全局日历产品。  
- 不引入新的外部调度集群；不改 APScheduler 替换方案。  
- 本回合只交规格，不 commit。

### 1.3 与现有 Cron 的边界（一句话）

> Cron = 用户/专家配置的 **定时任务**（多为新 prompt 回合、产品列表可见）；**0018 = 会话内 Agent 自设闹钟**，默认绑 **当前 `session_key`**，到点注入系统唤醒消息做自检，UI 默认隐藏或折叠。

---

## 2. 与 Cron 的关系（设计落定）

### 2.1 复用

| 能力 | 复用方式 |
|------|----------|
| 触发器解析 | `build_trigger()`：`date:<ISO8601>`、`interval:<seconds>`（`src/octop/infra/cron/trigger.py`） |
| 调度器 | 同一 `CronManager` / `AsyncIOScheduler`（或其 `schedule_system_job` 旁路） |
| 会话投递锁 | `CronDeliveryService` / `gateway.run_in_session` 保证同 session 串行 |
| 工具上下文 | `_tool_ctx()` 已取 `agent_id` / `user_id` / `session_key`（`tools.py`） |

### 2.2 差异（必须实现）

| 点 | 用户 Cron | Self-reminder |
|----|-----------|---------------|
| 创建者 | 用户或 Agent 经 `cronjob_create`（产品意图） | Agent 经 **新 tool**（长任务自检意图） |
| 可见性 | Cron 列表默认展示 | `self_reminder=true` → 列表 **默认过滤**；API 可选 `include_self_reminders` |
| `fresh_thread` | 可 true | **强制 false**（保持同一思维链上下文） |
| `task_type` | text / agent | **固定 agent**（要跑自检推理）；prompt 为系统唤醒模板 |
| 生命周期 | 长期/反复 | 默认 **one-shot**（`date:`）；`interval:` 仅当 Agent 显式要求周期自检，且须设 `max_fires` 或 `until` |
| 命名 | 用户可读 name | 内部名如 `self-check:{ulid}`，可不进主 UI |

### 2.3 DEC（写死）

| ID | 决定 |
|----|------|
| **DEC-001 存储** | **复用 `cron_jobs` 表**，用 `meta.self_reminder=true`（若列不支持 JSON meta，则：新增 nullable 列 `kind` 默认 `user`，值为 `self_reminder`；**优先查** `CronJobRow` / `cron_repo.create` 是否已有 meta——baseline 上 `CronCreateSpec.meta` 存在但 **repo create 可能未落库**，Coder 须补持久化或加 `kind` 列）。 |
| **DEC-002 唤醒策略** | **注入系统消息到同一 `session_key` 并触发一轮 agent 回合**（非 pause+resume 状态机）。若会话当前 **正在 streaming/running**：将 reminder 记入 pending queue，在本轮结束后立刻 fire（或合并进下一 turn 的 system 前缀）；若 **idle**：立即 `deliver` agent 回合。 |
| **DEC-003 精度** | 调度粒度与 APScheduler 一致；`interval:` **秒级** wall-clock；「做 30 分钟」= `date:(now+30min)` 或 `interval:1800` one-shot 语义用 **`date:`**（推荐 tool 把 `in_minutes=30` 转成 `date:<ISO>`）。不承诺亚秒级。 |
| **DEC-004 卡住自检** | 到点时：会话 running → 排队唤醒；idle → 立即唤醒。唤醒 prompt **必须**要求：汇总上次进度、是否阻塞、下一步；若无工具进度钩子，至少基于 transcript 最近 N 条消息摘要。 |

---

## 3. Tool + API

### 3.1 Agent Tool（主入口）

新建 tool（建议名，二选一写进实现常量）：`schedule_self_check`（首选）或 `set_reminder`。

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `at` | string ISO8601，可选 | 绝对时间；与 `in_seconds`/`in_minutes` 互斥，**至少其一** |
| `in_seconds` | int，可选 | 正整数；wall-clock 延迟 |
| `in_minutes` | int，可选 | 正整数；内部×60 |
| `purpose` | string | 短说明（≤200 字），写入唤醒 prompt |
| `repeat_every_seconds` | int，可选 | 若设则用 `interval:` + `max_fires`（默认 max_fires=3，硬上限 20） |

**行为**：

1. 从 `_tool_ctx()` 取 `session_key`（**禁止** Agent 改绑到其他 session）。  
2. 规范化 trigger：`date:` 优先；校验 `at` 不早于 now−60s（过期立即拒绝或立即 fire——**选拒绝并返回 error**，避免误触）。  
3. 写入 cron（`self_reminder` 标记），`fresh_thread=False`，`task_type=agent`。  
4. 返回 `{reminder_id, fire_at, purpose, session_key}`。  

**取消**：`cancel_self_check(reminder_id)`（仅能取消本 agent + 本 session + self_reminder 行）。

**伪代码**：

```python
async def schedule_self_check(at=None, in_seconds=None, in_minutes=None, purpose: str = "", repeat_every_seconds=None):
    agent_id, user_id, session_key = _tool_ctx()
    fire_at = resolve_wall_clock(at=at, in_seconds=in_seconds, in_minutes=in_minutes)  # UTC/aware ISO
    trigger = f"date:{fire_at.isoformat()}"
    if repeat_every_seconds:
        trigger = f"interval:{int(repeat_every_seconds)}"
    prompt = build_wakeup_prompt(purpose=purpose)  # 见 §3.2
    row = await cron_manager.create(CronCreateSpec(
        cron_id=new_cron_id(),
        agent_id=agent_id, user_id=user_id,
        name=f"self-check:{purpose[:40] or 'progress'}",
        trigger=trigger, prompt=prompt,
        session_key=session_key, fresh_thread=False, task_type="agent",
        enabled=True,
        meta={"self_reminder": True, "max_fires": 3 if repeat_every_seconds else 1},
    ))
    return {"reminder_id": row.cron_id, "fire_at": fire_at.isoformat(), "purpose": purpose}
```

Wire：`build_cronjob_tools` 旁新增 `build_self_reminder_tools`，经 `HarnessAgentConfig.tools` 注入（与 cron tools 同等通道）。

### 3.2 唤醒 prompt 模板（系统）

```
[SELF_CHECK_REMINDER]
purpose: {purpose}
You previously scheduled this self-check. Wall-clock time has been reached.
1) Summarize progress since the last user-visible update (or say unknown).
2) Detect if you are blocked or idle without a plan; if so, propose recovery.
3) Report briefly to the user, then continue the task or ask one clarifying question.
Do not create duplicate reminders unless still needed; cancel spent one-shot reminders.
```

One-shot：fire 成功后 **自动 disable/delete** 该 job（`max_fires` 计数）。

### 3.3 HTTP API（可选，S1 可不做 UI）

| Method | Path | 说明 |
|--------|------|------|
| `GET` | `/agents/{id}/cron?include_self_reminders=true` | 现有 list 扩展；默认 false 过滤 |
| 不强制新 CRUD | — | Agent 走 tool 即可；用户 UI 不展示创建表单 |

---

## 4. REQ / AC

### REQ-001 设定提醒

- Requirement: Agent 可在会话中调用 `schedule_self_check`，用 `at` 或 `in_minutes`/`in_seconds` 创建 one-shot 提醒，绑当前 session。
- AC-001: `in_minutes=30` → 存储 trigger 为 `date:<now+30m ISO>`（允许 ±2s 测试误差），`meta.self_reminder=true`（或 `kind=self_reminder`）。
- AC-002: 未带时间参数 → tool 返回 error JSON，不建 job。
- AC-003: 默认 list cron API **不包含** 该 job。

### REQ-002 到点唤醒同会话

- Requirement: 到点在同一 `session_key` 注入 agent 回合；`fresh_thread` 为 false。
- AC-004: idle 会话到点后 5s 内出现新的 agent 输出（测试可用短 `in_seconds=2`）。
- AC-005: transcript 中可见唤醒回合且 **未** reset 线程（先前消息仍可被引用）。

### REQ-003 Running 中排队

- Requirement: 会话正在 running 时到点不丢提醒，本轮结束后 fire。
- AC-006: 模拟 long-running turn + 到期 → turn 结束后必有 self-check turn。

### REQ-004 取消与 one-shot 清理

- Requirement: `cancel_self_check` 可取消；one-shot fire 后自动禁用。
- AC-007: cancel 后到点不再 fire。
- AC-008: fire 一次后 job enabled=false 或已删除。

### REQ-005 「做 30 分钟」语义

- Requirement: 文档与 tool description 标明 **wall-clock**，非模型 token 时间。
- AC-009: tool description 含 “wall-clock” / 「挂钟时间」字样（i18n 可随后）。

### REQ-006 进度摘要行为

- Requirement: 唤醒 prompt 含 progress / blocked 检查指令（§3.2）；无独立进度 store 时允许基于 transcript。
- AC-010: 单元测试断言 `build_wakeup_prompt` 含 `SELF_CHECK_REMINDER` 与 purpose。

---

## 5. Coder 最小切片（可勾选）

- [ ] **S1 tool + store + fire** — `schedule_self_check` / `cancel_self_check`；持久化 self_reminder 标记；`date:` 调度；list 默认过滤；one-shot 清理。  
- [ ] **S2 会话唤醒注入** — 复用/扩展 `CronDeliveryService`：running 时 pending queue；idle 立即 deliver；强制 `fresh_thread=False`。  
- [ ] **S3 进度摘要钩子（可选增强）** — 若存在 task_board / turn tracker，唤醒时附带最近进度快照字段；无则跳过，仅靠 prompt。  
- [ ] **S4 Dashboard（可选 P2）** — Cron 页「含自我提醒」折叠开关；默认关。

### 5.1 精确文件路径

| 动作 | 路径 |
|------|------|
| 新建或扩展 | `src/octop/infra/cron/tools.py`（self-reminder tools） |
| 改 | `src/octop/infra/cron/manager.py`（create 持久化 meta/kind；fire 计数；list 过滤） |
| 改 | `src/octop/infra/cron/delivery.py`（可选：pending 若 running） |
| 改 | `src/octop/infra/cron/job.py`（one-shot 后 disable；读 max_fires） |
| 改 | `src/octop/infra/db/repos/cron.py`（meta 或 `kind` 列；`to_public_dict`） |
| 改 | `src/octop/api/routers/cron.py`（`include_self_reminders` query） |
| 改 | Agent tools 注册处（搜 `build_cronjob_tools` 调用点，一并注册） |
| 测试 | `tests/.../test_self_reminder_0018.py` |
| 可选 | Dashboard cron 列表过滤开关 |

**禁止**：把 self-reminder 做成独立 APScheduler 第二套却不复用 trigger；禁止默认 `fresh_thread=True`；禁止在产品 Cron 创建表单默认露出 self-reminder。

---

## 6. 风险与回滚

| 风险 | 缓解 |
|------|------|
| Agent 刷屏建大量 interval | `max_fires` 上限；短间隔最小值（如 ≥60s） |
| 与用户 cron 列表混淆 | 默认过滤；命名前缀 |
| Running 竞态丢提醒 | pending queue + session lock |
| meta 未落库 | S1 先补 schema；测试读写 round-trip |

**回滚**：feature flag / 不注册 tools 即总关闭；已有 self_reminder 行可脚本 disable。

---

## 7. Evolution

- 用户可见「我的会话闹钟」只读页。  
- 与 task_board 深度集成（结构化进度 %）。  
- 跨设备同一 session 的提醒（仍跟 session_key，不跟 device）。  
- `agently:` 不适用本规格。

---

## 8. Evolution log

- 2026-10-15.1: 初稿 Ready；复用 cron `date:`/`interval:` + session 绑定；DEC 写死注入唤醒而非 pause+resume；与产品 Cron UI 分离。
