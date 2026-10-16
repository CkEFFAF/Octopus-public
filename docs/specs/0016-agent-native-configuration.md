# 0016 Agent Native 产品配置与协作

- Status: Implemented
- Revision: 2026-10-16.6
- Source: 用户要求 AI 能自行创建和配置专家、子 Agent，找历史会话，邀请多个 Agent 群聊，并适配其他现有基本操作；2026-10-16 明确优先 Agent Native，右侧适配暂停。代码使用 GPT 6.1 High，独立评审使用 GPT 6.0 Luna High。
- Code baseline: `CkEFFAF/Octopus-public` 公开 `main`，`c627ea158fa6afd63a429a934c57cecdb4077c1d`。交付前再次核对发现主线新增 0019 设备默认目标与群聊统一目标，本目录已同步该提交并恢复本切片修改；同步前快照保留在 Git stash。
- Workspace: `D:/Agent_Workspace/octopus/octopus-agent-native`。此前的右侧编辑工作保留在 `D:/Agent_Workspace/octopus/octopus-artifact-native`，本切片不移入。

## Summary

把用户界面已有的产品配置和协作能力提供为原生 Agent 工具。用户可以在会话里要求「创建一个审稿专家和一个检查用子 Agent」「找到上次预算讨论」「拉几个专家组成群聊」，工具通过已有业务服务持久化真实资源，返回资源 ID、实际状态和必要的下一步。界面在工具完成后同步资源列表。

## Requirements

| ID | 可观察行为与验收 |
| --- | --- |
| AN-1 | Agent 可以发现可用产品管理能力及参数入口；工具进入统一目录、禁用开关和中英文名称。发现结果只宣告当前已注册能力，并指出现有 TaskBoard、设备和定时能力入口。 |
| AN-2 | Agent 可以列出和读取专家，创建专家，并修改名称、描述、模型、指令、欢迎语及已有工具/技能/知识库/连接器引用。模型和引用依照已有产品规则校验。读取只返回配置白名单，无密钥或任意原始配置。共享专家可被发现和加入团队；只有所有者可以修改。 |
| AN-3 | Agent 可以查找子 Agent 模板，列出和读取已安装子 Agent，安装模板，创建或明确替换自定义子 Agent。定义使用现有专家工作区和解析约定，不建立另一份数据库。无效 slug/定义拒绝写入；创建与替换语义明确；刷新后能继续使用。 |
| AN-4 | Agent 可以查找当前账户的历史会话，包括本人在当前可用共享专家下的会话；按标题或已经就绪的用户/助手消息文本检索，分页读取历史，创建和重命名会话，查看真实运行状态。搜索结果有 thread/agent ID，输出有界；未知或未索引的历史不假装完整；工具原始输出和其他账户内容不得泄漏。 |
| AN-5 | Agent 可以创建、查看专家团队，修改名称/描述/欢迎语/模型，增减成员，随后创建该团队的群聊。复用 TeamService 的成员资格、至少两名成员、忙碌成员不可移除和团队工作区清单规则。成功返回真实 project/team/thread ID，现有群聊与 ask_agent 调度可以直接使用。团队主持人可以调用这组管理能力，文件和 shell 权限保持既有约束。 |
| AN-6 | Agent 可以为会话后续回合保存设备/目录选择，复用 ExecutionService 和当前设备权限。群聊使用 0019 的同一房间选择，不修改成员默认绑定；当前回合的冻结上下文不被修改。共享专家会话不支持的设备选择须拒绝，不能保存下一轮无法执行的目标；共享专家所有者的私有设备 ID 和目录不得向其他账户暴露。已有 TaskBoard 创建、分派、运行和进度能力继续可用；不重复新建任务状态模型。 |
| AN-7 | 每次调用从可信运行配置取得账户身份，重新校验账户和目标资源权限；Ask/Plan 下配置写入被拒绝，失败无部分越权更改。操作写审计，成功与待生效/失败状态明确。修改自身配置时不因立即 reload 中断当前回复。 |
| AN-8 | 原生操作后前端刷新相关专家、团队、会话和设备选择状态，旧线程的迟到响应不覆盖新线程状态。相关服务、工具及关键 API 集成测试通过，类型检查通过；独立模型评审发现的问题修复后复验。 |

## Decision / Design

