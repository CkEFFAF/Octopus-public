# 0021 P0-A+B：上下文轨迹采集保真与请求/轨迹回看（实施 Ready 切片）

- Spec ID: `0021-p0-ab-context-trace`
- Status: **Ready**
- Revision: `2026-10-16.3`
- Date: 2026-10-16（Asia/Shanghai）
- Mode: ENHANCEMENT / CROSS-CUTTING（Enhance existing；禁止平行第二套统计）
- Authoritative path: `docs/specs/0021-p0-ab-context-trace.md`
- Parent（方案，仍 **Proposed**）:
  - ops 包 `docs/specs/0021-native-context-refactor-proposal.md`（Rev ≥ `2026-10-16.2` / `.3`）
  - ops 包 `docs/specs/0021-minimum-context-trace-acceptance.md`（AC14–AC18）
  - ops 包 `docs/specs/0021-ui-layout-and-interactions.md`（UI01–UI10）
- Sibling / 承接: `0020-context-insights-and-harness-tools`、`0020.1b-context-panel-sort-pills-multiblock`
- **0020.2 已取消**（PR#15 已关）：首轮 **不含** Insights 全页/骨架；本切片可独立合入
- Repository: `CkEFFAF/Octopus-public`
- Git 起点: 最新 `origin/main`，**必须包含** `cc2ac13ba24a6328f142b2f8076654986d52d3b1`（PR#16 / tag `v1.0.2b16`）
- 研究基线: `80c4ab7ca15b997597504055994cec364ac90d64`
- 上游固定参考: `bowenliang123/dsh-context@ef478dee246abb072fcb32ffbf084e79220acf78`（v0.72.0）
- 设计审查: ops `design-review-2026-10-16.md`（PASS；契约已澄清）
- 原型: ops `prototype/` **仅参考 IA**；**禁止**写「照搬 prototype 到生产 UI」
- 本文件性质: ops 包 Status 仍 Proposed；**本文件是首轮 P0-A+B 的实施 Ready 切片**，供 Coder 直接开分支

---

## Goal

首轮交付用户可回答的最低闭环（对标 AC14–AC18）：

1. **每 step / 每轮**：实际发给模型的有序组成 + 已授权内容入口；轮视图列出该轮全部 steps。
2. **工具**：按 step/turn 可对账逻辑调用次数、attempt 次数、状态、实际参数、完整已保留结果；结果反复进上下文 **不**重复计执行次数。
3. **从会话开始到当前**：可分页查询的完整轨迹；注入来源/版本/生效 step；压缩/裁剪前后可回看；页面分页 ≠ 底层静默裁历史。
4. **统一读面**：扩展既有 `ContextInsightsService`；UI / Ring / Agent tools **同源 DTO**；`ResolvedContextScope`；三类用量分开；历史实际目标走冻结 `ExecutionContext`；coverage / 未知 ≠ 0。

## Non-goals

- 不实现 P1-C 完整 Events+File 聚合语义、`context_change_log` 可靠增量（可预留接口字段，不建框架）。
- 不实现 P1-D Fleet / 完整群成员窗口分列（UI04b）、`context_fleet`。
- 不实现 P2-E 跨会话 Insights 总览、P2-F 策略辅助动作。
- **0020.2 已取消**（PR#15 关闭）：首轮不含 Insights 全页/`/context-insights`/跨会话 KPI 骨架；勿 cherry-pick PR#15。
- 不碰 `work_mode` 证据校验 / receipt 记账语义；Insights **只读**已落库。
- 不照搬 dsh Cordis / DSH session projections / `reserve.ts` 常量到生产。
- 不把 prototype 示例数据写入生产 fallback。
- 不为 P0 提前建通用物化投影框架（先复用 SQLite + 现有分页；测出瓶颈再加可重建投影）。

---

## DEC

