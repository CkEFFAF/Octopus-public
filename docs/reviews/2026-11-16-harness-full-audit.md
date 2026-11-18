# Harness 全面审查，2026年11月16日

后续状态：本报告的 8 个已复现问题已修复，验证与产物见 [修复验证记录](2026-11-16-harness-fixes-validation.md)。其余建议仍按本文区分为后续设计或验证项目。

结论：现有运行时的常规回归基础较好，但仍有并发隔离、MCP 协议保真和资源上限方面的缺口。优先修复记忆游标、共享压缩策略和 MCP Schema 转换，再补齐调用串行化、压缩生命周期和下载限额。无需先重写整个 Harness。

本报告是本地代码与离线回归审查，不是生产验收或部署批准。没有调用真实模型，没有 prompted ACP 测试，没有运行 GPU 实验，没有启用任何计划。未修改应用或 Harness 运行时代码。

## 版本与证据范围

应用目录：`D:/Agent_Workspace/octopus1/innovation-work`。

分支：`feature/mcp-four-scopes-20261115`，HEAD：`afcac0adae55befef29859a6fedfd05619f4e4ed`。审查包含当前工作区的未提交集成代码，不把 HEAD 当作完整运行代码。

实际依赖：`1.0.2.post4.dev6+cache.1`。

核对结果：

* wheel SHA256 与 `vendor/harness/cache-source-manifest.json` 一致，值为 `4d3182ba3ce98a81afe7dc67e80bdb5df7e1c70762fddc220a910edea3f0cd46`。
* 源码包 SHA256 一致，值为 `efc0c3f2f4597488daacb62c2b7845f03d9ee6135a50e48f5945f079b037cb26`。
* 应用虚拟环境已安装包的 371 个运行时资源全部与 manifest 匹配。
* `innovation-harness` 已经是 `dev7+transport.1`，与锁定源码相比有两个 Python 文件差异，不能直接替代本次基线。

为避免误审较新源码，从已验证的 `harness-source.zip` 提取了独立副本：
`D:/Agent_Workspace/octopus1/output/harness-audit-20261116`。

下文 Harness 文件位置均相对此副本；应用文件位置相对 `innovation-work`。

## 验证结果

| 验证 | 本次结果 | 说明 |
| --- | --- | --- |
| 锁定源码的完整 Harness 测试目录 | 1886 通过，31 跳过，68.06 秒 | 149 个测试文件，包含运行时、协议、后端、权限、记忆、压缩、ACP 与协作等回归 |
| 应用集成单元测试，9 个文件 | 67 通过，10.64 秒 | response recovery、retry、quota、context、steering、MCP cache、live configuration、archive buffer、usage |
| 新增审查复现 | 8 通过，5.29 秒 | 断言当前错误行为存在，不表示问题已修复 |
| 运行时 artifact 一致性 | 通过 | wheel、archive、安装成员哈希 |

所有测试加载 `audit_offline` 插件，禁止 Python socket 向非回环地址连接。真实 PostgreSQL、Linux 专属语义和其他可选环境的跳过不算验证通过。没有测量生产吞吐或模型响应质量。

日志和独立复现位于上述 output 目录：`harness-tests.log`、`app-tests.log`、`finding-probes.log`、`test_audit_findings.py`、`audit_offline.py`。复现仅使用 mock、本地状态和内存传输。

没有运行 `make all`，它会先格式化并修改现有工作区。本次是检查任务，未交付代码修改；也未声称通过发布门槛。

## 已复现的问题

### 1. P1，异步并发会话会互相覆盖记忆采集游标

位置：`src/octop_harness/middleware/memory.py:223`、`:274`、`:321`、`:368`。

`_cursors` 按 `threading.get_ident()` 保存消息数量。异步 `abefore_model` 和 `aafter_model` 直接调用同步实现，因此多个会话通常使用同一个操作系统线程编号。A 调模型等待时，B 的 before hook 覆盖 A 的游标。A 返回后可能完全不记录答案，或者 B 返回时从零重新采集旧消息。