1. **同一数据源。** 资源操作经 AgentManager、TeamService、ExecutionService、HistoryArchive 和现有 repos 完成。子 Agent 安装/保存的现有 HTTP 逻辑下沉到共享 infra 服务，HTTP 与 Agent 调用相同实现；infra 不导入 API。
2. **配置边界。** 提供显式、可验证的参数，不开放任意 `config_json` 或服务器管理配置。省略参数表示不修改，空值是否清除按对应已有服务规则处理。工具/技能等引用使用产品已有有效 ID。未知参数拒绝，不能借配置接口扩大后端目录或读取凭证。
3. **会话检索。** 仓库提供有账户条件的参数化搜索，搜索词按字面匹配并限制结果页。消息正文只选择用户/助手文本；老历史尚无投影时明确提示。读取已有档案，不迁移或重写用户历史。
4. **团队即群聊主体。** 使用当前 `kind=team` 专家和其 manifest 成员名单；新建团队后可通过会话工具创建房间。主持人的管理工具白名单显式更新，仍沿用已有派工和工作证据机制。
5. **运行与配置分离。** 配置持久化后通过现有安全 reload 调度在适当时间生效，回执区分已保存与待 reload。设备切换只保存后续回合目标。工具处理不能关闭或重绑定当前用户会话。
6. **本次优先级。** 右侧 Office/Markdown/HTML 预览和编辑代码保留在原独立目录，暂停开发和验证，不纳入本次交付或完整性声明。也不添加没有现成产品语义的破坏性批量删除或账户管理功能。
7. **0019 兼容。** 保留上游设备默认信息、`ask_agent` 目标策略和房间统一选择；native 继续调用同一选择存储。拥有的专家可显示已验证的默认目标，共享专家隐藏所有者私有目标；目标解析仍遵循调用账户权限。明确要求 explicit 却未提供有效目标时拒绝派工，不静默沿用主持人目标。同步后重新验证受影响的专家发现、团队成员信息、设备选择及前端刷新，不沿用旧基线的通过结论。
8. **共享成员派工。** 群聊主持人可以调用当前名单中已启用且仍共享的专家；仅对本人拥有的 team 主持人放宽 harness 的同所有者筛选，调用时重新检查名单与共享状态，不修改全局 registry 的所有者信息。非名单、停用或取消共享的外部专家不可调用。共享专家的设备执行仍受当前 ExecutionService 同所有者规则限制，本切片仅保证其无设备文本协作，不扩大跨账户设备执行权限；回执/能力提示应明确该边界。
9. **共享文本调用的真实执行边界。** 已重新校验的共享名单调用由服务端标记为纯文本；请求准备再次验证账户、主持人、目标及当前名单，忽略共享专家私有设备绑定和账户默认设备，不修改这两种默认。请求使用 Ask 限制，关闭技能、MCP 和模型可用执行工具；设备 middleware 不读取或显示私有绑定。伪造或过期的调用标记拒绝。回归必须经过真实请求准备和设备 middleware，不能只在 mock 的 callee 入口验证排队成功。

## Build plan

1. 同步缓存主线，检查已有能力与权限服务，固定本文合同（AN-1～AN-8）。
2. 接入专家可配置工具与共享子 Agent 服务，覆盖创建/读取/修改和拒绝路径（AN-1、AN-2、AN-3、AN-7）。
3. 接入账户历史检索、会话管理和群聊团队名单操作，覆盖跨用户隔离、不可用成员、忙碌移除和结果持久化（AN-4、AN-5、AN-7）。
4. 接入后续设备选择、能力目录、审计和前端资源通知，保留现有任务编排（AN-1、AN-6～AN-8）。
5. 集成验证并交 GPT 6.0 Luna High 只读评审，修复确认问题，记录当前代码的证据与未验证项（AN-1～AN-8）。

## Native tool surface

23 个工具在当前专家的工具禁用配置中统一管理，具体可用性由运行时发现返回。

| 用户操作 | 工具 |
| --- | --- |
| 查看能力与有效配置引用 | `octop_capabilities`、`octop_resource_list` |
| 创建、查看和配置专家 | `octop_expert_list/get/create/update` |
| 查找模板、安装和创建子 Agent | `octop_subagent_catalog/list/get/install/save` |
| 创建群聊、重命名和调整成员 | `octop_project_list/get/create/update/update_members` |
| 查找、读取、新建、重命名会话和查看状态 | `octop_thread_list/search/create/read/status/rename` |
| 保存后续回合的设备/目录选择 | `octop_device_select` |

