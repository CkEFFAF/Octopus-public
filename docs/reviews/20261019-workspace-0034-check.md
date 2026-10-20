# 0034 实现审查

审查对象：`feature/0034-workspace-annotations-activity`，基线 `c236203c27c26d2f4beed5bec3aa9b437919dc41`。以下 P2 是本报告初版快照的记录；工作树持续变化，初版问题可能已修复，必须按最终冻结的源码指纹逐项复核，不能据此作为当前结论。没有运行测试或修改应用代码。

## P2：Range 请求仍读取并校验完整文件

`src/octop/api/routers/chat/collaboration.py:186` 对任何请求先调用 `ResourceService.bytes()`，之后才按 Range 截取字节。`src/octop/infra/documents/resources.py:396-409` 每次都读取整个快照并计算完整 SHA256。读取上限是配置的 `max_upload_bytes`，默认 100 MiB（`src/octop/config.py:15,159-164`）。因此播放器请求一个小片段时仍会为每个请求读取至多 100 MiB；多个并行 Range 请求会重复产生与整份文件同阶的内存和磁盘读取。响应虽有 `206`，数据读取并非有界分段，视频跳转场景仍有明显资源放大风险，也不符合规格 4.2 对有界 Range 源的要求。

建议在不可变快照首次登记时校验摘要，随后每次请求仍先校验当前授权，再对快照文件直接 seek 并只读取所请求的区间。

## P2：父会话结束后仍运行的任务会被误标为过期

`src/octop/infra/execution/activity.py:142-158` 只要事件的 `run_id` 不等于当前 `steering_status` 的 `live_run`，且运行状态超过 45 秒，就标记为 `stale`。父会话结束后，仍在运行的后台 Job 会满足这个条件，即使 Job 自己持续报告运行状态。顶栏随后停止显示当前运行状态，节点详情显示观测过期；长任务会被误判为失联。

这与规格 5.4 明确要求的“父会话结束但后台 Job 仍运行”恢复场景冲突。过期状态应取决于该来源是否仍能被查询，以及最近一次成功观测的时间，不能只用 Job 所属的父 run 是否仍是当前聊天 run。

## P2：依赖任务在依赖实际完成后仍停留在等待状态

`src/octop/infra/execution/activity.py:125` 将任何有 `depends_on` 的计划节点初始化为 `waiting`。后续状态合并只针对已有子活动节点（约 205 行起），没有依据前置计划任务的真实完成观测更新尚未派发的节点。因此当 A 的真实 dispatch 已完成而 B 依赖 A、尚未派发时，B 仍显示等待，DAG 无法表达依赖已满足、任务待开始的状态。

解除等待应依据依赖节点的实际完成观测。Agent 对计划状态的自报 `completed` 仍应作为声明单独显示，不能直接当成真实完成证据。

## P2：超过 5000 条活动记录后没有后续分页入口

`src/octop/infra/execution/activity.py` 最多读取 25 页、每页 200 条记录，并在 5000 条时返回 `scope_truncated=true`。活动 API 没有接收游标或页大小的参数，前端 `dashboard/src/pages/Chat/components/TaskActivity.tsx` 也没有显示 `scope_truncated` 或继续加载入口。因此超过上限的旧活动无法从页面查看，用户只会看到被截断的列表。规格 9.3.1 要求完整记录可从有界分页列表访问；当前结果只设了采集上限，没有分页查看能力。

建议活动快照显式提供分页游标和截断状态，并在运行列表中给出继续加载入口。

## P2：部分常见代码文件打开批注时没有文本预览

`dashboard/src/pages/Chat/components/ResourcePanelContent.tsx:64-68` 只把 `text/*` 媒体类型，以及 `md`、`json`、`csv`、`txt` 扩展读成文本。当前后端依赖主机 `mimetypes.guess_type` 推断类型；在本仓库的 Python 环境中，`js` 返回 `application/javascript`，`sh` 返回 `application/x-sh`，`yaml`、`yml`、`toml`、`ps1`、`log` 没有类型。它们因此显示“无法预览”，即使设备工作区允许直接编辑并提供“预览/批注”按钮，也不能选择代码位置。