| ID | 决议 |
| --- | --- |
| **DEC-T01** | **扩展既有** `infra/context_insights/ContextInsightsService`；旧 API 渐进委托；native tools 与 Dashboard **同一 DTO**。禁止平行 `ContextInsights2`。 |
| **DEC-T02** | **同源 DTO**：`schema_version` + `resolved_scope` + `revision`（ETag 相等性，非单调）+ `as_of`（UTC RFC3339）+ 每模块独立 `coverage` / `source` / `quality` / `reason_codes` / `next_cursor`。 |
| **DEC-T03** | **三类用量分名字段**：① 当前窗口占用 ← `compute_context_breakdown` / harness snapshot；② 单请求 `actual_usage` ← provider settlement；③ 会话累计 ← owner 约束的 ledger 聚合（`UsageRepo.thread_totals` 经服务封装）。禁止 ledger + actual 再相加；成员转发不二次结算（UI04a / AC04）。 |
| **DEC-T04** | **冻结 ExecutionContext**：历史 `effective_*` 仅经 `request.context_id` → owner-scoped `ExecutionContextRepo.get`（receipt 交叉校验）；查不到 → `null` + `missing_execution_context`。专家默认 / 当前 selection 只进 `configured_defaults` / `current_selection`，**不得**回填历史实际值。 |
| **DEC-T05** | **coverage / 未知 ≠ 0**：`coverage: complete\|partial\|unavailable`；容量兼容默认 128k 与真实 capacity 分离（`capacity_source` / `compatibility_capacity_tokens`）；缺失用量 / pending / unknown 不显示假 0。 |
| **DEC-T06** | **分页 ≠ 裁剪存储**：UI 可默认最近一页；底层按会话生命周期保留本最低范围的 metadata+content refs；静默只留最近 N 轮仍标「完整」= 失败。旧会话只还原已保留源，缺则 `missing_ranges`。**与 DEC-T12 联动**：禁止无 coverage 的 trajectory 静默 DELETE。 |
| **DEC-T07** | **捕获相位**：以最终 provider 请求组装完成后、实际发出前为准（model-visible）；中间草稿若存须标 `snapshot_phase`，不可冒充实际请求。 |
| **DEC-T08** | **工具三计数**：可用 schema 数 ≠ 逻辑 `call_id` 数 ≠ `attempt_id` 数；`invocation_origin_request_id` vs `consumed_by_request_ids`。 |
| **DEC-T09** | **不碰 work_mode 证据校验**；不改 Accepted `0004*`；**0020.2 已取消**（PR#15），首轮范围禁止混入 Insights 骨架。 |
| **DEC-T10** | **首轮 UI 面**：Context 内层 **概览 / 请求 / 轨迹** 达到 AC14–AC18 与 UI01–UI03、UI04a、UI05–UI10；文件/协作入口可保留可达但不冒充完成；UI04b / Fleet / 总览 / 策略延后。生产组件用现有 theme/i18n；**禁止照搬 prototype**。 |
| **DEC-T11** | **Agent 工具**：保留 `context_inspect` / `context_events` / `context_file_ops`；新增 `context_request`、`context_trace_read`（参数形状见提案 §5.8 / 最低验收 §7）；owner 来自运行身份，非模型参数。默认 limit 50 / max 100。 |
| **DEC-T12** | **轨迹静默 prune ↔ AC14（Coder 探测拍板）**：`TRAJECTORY_RETENTION_USER_TURNS=50` + `prune_older_than_user_turns` 今日会 **静默 DELETE** 且无 coverage。**A0 必须消除静默 prune**：默认 **关闭/旁路** 自动 prune（会话生命周期保留，与 request_snapshots 一致）。若因磁盘压力保留可选 prune，则 **必须** 落 `retention_gap` + `missing_ranges` + `reason_codes`，且之后查询 **禁止** 对被删区间标 `coverage: complete`。路径：`trajectory/settings.py`、`service.py`、`store.py`、`trajectory_events.py`。 |
| **DEC-T13** | **「完整已保留结果」语义**：= 运行时 **确已保留** 的内容 + `content_truncated` / `source_truncated` / `components_truncated` 等标记；大内容优先走既有 **授权 resource refs** 按块读。Harness 今日为 **有界 inline**（16k/段、128k/请求、256 components），**无**独立 content_ref blob——P0 **不强制新建 blob store**；先暴露 snapshot + 截断标记 + 可分页 component/结果。**禁止**伪造未采集的外部 stdout/进程输出。 |
| **DEC-T14** | **P0-A 优先 UI 同源**：`ChatDockContext` Ring/stats（及后续概览摘要）经 API **委托** `ContextInsightsService`；禁止继续 `contextUsage`+`trajectoryApi.metrics` 与 Agent tools **双口径**。 |
| **DEC-T15** | **计量分字段**：新增 `model_requests` / `human_turns` / `trajectory_events`；旧 `steps`/`turns` 仅作 `legacy_alias` 并标注口径（今日 `aggregate_metrics`：steps≈事件数、turns≈user 事件）。 |
| **DEC-T16** | **首轮工具**：B0 **必加** `context_request`（Insights 级 + native tool）；`context_trace_read` 同 B0（支撑 AC16 长结果分页）。不发明 `context_fleet`。 |
| **DEC-T17** | **schema ≠ call ≠ attempt**：DTO 分字段暴露 `tool_schema_count`（或 composition 组件计数）、`logical_call_count`（distinct `call_id`）、`attempt_count`（distinct `attempt_id`）；禁止混用。 |