任务创建、分派、执行和进度沿用 `task_board_*` 与 `ask_agent`；定时任务沿用 `cronjob_*` 及已注册的自提醒工具。可直接用自然语言要求「创建写作和审稿专家，建群讨论」「找我上次讨论预算的会话」「给写作专家添加检查用子 Agent」「下一轮切换到这台设备」。实际模型是否选择正确工具尚未做 live 模型端到端验证。

## Evidence

当前 `2026-10-16.6` 已同步 `c627ea15`，本切片的本地实现、最终定向与完整后端回归、静态检查和独立复审已完成。前端全量失败与实际运行边界如下保留，不宣称全栈测试全部通过。不复用旧 `octopus-artifact-native` 的证据。

### 当前基线 c627ea15

| 验证 | 当前结果 |
| --- | --- |
| 前端类型与生产构建 | `npm run build`（含 `tsc -b`）通过，保留 0019 群聊统一目标与 native 刷新。 |
| 完整前端回归 | **1336 passed / 11 failed**。未修改 `c627ea15` 对照为 **1336 passed / 10 failed**，10 项既有失败用例一致；额外一项 `TrajectoryInspector loads full content on the Preview tab` 为全量运行中的 Markdown 异步预览失败。该文件与设备选择文件单独复跑 **32 passed**，包含该预览用例；未修改预览代码或测试断言。 |
| 前端 ESLint / 格式 | 修改文件 0 errors、1 项既有 React 依赖警告；7 个修改文件 Prettier 复验通过。 |
| Native 与上游兼容定向回归 | 最终 r6 **42 passed / 2 warnings**，51.14 秒，覆盖 native、真实流式群聊共享派工、请求准备、设备 middleware、0019 目标可见性、上下文与解析优先级。代码与测试冻结快照一致。此前 r5 的 **67 passed** 仅作历史参考。 |
| 后端静态检查 | 最终 r6 Ruff check 通过、**1285 files already formatted**；严格 mypy **634 source files** 无错误。 |
| 最终独立复审 | Luna High 复审 r6 未发现新的可操作问题；源码与冻结快照一致，唯一后续测试变化为修正被装配器包装后的 spy 引用。 |
| 完整后端 | 最终 r6 在 `c627-r6-final-source-snapshot.json` 上 **4726 passed / 151 skipped / 36 warnings**，375.27 秒，退出码 0。日志：`logs/agent-native-verification/backend-c627-r6-full.log`。 |
| 交付前远端核对 | `git ls-remote --heads origin main` 确认仍为 `c627ea158fa6afd63a429a934c57cecdb4077c1d`。 |

最终主要验证命令（仓库根目录；前端命令在 `dashboard/` 执行）：

```text
uv run --no-sync --frozen ruff check src tests
uv run --no-sync --frozen ruff format --check src tests
uv run --no-sync --frozen mypy --strict src/octop
uv run --no-sync --frozen pytest -m "not live" -n 8 --dist loadfile -q -p no:cacheprovider --basetemp=D:/Agent_Workspace/octopus/.pytest-agent-native-c627-r6-full
npm run build
```

定向回归：`uv run --no-sync --frozen pytest tests/integration/test_native_management_tools.py tests/unit/agents/test_team_device_context.py tests/unit/agents/test_target_visibility_0019.py tests/unit/agents/test_device_target_middleware.py tests/unit/execution/test_resolve_priority_0019.py -q -p no:cacheprovider --basetemp D:/Agent_Workspace/octopus/native-r6-final-gate-20261016c`。Windows sandbox 首次运行因临时目录 ACL 出现 setup errors，未进入断言；同一命令在允许的执行环境复跑通过，未修改代码或断言。

### 同步前历史证据

下列是同步前 `634c1bde` + 本切片、规格 `2026-10-16.3` 的历史证据，不能直接视为新基线已验证。