建议由共享的文本扩展映射判断可预览文本类型，并让代码选择生成行列锚点。

## P2：区域批注与非当前工作表批注无法精确回定位

`dashboard/src/pages/Chat/components/ResourcePanelContent.tsx:125-129` 会保存 PDF 或幻灯片的归一化区域矩形，但 `locate` 只滚动到整页，没有恢复或突出显示矩形区域。表格定位在约 116 行只查询当前已挂载 DOM 中的 sheet 和 cell；`DocumentPreviewCore` 的工作表标签会切换活动表（`dashboard/src/components/DocumentPreviewCore.tsx:600-655`），定位函数没有切换到批注记录对应的工作表。用户切换过 sheet 后点击旧评论，目标 cell 不存在于当前 DOM，滚动无法发生。两种情况都会让评论不能回到其保存的位置。

建议在定位时先切换到目标工作表，并为已保存的页内矩形显示可见标记或恢复选区。

## P2：调度尝试终态没有 compare and swap 保护

`src/octop/infra/db/repos/cron_attempts.py:20-31` 的 `update` 会无条件覆盖尝试状态，数据库更新也不检查当前 revision 或状态。`recover` 同样直接把所有 waiting 或 running 记录改为 `unknown`，且没有设置结束观测时间。若重启恢复与迟到的运行回调并发，或同一尝试收到乱序更新，旧的 `running` 或其他状态可以覆盖终态，页面会把已结束尝试重新显示为运行中。规格 9.7 要求重启后的未知状态与终态保持稳定。

建议通过 revision compare and swap 更新，并禁止终态被其他状态覆盖。

## 初版问题：详情面板不会显示定时任务的运行中变化（当前修复待行为验证）

初版快照中，`ScheduleBrowser.tsx` 只在 `last_run_at` 改变时读取 delivery attempts。当前树已改为定时刷新（可见时每 3 秒，隐藏时每 30 秒）并监听 `visibilitychange`，所以不再把“详情面板不会刷新运行中变化”列为当前缺陷；需在冻结版本以真实行为验证等待状态和执行状态是否可见。

建议在详情打开期间按可见状态轮询 attempts，完成后继续显示终态。

## P2：聊天摘要的下一次触发时间使用浏览器本地时区

`dashboard/src/pages/Chat/components/TaskActivity.tsx:42` 直接调用 `toLocaleString()`，没有传入调度记录的服务端时区。详情面板的 `ScheduleBrowser` 已传入 `item.timezone`，但聊天顶部摘要可能会按浏览器时区显示不同时间。仓库 `AGENTS.md` 明确要求用户可见时间戳使用服务端时区，规格 9.7 也要求实际时区与下一次触发一致。

建议复用详情面板的时间格式化函数，并传入当前最早 `next_run_at` 对应任务的 `timezone`。

## 滚动源码复核（尚未冻结）

当前工作树仍在变化，以下仅是新快照的复核提示，不是最终门禁结论：

- `src/octop/infra/execution/activity.py:150-159` 对所有超过 45 秒仍为 running/waiting 的 `job` 事件直接标记 stale。持续运行但仍可查询的后台 Job 因而会变 stale；需在最终版本验证是否修复。
- `dashboard/src/pages/Chat/components/ResourcePanelContent.tsx:128-143` 的页锚定位只滚动到整页元素，没有恢复已存储的区域矩形；sheet 定位只查询当前已挂载的工作表 DOM。`DocumentPreviewCore.tsx:621-624` 的工作表切换仍由本地 `excelTab` 状态控制，定位函数没有切换到批注记录中的 sheet。需验证跨工作表旧批注定位和页内矩形恢复。
- 当前 `DocumentPreviewCore.tsx:687-688` 用 `String.fromCharCode(65 + colIndex)` 生成列字母，超过 Z 后会产生错误列名；预览矩阵还会删掉空列，若未保留原始列偏移，保存的单元格锚点可能与源工作簿坐标不一致。需按原始工作簿列索引验证和修复。
- 初版记录的 attempt 轮询、attempt 分页、时区格式、活动历史分页、attempt 终态保护等问题在当前树已有代码修订。需以冻结指纹重新逐条检查，不沿用初版行号或结论。

