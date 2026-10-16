# Agent Native 独立评审

- Spec: `docs/specs/0016-agent-native-configuration.md`，当前 `2026-10-16.6`
- Current baseline: `c627ea158fa6afd63a429a934c57cecdb4077c1d`；下述首轮结果来自同步前 `634c1bdeb627e71206d65b7dc582ae7ce89894ba`。
- Code: GPT 6.1 High；Review: GPT 6.0 Luna High。
- Review method: 只读检查完整差异与新文件，首轮和修复复审前后核对文件 SHA-256；未运行测试，未修改代码。验证结果另见规格 Evidence。
- Final runtime snapshot: `logs/agent-native-verification/c627-r6-final-source-snapshot.json`（本地忽略的验证日志；首轮使用 `source-snapshot.json`）。

## Findings and resolution

| Finding | Impact | Resolution | Regression |
| --- | --- | --- | --- |
| P2 / AN-4：停用的共享专家仍能进入用户的历史检索与读取范围 | 与「当前可用共享专家」范围不一致 | 非所有者读取与 SQL 检索均要求共享专家 enabled；用户自己停用的专家保留本人历史访问 | `test_owned_history_search_is_literal_bounded_and_text_only` |
| P2 / AN-3：子 Agent 创建的存在性检查与上传之间存在并行覆盖 | 同名 `replace=False` 调用可能都报告成功 | HTTP 与 native 服务以同一 agent ID + 路径串行写入；锁按事件循环管理，闲置键释放 | `test_native_and_http_subagent_create_do_not_overwrite` |
| 协调者补充：单条消息超过 4000 字符时未标记截断 | 调用者无法判断摘要是否完整 | 按单条和总量限制传播 `text_truncated`，返回限制元数据 | `test_history_marks_single_message_truncation` |

## Follow-up review

独立评审确认两项 P2 已解决，截断标记修复正确，未在这组修复中发现新的可操作问题。修复快照前后哈希一致。

其余已检查边界包括可信运行身份、共享专家私有配置隔离、模型和资源引用校验、文本历史范围、团队名单规则、安全重载及主持人工具约束。

## Verification boundary

- SQLite 服务/HTTP 与工具集成已执行；PostgreSQL 搜索分支本机未运行。
- 未调用付费或 live 模型。持久化通过真实业务服务与现有 API 断言，前端同步由 Vitest/jsdom 回归验证。
- 全量回归结果由协调者在规格中记录，独立评审通过不代表所有测试已通过。

## Upstream 0019 compatibility review

2026-10-16 同步新主线后，GPT 6.0 Luna High 先只读核对上游交集，发现两个需要纳入兼容适配的边界：共享专家会话保存设备后与执行服务所有权规则不一致，以及共享成员默认目标可能暴露所有者私有设备/目录。已明确拒绝不支持的共享专家目标设置，并对 native、团队摘要及实际 peer 列表使用相同的可见性边界。0019 房间统一目标继续复用已有会话存储，保留成员默认绑定。

Luna 的 r4 聚焦复审未发现新的可操作问题，确认私有目标/模型字段按当前查看账户屏蔽，所有者视图保留；原生设备选择在保存前验证专家所有权；explicit 目标在派工前校验且不静默回退。该轮尚未包含共享成员实际派工适配，后续结果见下述 r5 与最终 r6 复审。

## Shared dispatch r5 review

Luna 对 `c627-r5-source-snapshot.json` 所列文件复审，前后哈希一致，确认当前名单/共享/启用状态以及排队后的撤销校验范围合理，未扩大全局 registry 所有者权限。

发现 **P1：共享文本任务仍可能套用默认设备而失败**。`AgentManager._prepare_stream_request` 会考虑共享专家的私有绑定与调用账户默认设备，而 `ExecutionService.resolve` 仍要求专家同所有者；原测试 mock 了 `_call_agent`，没有经过这条真实请求准备路径。此发现进入规格 r6，修复要求以服务端重新验证的纯文本调用标记隔离目标、禁用执行工具，并测试真实请求准备与 middleware。修复及复审已完成，见下述最终 r6 复审。

协调者沿产品实际装配顺序继续检查，发现 `wire_host_dispatch` 的群聊流式路径会绕过先前包裹的 `_invoke_peer`，因此不能仅在该层创建纯文本标记。修复须把重新授权和标记创建放入所有派工都会调用的 `_build_peer_request`，并覆盖已装配流式房间的真实调用路径。此问题属于同一 r6 行为合同，既有 103 项局部通过不能替代装配路径回归。

## Final r6 review

GPT 6.0 Luna High 对最终冻结源码复审，**未发现新的可操作问题**。确认流式群聊经包裹后的 `_build_peer_request` 重新验证主持人、共享专家、当前名单与房间线程，签名标记由请求准备和设备 middleware 再次验证；设备目标/插件配置被清除，模式限制为 Ask，技能与 MCP 禁用，模型工具清空。未发现这条装配路径的授权绕过或私有设备信息泄漏。

源码哈希与 `logs/agent-native-verification/c627-r6-source-snapshot.json` 一致；唯一预期变化是集成测试保留原始 AsyncMock 引用，以适应 `wire_host_dispatch` 包装方法。协调者已保存包含该测试修正的最终快照 `c627-r6-final-source-snapshot.json`。评审未运行测试，最终执行结果见规格 Evidence。

协调者随后确认最终快照定向回归 **42 passed**、完整后端非 live 回归 **4726 passed / 151 skipped**。静态检查和前端构建通过；前端全量的既有失败及额外一次异步预览失败单独记录在规格，未据此宣称所有测试通过。