复现：A 的输入有 1 条消息，B 有 3 条。按 A before、B before、A after 交错，A 完成后的采集次数为零。无需真实模型即可重现。

建议：使用调用级身份保存游标，至少包含会话、checkpoint namespace 和模型调用标识；优先把必要状态放在调用上下文或图状态里。不能只换成单独的 `thread_id` 后假定并行子图不会再碰撞。

验收：不同会话、同一父会话的并行子代理、取消后重试都各自只采集一次，旧历史不会重新采集。

### 2. P1，手动压缩修改共享摘要中间件，交错后会残留错误模型

位置：`src/octop_harness/compaction.py:151`、`:337`。

`_force_policy` 在共享 `_lc_helper` 上临时修改 `keep`、`model`、`_summary_model`，跨异步等待期间一直保留这些改动。不同会话共用同一个 Harness 图时，压缩或自动摘要可能读到另一个会话的配置。

复现：A 和 B 依次进入策略上下文，然后 A、B 依次退出，最终 helper.model 为 A 的模型，原配置没有恢复。B 尚在执行时，A 退出也会提前替换 B 的配置。

建议：手动压缩创建独立 helper，沿用后端和会话标识，不原地改共享对象。单个会话的锁不足以解决跨会话共享对象的问题。

验收：两个会话选择不同摘要模型并发压缩，两个请求都使用自己的模型，图的自动压缩策略全程保持原值。

### 3. P1，MCP JSON Schema 转换会拒绝合法对象和数组

位置：`src/octop_harness/mcp.py:133`、`:442`。

`mcp_args_model` 仅识别 integer、number、boolean，其余一律成为字符串。原始对象、数组、联合类型和 `$ref` 的语义因此丢失，enum、约束和嵌套结构也没有完整保留。后处理会实际用这个模型替换原始字典 Schema。

复现：原 Schema 要求 `payload: object` 和 `items: array[integer]`，传入符合原 Schema 的 `{'payload': {'x': 1}, 'items': [1, 2]}` 被转换后的模型拒绝。

此外 `_prepare_tool_arguments` 无条件删除 None，服务明确接受 null 时也不能忠实传递。现有“省略可选 null”的兼容策略需要按 Schema 区分，不能覆盖合法 null。

建议：优先保留适配器支持的原始 JSON Schema，只针对确实有问题的字段做局部兼容。若必须生成模型，需要完整类型映射和保真测试，避免自行维护不完整的 Schema 编译器。

验收：对象、数组、enum、联合类型、引用、别名、required nullable 和 optional absent 都与原始 MCP 服务语义一致。

### 4. P2，MCP 名称去重有顺序依赖

位置：`src/octop_harness/mcp.py:365`。

名称已经合法时直接加入 `used_names` 并继续，不检查它是否与前面清洗出来的名称重复。

复现：`svc.a` 后接 `svc_a`，最终两个工具都叫 `svc_a`。反向顺序的结果不同。

应用的自定义 MCP 哈希别名减少跨服务器碰撞，但如果 Harness 已把同一服务器两个工具变成相同名称，之后按服务器和名称计算哈希也无法恢复区分。

建议：先收集所有原名，再建立稳定的唯一映射，所有名称都经过同一个冲突检查。错误提示和调用回执保留原始服务及工具身份。

验收：交换加载顺序不会改变身份或产生重名，名称清洗后仍能调用正确工具。

### 5. P2，应用非流式调用绕过会话执行锁

位置，应用：`src/octop/infra/agents/manager.py:1359`、`:1406`、`:1425`。

stream 和 HITL resume 使用 `_thread_execution_lock`，call 只有生命周期计数。同一个 agent、thread 的 call 可以同时进入 Harness，也可以与受锁保护的 stream 重叠。

