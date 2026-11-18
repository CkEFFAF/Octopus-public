# Harness 修复验证，2026年11月16日

本次修复全面审查中已复现的 8 个问题，基于应用实际锁定的 `1.0.2.post4.dev6+cache.1`，生成本地集成版本 `1.0.2.post4.dev8+reliability.1`。没有混入 `innovation-harness` 的 `dev7+transport.1` 改动，没有修改生产部署、设备服务、实验开关或任务队列。

原审查：[全面审查](2026-11-16-harness-full-audit.md)。独立复查：[修复独立复查](2026-11-16-harness-fixes-independent-review.md)。

## 改动与回归

| 原问题 | 修复 | 验证 |
| --- | --- | --- |
| 1，记忆游标交叉覆盖 | 游标改为私有 checkpoint 图状态，完成后清空 | 真实图并行会话、共享中间件的并行子图、取消后换新中间件恢复 |
| 2，共享摘要策略被并发覆盖 | 每次手动压缩复制中间件及其摘要 helper | 并行操作各用自己的模型和 keep，原对象保持不变，自定义 prompt/backend/session 保留 |
| 3，MCP Schema 和 null 丢失 | 原样保留 JSON Schema，只省略明确不接受 null 的可选空参数 | 对象、数组、引用、约束、保留名称、nullable、别名、真实 StructuredTool 调用及模型绑定 |
| 4，名称清洗碰撞 | 预留合法名称，再按原名稳定分配唯一清洗名 | 改变加载顺序，工具映射仍稳定且唯一 |
| 5，call 绕过会话锁 | 使用 stream/resume 已采用的 agent/thread 锁 | 已有写入锁阻止 call、不同会话并行、取消等待或执行释放锁 |
| 6，下载后才限额 | 原始响应流有界读取，对 gzip/deflate 有界解压 | 超限即停止、不读重定向正文、关闭连接、解压后边界、单块压缩炸弹、尾部数据拒绝 |
| 7，压缩未保护生命周期 | 手动压缩全程进入 `_invocation` | 摘要等待期间关闭，完成或取消后才释放实际 SQLite 连接 |
| 8，压缩估计遗漏宿主上下文 | 与 recall 一起重放宿主快照再计数 | before、after、removed 估计包含宿主快照 |

进程内 gateway 同步使用公开 `prepare_mcp_tool_arguments`，避免另一条工具路径仍删除合法 null。应用其余现有未提交改动保留。

修复前证据保留在 `D:/Agent_Workspace/octopus1/output/harness-fixes-20261116` 的 `memory-red.log`、`compaction-red.log`、`mcp-red.log`、`web-red.log`、`app-lock-red.log`。修复后对应回归断言正确行为，原审查中“错误存在”的探针不作为修复后的通过标准。

## 检查

Harness 与 wheel 检查加载原审查目录中的 `audit_offline`。最终应用检查使用 `audit_local_network`，允许回环及本机已分配网卡地址，禁止 Python socket 向外部建立 TCP 连接或发送 UDP 数据。UDP connect 只用于读取本机路由，不发送数据包。没有真实模型请求、prompted ACP 或 GPU 实验。

| 检查 | 结果 |
| --- | --- |
| Harness `make all` | 1912 passed，31 skipped；Ruff lint/format 通过，严格 mypy 检查 194 个源码文件通过；之后仅补充一个 recall 失败回归，已包含在完整 wheel 测试中 |
| 最终应用 `make all` | 5703 passed，157 skipped，20 warnings，848.39 秒；format-all、Ruff lint/format、严格 mypy 检查 764 个源码文件通过 |
| 最终安装 wheel 的完整回归 | 1913 passed，31 skipped，58.49 秒；独立安装目录导入，外部依赖沿用应用环境 |
| wheel、源码归档、依赖锁、安装成员一致性 | 通过；本地冻结安装完成，371 个运行时文件与 manifest 相同 |
| 独立复查 | 通过；没有遗留阻断或重大问题，初版 gzip 分配问题已修正并独立复验 |

Windows 上使用已有 GNU Make 与 Git Bash 运行真实 Makefile，`SHELL=C:/Program Files/Git/bin/bash.exe`。Harness 的 RUN 为 `uv run --project D:/Agent_Workspace/octopus1/innovation-work --no-sync`，显式 PYTHONPATH 指向修复源码。应用 RUN 为 `uv run --no-sync`，最终测试并发设为 `PYTEST_JOBS=3`，使用 worksteal 调度以缩短慢集成用例的尾部等待。没有跳过 format、lint、typecheck 或非 live 测试。日志保留为 `harness-final-make-all.log`、`app-final-make-all.log`、`wheel-tests-final.log`。

第一次应用完整运行是 5701 passed、157 skipped、2 failed。两项失败均为设备本机传输测试，被审查插件“不允许非回环地址”的过严策略拦截。修正测试防护后，两项原样重跑通过（`local-network-retest.log`），没有为此修改应用业务代码。初次日志 `app-make-all.log` 保留，最终完整重跑另行记录。

平台或可选服务跳过不算通过。没有对真实 PostgreSQL、Linux 专属行为、真实模型质量或生产吞吐作出验收结论。

## 可审查与重建的产物

应用仓库保留：

* `vendor/harness/octop_harness-1.0.2.post4.dev8+reliability.1-py3-none-any.whl`。
* `vendor/harness/reliability-source.zip`，包含匹配源码、完整测试、构建配置与依赖锁。
* `vendor/harness/reliability-source-manifest.json`，记录 wheel、源码包、补丁和逐成员哈希。
* `vendor/harness/reliability-fixes.patch`，对原 cache.1 源码包的完整差异。

`pyproject.toml` 与 `uv.lock` 指向仓库内的新 wheel，sdist 显式包含新产物，vendor 忽略规则已加入精确例外。原 wheel 和 `harness-source.zip` 未覆盖，历史 manifest 仍可核对。

wheel 只改动六个运行时模块：`__init__.py`、`agent.py`、`compaction.py`、`mcp.py`、`builtin/tools/web_fetch.py`、`middleware/memory.py`。应用代码只增加非流式调用的会话锁，以及 gateway 的 Schema 与空值策略适配。

## 兼容性与边界

`mcp_args_model()` 保留导入名，但返回完整 JSON Schema 字典。项目调用方已调整；外部依赖此 helper 返回 Pydantic 类的调用方，需要改为使用 Schema 字典和服务端校验。迁移说明和新公开 helper 已写入 Harness README。

网页抓取请求 identity、gzip、deflate。未声明的其他编码、叠加编码及压缩流尾部数据返回可恢复错误，避免引入不受限解压路径。

原审查中的后台容量、事件循环阻塞、锁回收、硬预算、DNS 与连接绑定、公开恢复 API 和性能基线仍是单独的后续设计项，本次没有把它们标为完成。

上述离线修复阶段没有提交、推送、发布或部署。用户随后授权提交部署，部署合并范围见 [部署变更说明](2026-11-16-harness-deployment.md)。模型与实验暂停继续保持。

维护说明已通过 sync 同步到应用及归档源码的 `AGENTS.md`，仅补充固定依赖来源、完整 MCP Schema、私有记忆游标和压缩隔离约束。没有变更范围清单或 spec 状态，没有新增工具依赖。
