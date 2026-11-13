# GPU 创新迭代上线验收

> 这是本日首轮部署的历史记录。当前两张 Graph、预算限制及最新验收结果以 [本轮更新记录](innovation-rollout-2026-11-12-layout.md) 为准。旧自动调度已关闭。

2026 年 11 月 12 日，已部署到 https://octop.effaf.me/。

代码目录为 `D:\Agent_Workspace\octopus1\innovation-work`，基于 develop `2aceadb8`，本轮没有提交或推送。生产目录为 `/root/octopus-deployments/innovation-b27-20261112`，服务为 `octop-hub`，数据目录仍为 `/root/OctopData`。原启动配置和 SQLite 在线备份位于 `/root/octopus-deployments/backups/innovation-b27-20261112`。

## 验收结果

| 要求 | 已观察到的证据 |
| --- | --- |
| AC1 模型路由 | 线上 preview 将架构设计和失败分析分到 reasoning，将编写脚本分到 coding，将文献检索分到 research。前两类及 research 使用 Grok 4.7，coding 使用 DeepSeek V4.1 Flash。手动选择及账号任务设置的优先级保留。 |
| AC2 持久 Graph | `gpu-innovation-27N3HD` 已发布第 1 版，共 32 节点、44 条边。首轮 `01M76XGF76YFD8D7P6F0RSZBG4` succeeded，4 个激活全部 completed。30 分钟调度已启用，重叠时跳过，next_due_at 已持久化。 |
| AC3 队列和报告 | helper 已安装至设备 `/home/wjh/workspace/gpu-innovation`，SQLite 事务、revision、领取凭据、依赖、未知执行阻塞和真实指标比较均有回归覆盖。原项目 TASK_QUEUE.md 仍为任务事实来源。 |
| AC4 原准则及资源 | 原专家准则保留，仅追加流程入口；项目任务表和维护准则实读成功。首轮 capacity 的真实 Job `245a7392b2ab81aadcb7963a4e5e0185` completed，returncode 0，日志与 Graph 输出均为 available=false。没有进入模型或训练节点，没有停止他人的进程。 |
| AC5 文件入口 | 15 个置顶已保存，6 个专家文件、9 个固定设备文件。实际读取 MEMORY、实验手册、评估准则、任务表、维护准则、流程说明及 STATUS 成功。所有权、并发元数据编辑和停止专家时编辑文档的回归检查通过。 |
| AC6 界面 | 已构建模型选择、映射及常用节点表单，高级 JSON 默认折叠。设置动作与滚动字段分开。本地浏览器交互和 390px DOM 布局检查通过，设置动作和字段无重叠，节点检查器无横向溢出。前端相关测试、TypeScript 和生产构建通过。 |
| AC7 可选 ACP | 专家 ACP 工具已启用，配置保留。真实设备检查返回 403 FORBIDDEN，没有扩大设备权限，也没有声称 ACP 决策已成功。当前默认使用已验证可用的 Grok 4.7。 |
| AC8 卡住会话 | 原会话 turn_active=false。已部署匹配源码构建的 Harness transport.1 wheel，两个运行文件 hash 与清单一致。OpenAI 连接和池等待 30 秒，读写空闲 300 秒，最多重试 1 次；连续流式输出可以超过空闲窗口。70 项针对性检查包含真实 TCP 静默超时、持续流、会话头和取消。 |

实际模型探测均成功：DeepSeek 2001ms，Grok 2917ms。公网 `/api/health` 返回 ok=true、db=true。原卡住会话没有挂起的生成或人工确认。

## 完整检查

在最终 Linux 发布目录执行 `make all PYTEST_JOBS=4`，退出码 0。结果为 **5860 passed，11 skipped**，耗时 1107.43 秒；Ruff 和 mypy 全绿。格式工具仅调整了一处新增测试，Python AST 相同。前端生产构建已完成。没有等待 Windows CI。

线上只读验收共 6 组，failed=[]；临时验证会话已撤销。公共 API 文档按现有配置关闭，`/api/docs` 和 schema 地址返回 404，因此使用已部署应用的 `openapi()` 检查新接口 summary 和请求、响应结构，没有更改公开设置。

可复核证据保存在本地工作区根目录：`innovation-ship-make-all.log`、`innovation-live-seed.log`、`innovation-live-verify.log` 和 `innovation-verified-manifest.json`。服务器对应日志位于 `/tmp/innovation-*.log`。发布包 SHA256 为 `aa8d52648ca40d564c6b8e7cc3076171f22e1493db81b0795b31ed699576dff3`。Harness 源码、补丁和 wheel 的独立校验链位于 `vendor/harness/transport-source-manifest.json`。

## 验证范围

首轮证明了真实设备资源检查及忙碌分支，不代表已经完成一次科学实验或获得指标提升。空闲后由定时 Graph 继续读取原规则和待实验队列。准备、训练和分析阶段保留真实回执要求，未知工作不能自动重提。

浏览器当前由用户控制，线上像素验收未继续；本轮界面证据来自本地交互和 DOM 布局检查，没有成功采集像素截图。没有匹配的 scope 条目需要勾选。独立只读审查未发现确定的 P1/P2 阻断项。