## 验收状态

上述问题需在 coder 完成修复后复查。0034 的真实 UI 场景、Harness 集成、定时任务与自提醒视图以及最终 S1 至 S7 验收仍需以实际执行证据关闭。当前审查没有验证这些场景，也没有将其标为通过。

## 冻结子集复核（2026-10-19）

本轮仅复核任务工作台冻结子集与 Harness activity.3 append 安全门；文件/批注界面仍在实现，未检查。应用工作台文件指纹：`TaskActivity.tsx` `1f1d250a525921a1615cec7f993856efe23c6983`，`TaskActivityGraph.tsx` `c3a9da3ad5de32ea5d886d83adaabc3dbf121bd6`，`ScheduleBrowser.tsx` `0ce081a135758bc852822af1f7badaff722ce995`。Harness `agent.py` 指纹：`23ed393dc9e4633fff6bab331c6bca81b80e6597`，源码提交基线 `6636ce2c4fed85c92f37da66459a218ddf158aef`；activity.3 的验证记录见 `ops/workspace-0034/harness-activity-3/verification.md`。未运行测试或进行 UI 操作。

### P2：切换节点时迟到的详情/日志响应会写入新节点面板

`TaskActivity.tsx:94-104` 在节点变化时清空详情，但异步 `collaborationApi.detail()` 没有清理函数或请求身份检查；`105-136` 的 `logs()` 也无身份检查。复现：打开委派 A 的详情后，立即选择委派 B；若 A 的详情请求晚于 B 完成，A 的消息会覆盖 B 的 `detail`。点击“更多”读取 A 的旧消息页时再切到 B，响应回调会把 A 页追加到当前 B 的 `detail`。后台 Job 日志请求也会在切节点后追加到新节点的日志区。这样会把另一活动的公开对话/日志错误地展示在当前任务下；如果同一组件实例跨 thread 保留，旧会话内容也可能短暂出现在新会话面板。应在每次节点/会话变化时使旧请求失效，并让详情、翻页和日志更新均检查同一身份代次。

### P2：依赖图没有展示真实执行节点和执行者/进展

`TaskActivityGraph.tsx:32-34` 将计划节点与实际活动节点拆开；SVG 只在 `108` 行开始渲染 `plans`。实际 dispatch/Job 不绘制为 DAG 节点，`contains` 边也不绘制。所有活动都被列在可折叠“未关联活动”列表中，即使节点有 `dependencies_known=true` 且 `task_id` 已绑定到计划。复现：为计划任务 A 绑定一个正在运行的 dispatch，进入自动选择的图视图；图中只见合并过状态的 A 计划卡，找不到运行者或最新公开进展，真实活动要展开底部列表才能另行查看。规格 9.8 要求图节点呈现执行者与公开进展，并将未关联活动单独列出；当前图无法满足这个观察路径。

### P2：活动摘要在超过 200 条活跃来源时把部分计数显示成完整计数

服务端 `RunEventRepo.active(..., limit=201)` 与 `ActivityService.snapshot()` 最多纳入前 200 条活跃事件并设置 `active_scope_truncated`，其 `counts.subagents/jobs` 是当前构建出的部分节点计数。`TaskActivity.tsx` 摘要在 `342-349` 显示这些数字，却没有读取 `active_scope_truncated` 或标记计数不完整；截断提示只在工作台主体中出现。复现：同一会话有超过 200 条活跃来源，打开顶部摘要，会看到具体活动数而没有部分范围提示。摘要应显示不完整状态或采用能明确表达上限的计数文案，不能将窗口计数呈现为全量计数。