---

## 数据契约摘要

### RequestIdentity

```text
request_id, attempt_id?, turn_id?, request_seq?, run_id?, context_id?
effective_model_ref?, execution_target_ref?  # {context_id, source_ref}
status, created_at/ended_at?, snapshot_phase
```

### Components（有序）

```text
component_id, kind, order, role?
source_ref, content_ref?, content_hash?
source_version?, injection_id?, tool_call_id?, parent_ref?
estimated_tokens, truncated?, redacted?, missing?
```

列表接口返回轻摘要（composition / counts / truncation flags）；完整内容按需分页读，refs 再鉴权。

### Tool call / attempt

```text
name, registry_source (native|mcp|device|plugin)
call_id, attempt_id?, parent_call_id?
step/request_id, turn_id
args_ref, result_ref (runtime 完整已回传), model_visible_result_ref?
status: success|failure|cancelled|pending|unknown
invocation_origin_request_id, consumed_by_request_ids[]
```

### Injection / transformation

```text
injection_id, kind (system|rules|skills|tool_schema|workspace|memory|collab|…)
source_id, content_version/hash, content_ref, scope
first_effective_step/request_id, still_present_in_request_ids[]
transformation: compact|prune|reinject — before/after refs, estimated delta
```

区分 **本 step 新注入** vs **仍在窗口的历史注入**。

### Coverage（响应最小字段）

```text
observed_start, observed_head, queried_range
coverage: complete | partial | unavailable
missing_ranges[], reason_codes[]
  (capture_failed | source_truncated | retention_gap | legacy_missing | capability_missing | …)
next_cursor, revision, as_of, source, quality?
```

### ResolvedContextScope（服务内部）

```text
subject (owner_user_id from auth)
readable threads / capabilities
room_ref? {host_agent_id, room_thread_id}
member/shared admission summary
# 缓存键含授权摘要；详情读取重新验证准入
```

首轮可只做单会话 owner/thread 路径；若提前暴露群 scope，须满足 UI04b 或明确 unavailable（本切片默认 **不开放群窗口合并百分比**）。

---

## 切片与 REQ / AC 映射


### 实施切分（Coder 探测后拍板 · A0 → B0）

| 切片 | 范围 | 必过 |
| --- | --- | --- |
| **A0**（最小第一 PR） | coverage + 三类用量/质量标签 + **停或披露 prune（DEC-T12）** + UI Ring/stats **委托** Insights（DEC-T14）+ `model_requests`/`human_turns`/`trajectory_events`（DEC-T15）+ `thread_totals` 经服务封装；契约测 AC01–05 | AC01–05；AC14 的 prune/coverage 底线 |
| **B0**（紧随） | `context_request`（+ `context_trace_read`）+ turn→全部 steps + schema/call/attempt 分字段对账（DEC-T08/T17）+ 注入/transformation 回看（缺则标 missing）+ 请求/轨迹 UI；不造空 Fleet | AC06–07、AC14–AC18；UI01–UI03、UI04a、UI05–UI10 |

探测证据：`/workspace/0021-probe/PROBE-REPORT.md`（只读；@`cc2ac13`）。

### P0-A：采集保真 + 有界持久化 + 统一服务/计量/coverage

