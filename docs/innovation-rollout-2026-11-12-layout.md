# GPU 创新流程本轮更新与验收

2026 年 11 月 12 日，已部署到 https://octop.effaf.me/。此记录更新本日首轮部署记录中的 Graph、预算和验收状态。

当前服务为 `octop-hub`，实际目录为 `/root/octopus-deployments/innovation-layout-b27-20261112`，数据仍为 `/root/OctopData`。数据库和原服务配置已备份至 `/root/octopus-deployments/backups/innovation-layout-b27-20261112`。健康检查返回 `ok=true`、`db=true`。没有提交或推送 Git 改动。

## 可核对的流程

设计图 `gpu-innovation-design-27N3HD` 已发布第 1 版，5 个节点、4 条边：

开始 → 预先设计 → 独立审阅 → 校验登记 → 结束。

执行图 `gpu-innovation-27N3HD` 已发布第 4 版，9 个节点、9 条边：

开始 → 检查资源并领取 → 有就绪任务？ → 按设计实现 → 复核实现 → 等待空闲并运行 → 分析与报告 → 校验归档 → 结束。

没有就绪任务时，条件节点直接进入结束。实现、版本、审阅及文件哈希由 helper 校验。失败或无提升产生下一版本设计需求，再进入设计与审阅流程。未知执行保持待核查，不能自动重复启动。

当前为额度暂停配置。两图自动调度关闭，`validation_only=true`，设计登记的批准 scope 为空。Agent 节点保留 DeepSeek 验收选择，当前没有启动设计图或模型节点。原定高级模型为 Grok 4.7，既有 ACP 高级 Agent 也可在权限允许时承担决策；本轮没有执行其真实审阅。

## 设计与文件入口

11 份任务编号及 v1 草案已上传至 GPU 项目的 `agent/designs/Txxx/codex-draft-v1/`，覆盖 T007–T015、T018、T019。每份包含代码设计、实施步骤、评估验收和依赖风险资源章节。独立 Codex 源码核对纠正了损失加入顺序、完整预测导出、数据及评估接口等问题，并逐项列明未决条件。

这些文件均为 pending，尚缺正式高级审阅及部分冻结的科学定义、配置、基线和命令，不能交给编码 Agent 即兴补齐并训练。原任务状态、前置、终止和否决继续有效。

置顶入口“任务设计文档与审阅索引”指向 `/home/wjh/workspace/OCRL-3DSSG-Codes/agent/designs/CODEX-PENDING-DESIGNS-20261112.md`。共享 `DESIGNS.md` 未被覆盖。原 `TASK_QUEUE.md` 只追加独立标记内的设计链接，写入使用新读取的 SHA 校验；线上验证确认原有 12 条任务行和标记外内容保留。31 次原生文件读取验证了草案、pending 回执、审查报告、索引和安装脚本的实际内容及哈希。

置顶列表共 16 项。行内删除按钮已移除，右上角进入选择模式后选择、确认，只取消置顶，源文件保留。专家详情和会话共用文件入口。画布连线采用直角避让路径，业务流程拆为两图。

## Agent 协作

普通用户会话与 Agent 协作分标签显示。机器身份来自服务端注册的受限 `oaa_` 凭据；ACP 记录保留真实 runner、设备和父会话链接。后续人类输入仍保留人类身份。

本地官方 ACP 客户端完成真实 stdio → HTTPS 初始化和建会话，没有发送 prompt。服务端回读确认：

- actor 为 `Codex`，凭据 ID 为 `01M775SY552R306NHQFXGFQA27`。
- 会话 `thr_01M775T3C8KV6MY33GH1P2MN9Y` 归属 `agent_collaboration`，普通用户标签不包含它。
- 会话有 0 条消息、0 个模型请求快照，无活跃生成。
- 临时机器凭据和验证用 owner 会话均已撤销，机器密钥临时文件已移除。

专家 AGENTS.md 已追加预先设计、真实身份和预算规则。写入规则与握手不代表专家已回复确认。先前额度失败的普通用户请求没有被改写成 Codex 消息。

## 验证证据与范围

最终 Linux `make all PYTEST_JOBS=2` 退出码 0：**5936 passed，11 skipped**，1961.04 秒。Ruff 与 mypy 763 个源文件通过。首轮发现一个旧 ACP 测试 fixture 使用旧查询接口；独立复现后修正 fixture，权限恢复的原断言保留，相关 21 项通过、1 项平台跳过，再完成上述完整重跑。前端 TypeScript、生产构建及协作、置顶、线路相关测试已通过。没有等待 Windows CI。

发布包 SHA256 为 `18975c9051d34e71b22ba9848efff16b0e658201260c1e7821fce930f4fd6c43`，773 个覆盖文件字节匹配。已安装 Harness `1.0.2.post4.dev7+transport.1` 的两个修复文件与清单匹配。

真实执行图验收 run `01M775QHCZNBF5EKNVJAT0MR68` succeeded，仅激活 start、claim、has_claim、end。实际 Job `b301b08ebb8f40599c0d1abafa538cba` 退出码 0，日志与输出一致为 `claimed=false, reason=validation_only`。模型激活数为 0，没有启动训练或修改真实实验账本。

只读线上验收的 42 次 HTTP 请求全部通过，没有启动 Graph、调用模型、训练或重试。完整日志在工作区根目录的 `innovation-layout-make-all.log`、`innovation-readable-setup.log`、`innovation-readable-verify.log`、`innovation-budget-smoke.log`、`innovation-layout-deploy.log`；发布字节清单为 `innovation-layout-verified-manifest.json`。

本轮证明了部署、文件、分类身份及预算退出分支。设计、编码、真实高级模型或 ACP 决策、训练和科学提升尚未完成端到端验收。OpenCode Go 五小时额度耗尽后，本轮所有服务商测试和重试保持暂停。浏览器目前由用户控制，未完成线上像素验收。规格 0053 和 0054 保留 In Progress。