### P2：重复单击会收起摘要，与既有交互约束不符

`TaskActivity.tsx` 入口的鼠标单击定时回调（约 `399` 行）和键盘/触屏分支（约 `396` 行）都使用 `setSummary(v => !v)`。因此摘要打开后再单击一次就收起；反复按 Enter/Space 或触屏点按也会切换开关。0034 第 2.4 条既有要求为“首个单击只展开、不切换收起”。9.8 明确双击进入工作台，但没有撤销单击保持展开的行为。应让单击保持打开，使用 Escape、外部关闭或显式关闭控件收起；双击继续取消待执行的单击并直接进入工作台。

### Harness activity.3 append 门

只读复核 `agent.py:738-798`：pending 状态仅在 checkpoint 标记为当前精确的 `source=update`、append step 与 checkpoint step 相等、`state.next` 和 tasks 恰好等于公开图的 START targets，且没有 interrupt/error 时才允许追加。其余 pending/中断/失败状态会在 `aupdate_state` 前抛错；提交使用 `as_node=START`，避免多写节点的歧义。验证文档报告的中断、静态中断、失败、外部更新、重复追加和 SQLite 重开测试覆盖与该门相符。没有发现可从当前实现和证据确认的 Harness 缺陷。host 同线程串行化是该公共方法声明的前置条件，本轮未发现调用端违反证据。

### 其他边界观察

调度 API 对非所有者返回空列表，`ScheduleBrowser` 因而把无权限与空列表都呈现为空状态，且在有 `threadId` 时仍显示“本 Agent 全部”范围切换。后端没有泄露定时内容，属于权限状态解释不清的低优先级 UX 问题；建议调用端按现有 Agent ownership/capability 隐藏无权范围或显示不可查看提示，不应扩大 API 权限。窄屏任务详情返回按钮会复用列表 DOM，保留所选/滚动状态；本轮静态代码未发现该部分实质缺陷。

## 9.8.2冻结修复复核（2026-10-19）

复核对象：TaskActivity/TaskActivityGraph 9.8.2 冻结源码。`TaskActivity.tsx` SHA256 `5bc8a97128e814e2b55fbd53a49a112f6406e91be46ad05f833d8d771051a814`，`TaskActivityGraph.tsx` SHA256 `3755dac912f313a4128d481c700f4e5b9b2edac4b97cb54114b2a930c316f69e`。只读检查了实现与新增测试源码，未运行前端测试。代码复核确认详情/更多消息/日志、历史分页响应均检查节点或会话身份；历史分页的 `finally` 也只在当前会话更新 busy 状态。摘要与主体都显示 `active_scope_truncated` 提示，鼠标单击变成仅打开，键盘和双击行为仍可用。图递归沿 `contains` 搜索并按节点 ID 去重，当前过滤节点可被选中，超出三项可从“更多”面板进入；声明状态仍作为计划节点状态呈现，不进入图的 executor 子列表。

### P2：ask_agent dispatch 与 invocation 被作为两个 subagent 计数/显示

Harness activity.3 的 `RunEventCallback` 为 `ask_agent` dispatch RunEvent 写入 `dispatch_receipt.invocation_id`；同一 invocation 也由 `CollaborationService.listing` 返回。`ActivityService.snapshot` 在 `activity.py:166` 将 dispatch RunEvent 映射为 `type=subagent`，又在 `192-207` 为该 invocation 新建 `type=delegation` 节点。`259-263` 将两类节点都相加为 `counts.subagents`。因此一次 ask_agent 调用可被摘要计为两个 subagent；在没有 plan contains 绑定时，TaskActivityGraph `66-70` 也会把两个不同节点 ID 同时放入未关联活动列表。当前图的 BFS 去重只对相同节点 ID 生效，无法合并由相同 `invocation_id` 标识的两种投影。