| REQ | 内容 | AC |
| --- | --- | --- |
| REQ-A1 | 扩展 `ContextInsightsService`：scope/summary/window/coverage；旧 endpoint / tools 委托 | AC01, AC02, AC05 |
| REQ-A2 | 三类用量字段 + 固定样本契约测试 | AC03, AC04, UI04a |
| REQ-A3 | 兼容 128k vs 真实 capacity；未知不造百分比 | AC05, UI03 |
| REQ-A4 | `thread_totals` 经服务 owner 约束；累计不受 UI 分页影响 | AC04 |
| REQ-A5 | 采集：有序 components + content refs；工具 call/attempt；注入/压缩事件；失败/取消可见 | AC14–AC18（采集侧） |
| REQ-A6 | `model_requests` / `human_turns` / `trajectory_events` 分字段；旧 `steps`/`turns` 兼容别名并标口径 | AC02 |

### P0-B：请求浏览 + 全轨迹回看 + 同源 Agent 读工具

| REQ | 内容 | AC |
| --- | --- | --- |
| REQ-B1 | Trend/列表以真实 `request_id` 为主；选中联动 Browser；摘要轻、详情按需 | AC06, AC07, UI02 |
| REQ-B2 | Step/轮次切换；轮下列出全部 steps；有序组成树 + 内容入口 | AC15, UI 请求视图 |
| REQ-B3 | 轨迹视图：从首记录→head 可分页；过滤 模型/工具/注入/压缩/配置；工具展开参数+完整已保留结果 | AC14, AC16, AC18 |
| REQ-B4 | 注入详情 + 压缩前后回看；新/历史注入可区分 | AC17 |
| REQ-B5 | `context_request` + `context_trace_read`；与 UI 同 facade | AC07, AC10（首轮读工具部分） |
| REQ-B6 | 历史 effective 绑定冻结 EC；重启后已保留请求可读 | AC07, DEC-T04 |

### 首轮必过 AC（摘录可验收）

| AC | 验收要点 |
| --- | --- |
| AC01 | 两用户 / 共享专家 / 详情与缓存无越权（单会话 owner 路径至少通过；群深度 ACL 随 D） |
| AC02 | 同 scope/as_of 下 UI、Ring、tools 同源同值 |
| AC03 | estimated / actual / 当前窗口 / 预览可区分；缓存无重复加和 |
| AC04 | 分页/重载/压缩/转发成员回复不改已结算累计、不重复计数 |
| AC05 | 有界数据带回 coverage；缺失/无用量/真实 0 可区分 |
| AC06 | Trend / Browser /（基础）轨迹 / Receipt 经稳定 ID 联动 |
| AC07 | 重启后已保留请求可读；不默认解码巨型 checkpoint |
| **AC14** | 新会话首记录→head 可分页无静默丢失；旧缺失可见 |
| **AC15** | 任意历史 step 有序组成+内容；轮列全 steps；改专家默认后历史不变 |
| **AC16** | 工具 call/attempt/状态/参数/完整已保留结果可对账；重复进上下文不加执行次数 |
| **AC17** | 注入来源/版本/内容/生效 step；压缩前后回看；新 vs 仍在窗口可区分 |
| **AC18** | 重启/中断/失败/取消后可见已采集部分与真实状态；无结果标 pending/unknown |

### 首轮 UI

UI01–UI03、**UI04a**、UI05–UI10。**UI04b / Fleet / 总览 / 策略延后。**

---

## 现状 vs 规格（代码观察 @ `cc2ac13`）