复现：调用真实 `AgentManager.call` 方法，提供只阻塞等待的 fake Harness，两个相同 thread 的调用均进入了底层。该复现证明缺少串行化，不把 checkpoint 丢失作为已完成的端到端复现。

建议：stream、call、resume、recovery、append、compact、delete checkpoint 使用一致的会话写入规则。继续允许不同会话并行，避免扩大成全 agent 串行锁。

验收：相同会话所有写操作按序执行，不同会话互不阻塞，停止和重载没有死锁。

### 6. P1，web_fetch 的 5 MiB 上限在完整下载后才生效

位置：`src/octop_harness/builtin/tools/web_fetch.py:24`、`:40`。

`client.get()` 默认读取完整响应，随后 `_response_body_as_text` 才检查 `response.content` 长度。该上限限制了返回文本，无法限制下载过程的内存消耗，重定向响应也经由相同读取路径。

复现：使用 httpx.MockTransport 提供七个 1 MiB 数据块，抓取先把七块全部消费并留在内存，之后才返回超过上限的错误。

建议：使用流式读取，在累计解压后的正文超过上限时立即关闭连接；Content-Length 只能预筛选。限制重定向响应体，保留既有逐跳 URL 校验。

验收：超限 chunked、压缩响应和重定向响应都能提前停止，连接被关闭，内存不随服务器正文无限增长。

### 7. P2，手动压缩没有加入运行时生命周期保护

位置：`src/octop_harness/agent.py:892`、`:1087`。应用调用入口：`src/octop/infra/gateway/slash/handlers/composite.py:103`。

call、stream 和 resume 会进入 `_invocation()`，手动压缩没有。压缩在读取、摘要和写 checkpoint 时，关闭逻辑可能把运行时判断为空闲。

复现：暂停真实 `acompact_conversation` 在摘要等待点，`_in_flight` 仍为 0，`_defer_close_while_busy()` 返回 False。证明关闭保护遗漏，不声称本次实际破坏了数据库。

建议：压缩也纳入 invocation 保护，并与会话写入规则一起处理。原始 `stream_events` 同样需要明确由谁追踪整个返回流的生命周期，不能只包裹创建流对象的瞬间。

验收：压缩过程中发起重载和 shutdown，资源在操作结束或明确取消后释放；关闭完成后不能重新进入旧 runtime。

### 8. P2，手动压缩的 token 估计遗漏宿主上下文快照

位置：`src/octop_harness/compaction.py:261`、`:297`、`:298`。

自动 token counter 已经重放 recall 和 host context snapshots。手动压缩计算 removed、before、after 时只重放 recall，device、task 等宿主上下文不参与同一口径的估计。随后 `shrink_snapshot` 使用这个差值，界面使用量可能偏离实际请求。

复现：HumanMessage 只有很短的正文但附带大量宿主上下文，完整 counter 比手动压缩的 before estimate 多出超过 1000 个 token。

建议：提取统一的模型请求投影计数入口，自动压缩、手动压缩、context breakdown 都使用它，并明确工具 Schema、系统消息和图内摘要的计数范围。

验收：有 recall、host snapshot、附件和摘要的同一状态，各展示入口差异有明确说明且符合预期。

## 代码确认的改进项，尚未做端到端故障复现

### 9. 记忆异步 hook 仍可能阻塞整个事件循环

位置：`src/octop_harness/middleware/memory.py:368`、`:371`。

异步 hook 直接执行同步 recall 和 JSONL 写入。数据库、远程 recall 或文件系统变慢时，同进程其他会话和取消控制也可能受影响。本次未测量真实服务延迟。

建议：先修复游标隔离，再把实际阻塞操作移出事件循环，明确超时及取消语义。记录 recall 和 JSONL 的延迟与失败计数，不能仅因方法声明为 async 就视为异步 I/O。

### 10. 后台记忆采集和协作队列需要真正的容量限制

位置：`src/octop_harness/middleware/memory.py:99`；`src/octop_harness/teams/inbox.py:96`、`:279`、`:295`。