应按 `details.invocation_id` 将 dispatch 与 invocation 合并为一个真实执行节点，或保留一个作为状态权威、过滤另一重复投影；保持其单一执行状态，不把计划声明状态作为另一次执行计数。本轮因此对该实质问题不通过。CUA `getState()` 返回浏览器因 Work 设置禁用，未进行真实 UI 视觉验证。

## 资源与实际场景状态补充（2026-10-19）

### P2（已在 9.8.3 修复）：上传文件来源变化后，修改请求仍可能入队

`src/octop/api/routers/chat/annotations.py:142-169` 在创建修改请求前调用 `FileSourceService.assert_current`，再准备并提交排队 turn。该检查仅处理 `execution` 与 `workspace` 来源（`src/octop/infra/documents/file_sources.py:33-49`）；上传资源未检查。`ResourceService.register` 会为上传来源保留 `legacy_path`（`src/octop/infra/documents/resources.py:246`），而读取内容时会在 `390-393` 检查别名文件仍与资源版本摘要一致。可复现步骤：登记一个带 `legacy_path` 的上传文件版本，改变对应工作区文件，再以旧资源版本提交批注修改请求。提交路径会跳过来源检查并将请求入队；Agent 随后读取源资源时才因摘要变化被拒绝，用户收到的是已经排队但无法处理的请求，而不是规格要求的版本冲突回执。

应在排队前对上传别名执行同样的当前版本校验，并将变化映射为明确冲突。当前没有看到覆盖此路径的回归测试。该结论是代码路径审查，未运行测试或实际 Agent 场景。

9.8.3 复核时，`FileSourceService.assert_current` 已对上传 `legacy_path` 重新读取并同时比较长度与 SHA256。`tests/unit/agents/test_workbench.py` 增加真实路由回归，覆盖别名未变时成功排队、已变或已删除时返回 `ANNOTATION_SOURCE_CONFLICT` 且不调用 queue、不留下修改请求。该先前 finding 已关闭。

### 9.8.3 后端收口复核

只读复核了 `src/octop/infra/execution/activity.py`（SHA256 `16fd3f48dd7baef44f9cb9b5eb6f7d033d5be0486e3704959ea085031bf386b5`）、`src/octop/infra/documents/file_sources.py`（SHA256 `8994ea251217f4670fd970e86666d991d463411a1fe6e997d098206ef602b2e8`），以及活动关联和批注请求回归。Job 关联要求真实 `job_start` tool receipt 的状态成功、相同 run/context/job ID，以及相同资源作用域中的唯一 producer；`job_status`、`job_logs`、`job_cancel`、歧义提交和跨 context/run/thread 的同名 Job 均不连边。ask_agent dispatch 只有在 owner 限定的 invocation 与 source agent/thread、scope thread、root run 全部吻合时才映射到稳定 invocation ID；调用的 task/attempt 与 source refs 和 contains 边保留，invocation 记录仍提供权威状态。映射完成后才计算并行 task 数。等待中的 accepted 节点计入 active invocation，但不计为 running 或并行运行。未发现新的后端 P1/P2。

已留存的目标日志 `.0034-983-pytest.log` 显示 47 passed，新增案例覆盖两条并行 Job 精确配对、跨 context/run/thread 拒绝、歧义不连接、installed Harness callback 到 App sink、ask_agent 单次计数与 task link、native task 独立保留、status 工具不冒充创建、以及 accepted 不冒充 running。该日志不是我本轮重新运行所得；更早 full3 的 4975 passed、157 skipped 明确早于 9.8.3，不能作为该修改的全量门禁。应用实际场景与 UI 验收仍开放。

### S1 至 S7 实际场景验收仍开放

