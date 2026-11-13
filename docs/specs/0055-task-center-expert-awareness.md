# 0055. 全局任务面板与专家跨会话任务感知

**Date**: 2026-11-13
**Status**: In Progress

## Summary

提供账号级任务总览，可筛选专家、来源会话和任务状态。聊天任务面板可以查看该专家所有会话的任务。同一专家在新的交互回合获得其他会话的任务摘要，原生任务清单更新进入现有任务记录。

## Requirements

- **AC-1**: 导航有全局任务入口，汇总工作项、任务账本、后台 Job、子任务和已保存计划，可按专家、会话、状态、文本筛选并分页。
- **AC-2**: 会话任务面板可直接查看当前专家跨会话任务，并进入全局总览或来源会话；读取不会追加 worker 输入或启动任务。
- **AC-3**: 每个新用户回合注入同账号同专家其他会话的有界任务摘要。提供只读查询工具以获取完整分页结果，不能接受模型指定用户或专家身份。
- **AC-4**: 成功的 write_todos 更新现有 workbench plan；失败工具调用不产生计划。计划状态明确为 Agent 声明，与 Job 执行证据分开。
- **AC-5**: 所有读取按当前账号隔离。共享专家不能读其所有者或其他使用者任务；过期运行回执显示状态待确认。原任务状态与人类确认边界不变。
- **AC-6**: 离线验证跨会话、账号隔离、来源跳转、筛选、分页、异步请求切换与成功/失败写入，不请求模型或恢复任何研究计划。
- **AC-7**: 定时任务、自提醒、工作项、Job 和已结束的账本任务定期逻辑归档。完成和取消满 7 天、失败满 30 天归档；默认列表在 SQL 层排除归档，历史页不轮询，原始记录保留。暂停中的周期任务、有待处理投递的计划和未完成任务不归档。
- **AC-8**: 会话概览清除标题 Markdown 标记，操作分层；多个来源去重收拢、按需分页查看，重复执行事件折叠保留原始引用，成果使用紧凑列表并先显示 8 项。
- **AC-9**: 五列任务看板直接展示来自执行系统的卡片、按真实来源状态自动刷新，可按专家、会话筛选并跳转来源；保留原有账本创建、分派与验收操作。

## Decision

延伸 0043 的独立权威存储及 0034 的任务活动投影，增加只读聚合层；不把工作项复制进 task_boards 的 revision 协议。使用现有 React、Ant Design、PageShell 和任务面板样式。

## Feature design

| 值 | 来源 |
|---|---|
| 身份 | HTTP current_user；工具和 middleware 的 runtime configurable.user、thread_id 与绑定 agent_id |
| 工作项 | work_items 的 task_id/title/status/agent_id/origin_thread_id/updated_at |
| 账本任务 | task_boards 的 BoardSnapshot；来源会话取最近 run.thread_id |
| Job / 子任务 | run_events 中 job/dispatch；状态过期规则沿用活动面板的 45 秒规则及当前运行标识 |
| 计划 | workbench_records(kind=plan) 的 tasks 与 run_id；write_todos 成功后记录 source=write_todos |
| 专家、会话名称 | agents.name、threads.title，必须与 owner 和 agent 一致 |
| 展示时间 | useServerTimezone / config.default_timezone |

新增 `GET /api/task-center`，参数 agent_id、thread_id、lifecycle、query、offset、limit，返回 typed items、counts、total、分页信息和筛选项。分页只读，不触发后台操作。聚合层保留 source/source_id，不猜测跨来源的任务同一性。

`include_board=false` 为看板读取执行卡片，避免重复显示已有账本任务。不同来源卡片不写入 task_boards revision 数据。新增迁移 041 的 SQLite/PostgreSQL 对保留逻辑归档标记及对应源版本；源记录更新自动使旧标记失效。CronManager 启动及每小时执行归档；账本借现有 tick 每小时维护，仍启用的周期规则不会被归档。schema reconciliation 覆盖已记录 041 的恢复库。

全局页面使用现有 PageShell，顶部筛选、状态计数、任务列表和来源跳转；空、加载、失败、刷新状态完整。聊天面板增加“专家全部任务”和“全局任务”入口。原账本编辑入口保留。

`list_expert_tasks` 只接受筛选和分页值，身份始终从运行时获取。新回合摘要最多 10 项、约 6000 UTF-8 字节，保留 task/source/thread 引用及截断说明。摘要是外部任务数据，不是执行授权；查看摘要不意味着接手、重试或暂停任务。图执行的隔离上下文继续遵守既有 history recipe。

## Build plan

- [x] 账号隔离的只读任务聚合与 typed HTTP API（AC-1、AC-5）。
- [x] 总览页面、专家和会话筛选、导航与聊天面板入口（AC-1、AC-2）。
- [x] 专家任务查询工具、新回合摘要与原生清单持久化（AC-3、AC-4、AC-5）。
- [x] 定期逻辑归档和历史页按需加载（AC-7）。
- [x] 会话概览阅读层级、来源、时间线及成果布局（AC-8）。
- [x] 任务看板实时执行卡片（AC-9）。
- [x] 后端回归、前端交互验证、类型检查、构建及完整离线检查（AC-6）。

## Consequences

旧任务数据直接可读；041 只增加逻辑归档元数据。不同来源的任务保留独立生命周期；运行事实由现有运行回执判定，Agent 的计划进度保留声明来源。结果和后续输入继续属于原始会话。

## Follow-up

本次不启用研究计划、不发起实验、不改变 provider 配额暂停范围。

- [x] 截图视觉验收：已恢复验收浏览器，走查专家与会话筛选及重置、时间线合并、来源弹层与按需读取、文件置顶折叠及多列布局、文件详情和窄面板切换。390px 布局无页面横向溢出。
- 文件变更补充：置顶区默认收起，仅展示名称；路径及来源进入详情后查看。窄面板切换差异与完整内容，看板手动刷新同时更新执行投影，归档页停止账本轮询。
- 后续验证：Linux 前端全量 357 个文件、1878 项测试通过。上线与迁移演练记录见 `docs/task-center-rollout-2026-11-13.md`。
- 验证记录：完整离线后端 5799 passed、157 skipped；前端全量初次 1867 passed，新增导航断言已更新，其余失败及超时用例在低并发单独复验 39 passed。Ruff、mypy、TypeScript、Prettier、ESLint（0 errors，保留既有 1 warning）及生产构建通过。新增归档活动回归另有 104 passed。

## Rationale

用户明确要求全局筛选和同专家跨会话知情。统一只读投影保留各执行系统的权威状态，避免通过复制状态引入冲突与错误验收。
