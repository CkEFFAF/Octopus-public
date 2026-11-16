# Harness 部署变更说明，2026年11月16日

用户授权提交和部署此前确认的 8 项 Harness 修复。本次提交只含可靠性修复、依赖产物、测试和维护说明，原工作区已有的 MCP、设备、浏览器账号切换和前端改动不并入此次提交。

## 线上基线与合并

部署前实际服务为 `octop-hub`，运行目录 `/root/octopus-deployments/mcp-plugins-scopes-20261115`，MainPID `1619969`。数据目录为 `/root/OctopData`。线上应用包含未在本地旧 HEAD 中的修复，因此候选从实际活动源码复制，保留原 SPA、MCP 作用域、设备策略和其他线上改动，仅叠加本次应用会话锁、gateway 参数适配及新 Harness 依赖。

线上实际 Harness 为 `1.0.2.post4.dev7+transport.1`。其 371 个运行时成员与部署时的 manifest 一致；wheel 和完整源码归档的哈希也匹配。dev7 相对本地最初 cache.1 基线增加两个传输模块，保留有限连接等待和 SDK 重试策略。

因此此前本地验证的 dev8 不直接覆盖线上。最终部署依赖为 `1.0.2.post4.dev9+reliability.2`：

* 保留线上 dev7 的 `llm/factory.py`、`llm/session_header.py` 及两份传输测试原始字节。
* 相对 dev7 只变更六个已复查的可靠性模块，完整保留 dev8 修复及测试。
* source archive、wheel、可读补丁、成员哈希与应用依赖锁一并提交。

| 产物 | SHA256 |
| --- | --- |
| dev9 wheel | `4d8063b351614a8b5f45f8e59cbf664b7555dc785eab5c296cc0cf3366102815` |
| reliability2-source.zip | `9410615ebf7124439281f393037b399719eb5d5f5916ed76aa9f6e95e459ce74` |
| reliability2-fixes.patch | `277f8bd4e00c6c588fb16f9ad09bafbf6c54d06013a916886300eab1247411da` |

原 dev8 产物保留为本地审查历史。dev7 只使用通过哈希核验的 wheel、源码归档及其原 manifest 作为基线；旧服务器上的独立 transport 补丁与该历史 manifest 的补丁摘要不一致，没有将其作为应用或重建依据。新 dev9 补丁直接从已验证的完整 dev7 源码生成。哈希覆盖的补丁禁用 Git 文本换行转换，保证 Windows 和 Linux 校验一致。

## 验证与提交

合并版 Harness `make all` 已通过：1920 passed、31 skipped，Ruff、格式检查及严格 mypy 的 194 个源码文件通过。独立安装目录的 371 个运行时成员及归档 532 个源码文件均核验匹配。原 transport 测试使用本机假服务，测试时仅设置 NO_PROXY 避免用户代理接管本机流量，没有修改线上代理策略或发起真实模型请求。

此前应用完整回归及 8 项修复证据见 [修复验证](2026-11-16-harness-fixes-validation.md)，独立复查见 [复查记录](2026-11-16-harness-fixes-independent-review.md)。最终提交使用干净隔离 worktree，正常执行原 pre-commit hook；避免该 hook 的自动重新暂存机制把原目录的其他未提交 hunks 混入提交。

## 部署与回退约束

候选目录为 `/root/octopus-deployments/harness-reliability-20261116`。部署前保留一致 SQLite 备份、原服务配置及暂停状态记录。候选沿用 `/root/OctopData`，使用单独可移除的 systemd drop-in 切换 WorkingDirectory 和 ExecStart，原 MCP 版本目录保留以便回退。切换前要求活动路径与核对时一致，健康或验证失败时删除本次 drop-in 并恢复原服务。

不更新 GPU 或 Windows 设备客户端，不取消独立 durable Jobs，不变更任务队列和 Graph 定义。两张创新 Graph 的 schedule 继续 disabled，根 validation_only 保持 true。上线确认须检查实际 MainPID/服务目录、运行时成员哈希、公共健康接口、原 SPA 文件、设备连接及暂停状态。

提交 hook、Linux 候选检查及实际切换回执分别保留在本地 `output/harness-deploy-20261116` 和服务器候选目录。最终服务状态以实际切换回执为准，本文件记录变更与部署约束，不作为已完成切换的声明。没有公共 release tag、主分支合并或模型/ACP 提示测试。