规格登记的 S1 至 S7 仍没有一组完整真实 UI 与执行证据。当前 `docs/workspace-0034-coder-evidence.md` 报告的 full3 为 4975 passed、157 skipped；这是 9.8.3 投影修改前的结果，不覆盖正在进行的投影修复。代码测试不能证明真实文件保存冲突、超过 1 MiB 的远端预览与媒体跳转、批注请求经真实 Agent 工具产出结果、两个真实 invocation 与 Job 的监控、DAG 实际分叉汇合和恢复、响应式布局和视觉交互、真实调度器/自提醒触发。浏览器由 root 单独使用且后端正由 release 恢复，本轮未操控 UI，也未将视觉验收标通过。

### 9.9 定时详情与通知复核（2026-10-19）

本次只读检查了 `ScheduleBrowser.tsx` 与 `useDashboardPushToast.tsx`。最终 SHA256 分别为 `9a632eb60a8d0492b426795cdbb6a1a6964294345a665d1b7e6db78497edb168` 与 `03b0fa3e528f133e8800b773d78c9e9cee788ac48588dfc875455fdc15b759c4`，均与当前 `docs/workspace-0034-ui-freeze-sha256.json` 一致。未使用浏览器；这不构成实际通知或视觉场景验收。

### P2（已修复）：失败或异常调度状态被描述为一次任务“已结束”

最初版本对所有已过期日期任务，在有终态记录时都返回 `ended`，包含 `last_status: "error"`，并覆盖 `scheduler_stopped`。最终 `dashboard/src/components/ScheduleBrowser.tsx:544-562` 先保留非 `unregistered` 的当前调度状态；对未注册条目，失败记录显示 `last_failed`，只有有效且已到期的 date、无下一次运行、观察时间已到、成功 `last_status` 及触发至观察时间之间的 `last_run_at` 才返回 `ended`。`ScheduleBrowser.test.tsx` 增加了失败、scheduler stop、早于/晚于有效触发窗口、无效日期、自提醒耗尽等断言。Tab panels 也已补 `aria-labelledby`。最终源码与 manifest 哈希一致；未复现新的实质问题。

通知路径检查结果：可见当前会话的 push 仍刷新 sidebar/history，并在打开通知前按 `agent_id + thread_id` 抑制当前会话 toast；导航/标签页恢复时只清理该会话跟踪的 notice keys，后台和其他会话通知保持。`useDashboardPushToast.test.tsx` 覆盖当前会话抑制、其他会话保留和后台恢复后定向清理。自提醒目的只读取 `meta.purpose`，再按规格移除 `self-check:` 名称前缀；普通任务使用原名，未从 prompt 推断目的。Tab 使用原生 button，并以稳定唯一 ID 关联 `tab` 与 `tabpanel`；左右方向键与 roving tabindex 尚未实现，保留为低优先级可访问性增强。root另行实际检查了375x812视口内对话框及关闭/返回可达性，但这不代表1390/894/375全部场景或S1至S7已通过；后者仍开放。

## S1/S3 接缝证据补充（2026-10-20）

### S1：restricted 设备被送入 owner-only 原生文件面板

最新 runtime API 探针确认目标设备在线且 `trust_mode=restricted`，对其执行原生 `fs.list` 返回 403。代码路径与该结果一致：`DeviceTargetSelect.tsx` 的候选列表包含全部未撤销设备；执行工作台的 `workspace` surface 无条件渲染 `NativeDeviceFiles`，该组件通过 execution context 调用 `fs.list`。服务端仅允许 `owner_trusted(row)` 使用 `fs.*`（`src/octop/infra/devices/service.py` 的 `authorize`）；`ExecutionService.resolve` 则允许已绑定可读 shared root 的 restricted 设备形成 context。因此该错误配置可由公开会话选择路径到达，是本次 S1 原生文件面板不可读的已确认根因，不应提升测试设备信任级别来绕过。