| 区域 | 现状（事实） | 规格要求 | 最小修订建议 |
| --- | --- | --- | --- |
| `ContextInsightsService.inspect` | 有 breakdown/stats/trend/execution；无 coverage/quality/三类用量分栏；stats 来自 `aggregate_metrics`（`steps=len(events)`，`turns=kind==user`） | 同源 DTO + 分字段口径 + coverage | 扩展返回契约；新增 `model_requests`/`human_turns`/`trajectory_events`；旧字段标 `legacy_alias` |
| UI 读路径 | `ChatDockContext` 调 `contextUsage` + `trajectoryApi.metrics/history`；tools 调 Insights service | 单一服务 facade | UI 逐步改走 Insights（或 API 委托 service）；对照测试同 as_of |
| `events()` | 仅 trajectory 分页；注释写明 run_events 未合入 | 首轮轨迹以 trajectory + request/tool/injection 关联为主；完整 run_events 合入属 C | P0 扩展 trajectory 侧 tool/injection 载荷与链接；**不**假装 run_events 已全量合并 |
| `file_ops()` | ≤500 run_events 启发式路径聚合 | C 阶段完善 | P0 保持；gaps 诚实 |
| `_breakdown` / max_tokens | 默认 `128_000` | 兼容默认 ≠ harness capacity | 增加 `capacity_source` / `compatibility_capacity_tokens`；真实未知时 capacity null |
| `_execution_summary` | 当前 `selection` | 历史应用冻结 EC | 列表/当前卡可保留 selection；**请求详情**走 context_id→EC；禁止回填 |
| `RequestInspectionService` | 授权 list/get；列表剥 components；有 composition / truncation / transformation / actual_usage；components 现多为 inline `content` | content_ref 分页；attempt；injection_id；轮次全 steps | 在现有 sink/repo 边界补字段；大内容迁 ref+分块读；保留 truncation 标记语义 |
| Agent tools | `context_inspect` / `context_events` / `context_file_ops` | + `context_request` / `context_trace_read` | 注册同 catalog；实现委托 Insights + RequestInspection |
| `UsageRepo.thread_totals` | 按 agent/thread 聚合；**无 owner 参数** | 服务层 owner 约束后再暴露 | 服务先校验 thread 属主再调 totals；逐步带 request 关联去重（旧行标 legacy） |
| ResolvedContextScope | 无独立类型；tools 用 thread 行 + identity | 内部 ACL 摘要类型 | 最小 dataclass/TypedDict；首轮单会话填满必填字段 |
| 0020.2 | **已取消**（PR#15 关闭） | 首轮排除 | 禁止 cherry-pick / 写入本 PR 范围 |

**不补造**：当前不声称已有 attempt 对账、全量 injection 审计表、或 UI 已接 Insights 单一路径。

**Coder 探测硬缺口（@cc2ac13，写入 Ready）**：`TRAJECTORY_RETENTION_USER_TURNS=50` 静默 DELETE ↔ AC14 → 见 **DEC-T12**；snapshot 有界 inline 无 blob → **DEC-T13**；UI 双路径 → **DEC-T14**；缺 `context_request` → **DEC-T16**。

---

## 给 Coder 的可粘贴实现 brief