记忆 `_BackgroundExecutor.submit` 每次启动一个 daemon 线程，并非固定大小线程池。进程退出可丢掉尚未完成的采集。

Inbox 队列无大小上限，worker 为每条消息创建 task，随后 task 才等待 semaphore。`max_concurrency` 限制实际执行数，没有限制等待任务数。shutdown 对 worker 有 30 秒限制，对全部工作 task 的 gather 没有对应期限。

建议：设置队列容量、在创建执行任务前取得容量，并明确超载时的拒绝或排队反馈。需要可靠采集时使用可追踪的提交和有限 drain；不要仅靠 daemon 线程承担持久化保证。

### 11. 会话锁需要安全回收

位置，应用：`src/octop/infra/agents/manager.py:407`、`:1016`。

`_thread_execution_locks` 只创建和读取，没有回收路径。长时间服务接收很多不同会话会持续持有锁和字符串键。

建议：使用带持有者与等待者计数的锁注册表，最后一个引用释放时清理。不要直接按 LRU 删除正在持有或等待的锁，否则会让同一个会话出现两把锁。

## 需要进一步设计或专门验证的项目

1. **抓取的 DNS 检查与实际连接之间存在间隙。** `security/ssrf.py:70` 验证解析结果后返回原 URL，`web_fetch` 的独立 httpx 连接仍会重新解析。建议验证 DNS rebinding、代理和连接复用场景，必要时绑定已验证目的地址并保留 TLS 主机校验。本次没有复现真实内网访问，不将其写成已确认的生产利用。
2. **预算从回合准入升级为调用级约束。** 应用 `middleware/token_quota.py:45` 只在 before_agent 检查累计额度，`users/resource_policy.py:252` 是读取后判断；多个并发回合和一个长工具循环仍可能超额。当前暂停属于操作要求，不能据此假定额度中间件是硬预算。建议按需要设计预留、逐次结算、重试与子代理的统一预算，并计入摘要调用。此项是能力改进，不把现有回合准入语义误报成实现错误。
3. **取消与 MCP 发现失败分开。** `mcp.py:238` 捕获整个 BaseExceptionGroup，可能吞掉携带取消的组；发现过程按服务串行进行。建议用本地 fake transport 验证取消传播、逐服务期限和有界并发，避免增加不受限重试。
4. **减少宿主对私有实现的依赖。** 应用 `response_recovery.py` 依赖 `_prepare_call`、`_invocation`、`_stream_with_steering` 和协议 `_project_chunk`。建议提供公开的 model checkpoint resume、history append 和调用控制 API，添加 artifact 级契约测试，不在一次修复中改写整个宿主层。
5. **建立可重复性能基线。** 已有 schema 缓存、history 合并、固定标签指标和不可变前端快照，不建议重复实现。补测固定历史长度、并发会话数、工具数下的首事件时间、事件循环延迟、内存峰值、归档写放大和 checkpoint 增长。模型暂停期间用 FakeChatModel 和本地 transport；不声称已有吞吐改善数字。
6. **把新风险转成长期回归。** 当前 1886 个常规测试全绿但未阻止上述交错问题。优先增加实际异步交错、取消、重载、进程重启及 SQLite/PostgreSQL 等价测试；PostgreSQL 和 Linux 验证应在可用环境单独执行。

## 建议实施顺序

第一批：修复记忆游标、独立压缩 helper、MCP Schema 和名称映射。验证本报告复现从“错误存在”转为“正确行为成立”，再运行完整 Harness 与应用回归。

第二批：统一会话写入与生命周期保护、流式下载限额、统一 token 估计。补做取消和重载测试。

第三批：后台容量、锁回收、预算与公开恢复 API。每项单独给出行为约束和验证，避免扩成整体重构。

进入发布时仍需 `make all` 和相应平台检查。本次检查没有发布、提交、推送或部署。
