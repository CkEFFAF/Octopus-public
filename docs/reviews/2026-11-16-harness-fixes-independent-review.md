# Harness 修复独立复查，2026年11月16日

**结论：通过代码复查。当前检查范围内没有遗留的阻断或重大问题。**

复查由未参与实现的独立代理进行，未声明跨模型保证。仅对代码与相关测试进行只读审查，未修改实现或回归测试。本报告不是生产部署验收，完整发布检查由主线程另行记录。

## 范围

基线为 `output/harness-audit-20261116`，对应已验证的 `1.0.2.post4.dev6+cache.1` 源码。修复位于 `output/harness-fixes-20261116`。

检查了六个 Harness 运行时模块：

* `src/octop_harness/middleware/memory.py`
* `src/octop_harness/compaction.py`
* `src/octop_harness/agent.py`
* `src/octop_harness/builtin/tools/web_fetch.py`
* `src/octop_harness/mcp.py`
* `src/octop_harness/__init__.py`

同时检查应用的 `src/octop/infra/agents/manager.py` 中 `call()` 的新增会话锁，以及 `src/octop/infra/connectors/gateway/langchain.py` 的 Schema 和参数传递适配。检查了相关新旧测试及 README 的迁移说明。未复查工作区内无关的 MCP 作用域、前端、设备等已有修改，也未复查最终 wheel 打包产物。

## 审查中发现并已修正的问题

初版网页流式读取仍在 HTTPX 完整解压一个网络块后才检查长度，因此不能兑现解压正文的内存上限。

独立离线复现：将 24 MiB 文本压缩成一个 24,482 字节 gzip 块，配置正文上限为 1 KiB。初版实现虽然返回超限错误，但 `tracemalloc` 峰值约 56,007,523 字节。该块足够小，可以放进一个普通网络读取块，并非依赖不现实的巨大原始块。

作者随后改为读取原始数据，并对 gzip、zlib 和原始 deflate 进行有输出上限的解压。请求明确列出支持的编码，其他或叠加编码返回可恢复的解码错误。尾部数据和已经结束的解压器也受到检查，防止 `unused_data` 积累或静默截断。

独立对相同 gzip 数据重新执行，峰值为 68,436 字节，超限按预期报错。当前网页限额测试包含该压缩块、解压后大小边界、拆开的 deflate 头、重定向正文不读取、连接关闭以及尾部数据检查。此问题已解决，没有保留为待修复项。

## 最终实现评估

记忆游标改为私有图状态，不再以操作系统线程编号关联异步调用。真实图测试覆盖不同会话交错、同一父图并行子图，以及取消后使用新中间件恢复检查点。游标在正常采集后清除，输出中不暴露该内部字段。

手动压缩复制中间件及其摘要 helper，不再跨异步等待修改共享模型和 keep 设置。复制保留原有后端、自定义提示、trim 和会话路径。模型调用、checkpoint 更新和回执处理处于 invocation 生命周期内；完成和取消时延迟释放资源。宿主上下文与 recall 采用与模型投影一致的重放后计数方式。

MCP 保留服务器提供的 JSON Schema，不再把对象和数组编译成字符串。名称分配先保留合法名字，再按原名排序分配清洗后的名称，避免已有合法名字与清洗结果碰撞。真实 StructuredTool 调用和模型绑定测试覆盖嵌套值、引用、约束、保留字段名、别名及显式 nullable 值。

共享参数处理只省略可确定为非 nullable 的可选 null，不把未知 Schema 当成拒绝 null。对组合根 Schema 的检查没有发现合法 null 被错误删除的案例。服务器仍负责完整参数校验，测试和文档没有宣称保留客户端完整 JSON Schema 校验能力。

应用 `call()` 使用 stream 和 HITL resume 已采用的会话锁，锁粒度保持为 agent 与 thread。相关测试证明已有写入锁会阻止 call，独立会话仍可并行，等待和执行中的取消不会残留持有锁。

## 独立验证

运行环境均显式设置 `PYTHONPATH` 指向修复源码，并加载原审查目录中的 `audit_offline` 插件，禁止向非回环地址建立 socket 连接。未调用真实模型、外部服务或 prompted ACP。

| 独立检查 | 结果 | 日志 |
| --- | --- | --- |
| 记忆隔离、压缩隔离、关闭生命周期、MCP 保真和核心行为、网页限额 | 67 通过 | `output/harness-fixes-20261116/reviewer-targeted-final.log` |
| 应用会话锁与进程内 MCP gateway 参数保真 | 5 通过 | `output/harness-fixes-20261116/reviewer-app.log` |
| 最终网页限额测试，包含尾部数据检查 | 12 通过 | `output/harness-fixes-20261116/reviewer-web-final.log` |
| 单 gzip 块解压内存复现 | 修复后超限报错，峰值 68,436 字节 | 本次复查工具输出 |

这些测试存在覆盖重叠，不将数量相加作为不同测试总数。初次独立测试曾读到正在修改中的网页测试版本，最终复测以上表结果为准。完整 Harness、应用 gate 和 wheel 一致性由主线程执行，不作为本报告独立重跑的证据。

## 兼容性与范围限制

`mcp_args_model()` 保留导入名称，但返回值从 Pydantic 类改为 JSON Schema 字典。这是有意的接口迁移，README 已说明，仓库中调用方已适配。依赖该工具函数的外部调用方若仍调用 `.model_validate()` 或 `.model_json_schema()`，需要同步迁移。

网页抓取当前支持 identity、gzip 和 deflate 的单个编码流。其他编码或叠加编码返回清楚的解码错误，未尝试提供不受控的通用解压路径。

原全面审查中的后台任务容量、事件循环阻塞、锁回收、硬预算、DNS 校验与实际连接之间的间隙、公开恢复 API 等后续工作不属于本次八个已复现问题的修复范围，不能据本次通过结论宣称这些项目也已解决。