受限设备已有独立的 root-scoped `files.*` 能力：设备管理页根据 `trust_mode` 显示 `RestrictedDeviceFiles`，其列表/读取请求携带 `root_id` 并由 root 权限约束。聊天工作台目前没有把此路径用于其 restricted context。按最新 9.9.1 决策，应让文件面板按当前 context 复用受限 root UI；沿 context 读取准确设备 roots/local target，遵守 ask/plan 写保护，禁用跨设备传输，并在 scope 切换时丢弃迟到请求及旧 Blob。该修复仍待 coder 冻结与复核，尚未实现/验收。`executionApi.call` 解包服务端 `result`，device transport 的失败帧转为异常，NativeDeviceFiles 也会进入 error 状态；这些层未将 403 静默映射为成功空目录。

### S3：离线回放只验证工具调用链，不验证真实发布

`ops/workspace-0034/test_scripted_openai_provider.py` 使用真实 `AnnotationService.prepare_request` 文本和真实 `read_attachment` 工具，校验 `ReadResource`、`WriteFileSchema`、`PublishResource` 参数，并执行写入隔离的临时文件。末尾构造的 `{"status":"published"}` ToolMessage 只用于让 deterministic provider 结束该轮回放；测试随后断言原始资源未变、批注仍 open，并未调用真实 `publish_artifact`、`ResourceService.publish` 或验证请求完成状态。因此这条测试可证明 provider 在该 toy comment 下发出绑定真实 request ID 的正确工具参数并终止，但不能作为发布成功、结果入库或 request/run 关联的证据。它没有把真实发布失败伪装成成功；真实 S3 队列、运行和发布结果仍需由后续公共 API 场景证据关闭。

### P2：restricted 上传在 scope 切换时可遗留未完成 upload

`dashboard/src/pages/Devices/DeviceFiles.tsx:218-229` 在 root/path 变化或 keyed component 卸载时 abort 当前请求并清空 `controller.current`。若 `files.write_begin` 或某个 `files.write_chunk` 已成功返回、但用户此时切换 execution context/work mode（其 key 会重挂组件），旧 upload 的 catch 到 `:296-306` 时会先因 `controller.current !== abort` 返回，跳过以旧闭包 execution context 调用 `files.write_abort`。此时最近一次设备操作已经完成，设备端不会再因该操作的取消清理该 upload；`DeviceExecutor` 将 upload 清单写入 `uploads.json`（`src/octop/infra/devices/executor.py:636-648`），并对活动 upload 数设 16 个上限（`:1121-1126`）。反复在成功 begin/chunk 回执后切换 scope 可留下临时上传并耗尽新上传名额。已有回归只覆盖同一 context 中 chunk 失败时触发 abort，未覆盖成功回执后 scope 切换。修复应以原 context ID 做 best-effort abort，不能把旧 upload ID 发往新 context；并补该切换时序回归。此 finding 基于冻结源码路径分析，未实际运行该竞态。

9.9.1 后续冻结修复复核关闭该 finding。`DeviceFiles.tsx` 最终 SHA256 为 `00475155e838ada48cddd836f7cf3ab47e6245a6093731b3ff0d03b1687b74e6`，9 文件 manifest 中每项均与工作树匹配。上传在检查取消前先保存 `write_begin` 回执中的 upload ID；异常/取消时以闭包捕获的 adapter 发 `files.write_abort`，而新 UI state 的更新仍受 controller 身份检查保护。若旧 context 已撤权，清理失败仅 best-effort，不转发到新 context。新增 deferred begin、首 chunk 成功/第二 chunk 挂起后切 context、旧 context revoke 导致 abort 失败三项回归检查均验证 abort 使用旧 context 与旧 upload ID，且新 context 只执行 listing、不受旧 catch 更新。coder 提供 15 focused tests、相关 ESLint、TypeScript exit 0；这些门禁未由本轮重跑。无其他 P1/P2。S45 目前只有离线 provider 回放（8 passed）的 coder 证据，未在真实 target/环境运行，不作为执行场景验收。未做真实浏览器视觉验收。