```text
## 0021 P0-A+B 实现 brief（直接开干）

分支名: feature/0021-p0-ab-context-trace
起点: git fetch origin && git checkout main && git pull --ff-only
      确认: git merge-base --is-ancestor cc2ac13ba24a6328f142b2f8076654986d52d3b1 HEAD
      然后: git checkout -b feature/0021-p0-ab-context-trace
规格: docs/specs/0021-p0-ab-context-trace.md（Rev 2026-10-16.3）
上游参考固定: dsh-context@ef478dee（只读研究，勿整包拷入）
勿纳入: 已取消的 0020.2 / PR#15 / Insights 全页骨架

### Writable（优先）
- src/octop/infra/context_insights/**          # service / mapping / 新 DTO 辅助
- src/octop/infra/execution/inspection.py     # 委托/补字段读
- src/octop/infra/db/repos/request_snapshots.py  # 仅当现有 payload 无法表达 refs 时最小扩展
- src/octop/infra/history/trajectory/**       # 工具/注入关联与分页读辅助（最小）
- src/octop/infra/agents/native_management_tools.py  # + context_request / context_trace_read
- src/octop/infra/agents/settings/tool_catalog.py
- src/octop/api/routers/chat/inspection.py    # 及必要的薄 API 委托 Insights
- src/octop/api/routers/chat/history.py / trajectory.py  # 仅委托/对齐 DTO 时
- dashboard/src/pages/Chat/components/ChatDockContext.tsx
- dashboard/src/pages/Chat/components/ContextRequestBrowser.tsx
- dashboard/src/pages/Chat/components/ChatDockContext.module.less
- dashboard/src/pages/Chat/hooks/**（context 相关既有 hook）
- dashboard/src/api/modules/**（execution / trajectory / 新 insights client 薄封装）
- dashboard/src/locales/{zh,en}.json
- tests/unit/context_insights/**
- tests/unit/devices/test_request_inspection.py（及新增 fixture）
- docs/specs/0021-p0-ab-context-trace.md（仅修笔误/验收勾选，不改 DEC 方向）

### 禁止改
- work_mode 证据校验路径（src/octop/infra/execution/work_mode.py 及相关证据白名单）
- docs/specs/0004-*.md（Accepted）
- 无关大重构 / 平行 ContextInsights2 / 照搬 ops/prototype 到生产
- 把已取消的 0020.2 / PR#15 代码 cherry-pick 进本分支
- 伪造余额/精确成本/用当前专家默认回填历史 effective_*

### 实现顺序建议（A0 → B0）
A0: coverage DTO + 三类用量/质量标签 + capacity_source + model_requests/human_turns/trajectory_events
   + **关闭/旁路 trajectory 静默 prune（或 prune→retention_gap，禁 complete）**
   + ChatDockContext Ring/stats 委托 ContextInsightsService；thread_totals 经服务
   + 契约测 AC01–05
B0: context_request + context_trace_read；turn→steps；schema/call/attempt 分字段
   + 注入/transformation 回看（缺标 missing）；完整=已保留+truncate，大内容授权 ref，禁伪造
   + UI 请求/轨迹；冻结 EC 接到请求详情；AC14–18 固定样本 + 桌面/手机证据

### 测试命令
- uv run pytest tests/unit/context_insights -q
- uv run pytest tests/unit/devices/test_request_inspection.py -q
- uv run pytest tests/unit/test_usage_thread_totals.py -q
- uv run pytest tests/unit/agents/test_context_breakdown.py -q
- 相关 trajectory / inspection 单测随改动补跑
- 门禁: make test-fast   （或改动面要求时 make all）
- Dashboard: cd dashboard && npx tsc -b   （改 TS 时）；必要时 npm run lint

### AC14–AC18 手测 / fixture 要点（固定样本至少含）
- 一轮多次模型请求；同工具多次调用 + 重试 attempt
- 失败与取消；长工具结果分页到末尾
- 同一工具结果被多个 step 携带（执行次数不增加）
- 技能/规则/协作注入；压缩/裁剪前后回看
- 模型切换；进程重启后已采集部分仍可读
- 旧历史缺失 → missing_ranges / reason_codes，不拿当前配置填历史
对每条组成核对 hash/顺序；对每个 tool call 核对身份与次数。

### PR 说明要点
- 标题: feat(context): 0021 P0-A/B context trace fidelity + request/trace read
- 基线 commit: 含 cc2ac13 的 origin/main
- 链接本规格 + ops 最低验收 AC14–AC18
- 列出 DTO schema_version、新增 tool 名、未做的 C–F 边界
- 附桌面/手机证据与 pytest 摘要；声明不碰 work_mode / 0020.2 已取消勿混入
```

---

## Relates

- Parent（Proposed）: ops `0021-native-context-refactor-proposal.md`、`0021-minimum-context-trace-acceptance.md`、`0021-ui-layout-and-interactions.md`
- Enhance: `0020-context-insights-and-harness-tools.md`、`0020.1b-context-panel-sort-pills-multiblock.md`
- **已取消**: `0020.2-context-insights-dashboard`（PR#15 关闭；首轮以本规格为准）
- Code: `ContextInsightsService`、`RequestInspectionService`、`RequestSnapshotRepo`、`UsageRepo.thread_totals`、`ChatDockContext`、`ContextRequestBrowser`、native `context_*` tools

## Evolution

| Rev | 说明 |
| --- | --- |
| `2026-10-16.1` | 首版 Ready 切片：P0-A+B；写入仓库 docs/specs；固化 Git 起点 cc2ac13；嵌入 Coder brief；现状差距基于 main 只读调研。 |
| `2026-10-16.2` | 用户取消 0020.2（PR#15 关）：Non-goals/DEC/Relates/Coder brief 写死首轮排除 Insights 骨架。 |
| `2026-10-16.3` | 并入 Coder PROBE-REPORT：拍板 DEC-T12–T17（停静默 prune / 完整=已保留+truncate / UI 委托 Insights / 计量分字段 / 首轮 context_request / schema≠call≠attempt）；实施切分 A0→B0。 |