| 验证 | 当前结果 |
| --- | --- |
| Native 真实服务/HTTP 集成、子 Agent HTTP、团队服务与工具目录 | 评审修复后 **38 passed**。覆盖专家/子 Agent/群聊实际持久化、无效引用拒绝、共享访问、文本历史、并行创建、安全重载及设备冻结。 |
| AgentManager 全文件回归 | **101 passed**；已同步新增工具的清单契约断言。 |
| 后端中英文标签 | **76 passed**；23 个 native 工具均进入统一能力目录。 |
| 后端 Ruff 与严格 mypy | Ruff 检查/格式通过，完整 mypy **632 source files** 无错误。 |
| 前端设备选择回归 | **23 passed**，包括 native 更新与旧线程迟到响应拒绝。 |
| 完整前端回归 | **1337 passed / 10 failed**；按用例名与未修改的 `634c1bde` 对照，失败集合完全相同，新增失败为 **0**。既有失败位于旧工作台标签测试（8）、导航权限布局（1）、路径权限映射（1）。 |
| 前端类型、改动文件 ESLint/Prettier、生产构建 | `tsc -b` 通过；ESLint 0 errors、1 项既有依赖警告；Prettier 通过；`npm run build` 通过。 |
| 独立评审 | GPT 6.0 Luna High 首轮 2 项 P2 已修复，复审未发现新的可操作问题。见 `docs/reviews/0016-agent-native-configuration-review.md`。 |
| 完整后端非 live 回归 | **4704 passed / 151 skipped**，371.94 秒。首次全量发现 4 个手工构造 Manager 的测试缺少生命周期字段，补齐测试夹具后复跑通过，未放宽断言。 |

### 行为覆盖

- AN-1/2：`tests/integration/test_native_management_tools.py` 的资源发现、配置持久化及权限用例，`tests/unit/agents/test_tool_catalog.py`、`tests/unit/i18n/`。
- AN-3：模板/自定义定义、显式替换及 native/HTTP 并行同名创建回归；`tests/integration/test_subagents_api.py`。
- AN-4：字面搜索、共享/所有权、索引就绪、可见文本过滤与截断标记回归。
- AN-5：真实群聊创建、名称配置、成员忙碌/最小人数规则、部分成功回执；`tests/unit/agents/test_team_service.py`。
- AN-6/7：后续设备选择不改动当前上下文、自身修改在最后一个 invocation 释放后合并重载、Ask/Plan 与停用账户拒绝。
- AN-8：`DeviceTargetSelect.test.tsx`、现有前端全量回归、类型检查与生产构建；最终 r6 完整后端回归通过，前端全量失败边界见上表。

### 实际运行边界

- 数据层集成使用 SQLite。PostgreSQL 的文本搜索分支本机尚未执行。
- 未调用付费/live 模型；工具使用可信运行配置直接调用真实业务服务，持久化通过现有 API 核对。前端同步使用 Vitest/jsdom 验证，未宣称已做真实模型驱动的端到端验证。

## Consequences / Follow-up

- 用户的「其他基本操作」通过能力发现与既有任务/设备/定时服务适配，避免创建另一套产品资源。
- 2026-10-16 GitHub 连接恢复后已核对远端主线。后续继续工作仍应检查新增上游变更。
- 2026-10-16 用户已授权提交与合并；功能分支为 `feature/0016-agent-native-configuration`，目标分支与最终 PR 状态以交付记录为准。未请求发版或部署。

## Changes

- `2026-10-16.2`：明确 AN-4 包括用户本人在当前可用共享专家下的会话；仍拒绝其他用户会话。这是产品「找历史会话」的访问范围澄清，相关搜索和读取证据须依此验证。
- `2026-10-16.3`：AN-5 明确团队基本配置修改，覆盖原请求中的项目重命名和配置操作；沿用专家的模型验证及安全重载，不开放额外原始配置。
- `2026-10-16.4`：基线同步至 `c627ea15`，保留 0019 房间统一目标及默认目标信息，明确共享专家设备权限和私有元数据边界；相关旧验证标为历史证据，兼容适配后重新验证与复审。
- `2026-10-16.5`：实际 harness 链路发现共享成员会被第二层所有者筛选拒绝。增加仅针对本人 team 当前共享名单的适配，要求真实 ask_agent 派工与撤销回归；共享成员设备执行继续拒绝，明确文本协作边界。
- `2026-10-16.6`：最终独立评审发现共享文本调用仍会自动应用设备默认并触发所有权拒绝（P1）。补充服务端校验的纯文本执行边界及真实请求准备/middleware 回归；r5 受影响的通过证据失效，修复后重新验证。

## References

- `docs/specs/0015-device-execution-and-context-inspection.md`
- `docs/specs/0018-agent-self-schedule-reminder.md`
- `docs/specs/0019-device-target-defaults-and-session-unify.md`
- `src/octop/infra/agents/manager.py`
- `src/octop/infra/agents/teams/service.py`
- `src/octop/api/routers/subagents.py`
- `src/octop/infra/history/reader.py`
- `src/octop/infra/task_board/tools.py`
