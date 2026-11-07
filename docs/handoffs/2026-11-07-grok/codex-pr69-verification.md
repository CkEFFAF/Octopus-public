# PR #69 / 0045 G5 独立收尾记录

本轮单独收尾后端 token 与标准 ACP adapter，不修改 `chat-task-work` 的聊天 UI。说明与启动配置见 [remote ACP](../../acp-remote.md)。

## 修复的边界

- 原始 `oaa_` 和机器 JWT 都走明确的 HTTP 默认拒绝表，不能继承发行人的管理员接口权限或进入账号／设备 WebSocket。
- session/task/thread grant 按 credential 隔离；机器创建 session 不切换人类聊天。命令重放、分页、worker grant 和当前专家权限检查覆盖同账号多凭据及取消共享的情况。
- S0 token 没有设备／管理端本地执行授权，也不接受输入资源引用。任务正文不能借用发行人的管理员身份选择 local、device 或目录。
- work item 的 HITL 暂停可转给 ACP 客户端决定；审批绑定当前 task/attempt/pending，逐项校验、持久化幂等回执，随后复用原有 resume 与历史链路。取消与审批竞争时不能自动放行。
- 适配器先保存待确认命令，再发送请求；丢失响应时只读找任务／输入回执。未知任务保留待确认状态，不创建替代任务。增量文本和完整结果分别来自有界运行缓存与授权历史，取消以服务端确认状态为准。
- 本地 session 缓存改为私有 SQLite，避免多个 adapter 进程互相覆盖 JSON；load 先重检云端权限，再重放缓存。
- 修复主分支已有的 Ruff/mypy 问题、迁移 038 的历史版本断言和 G1/G2/G4 变化后的测试替身，以满足整个仓库的检查要求。

## 已取得的证据

- token、隔离、恢复、权限、实际 ACP 链路及 i18n 定向验证：**105 passed**。
- 首轮完整回归的 17 个失败项修复后单独复测：**17 passed**。
- 修复后的完整 `make all`：**5417 passed，157 skipped**，Ruff、格式检查和类型检查全部通过。
- `mypy --strict src/octop`：**726 个源文件通过**；Ruff 通过。
- `npx tsc -b` 与 `npm run build` 通过。
- Ego Lite 实际打开 Scalar，审批 API 的描述、请求字段、枚举和响应结构可读。
- Windows → Linux 实测：官方 ACP 客户端、实际 CLI、实际 HTTP 服务，中文结果与 load 重放通过；两端源码树一致。仅替换 LLM worker，使用隔离账号／数据及 SSH 端口转发。

提交钩子和 PR 的 Linux／Windows CI 状态以本 PR 最终检查为准。未将模拟云端、curl、真实 Zed UI、真实 LLM 或 P2P 直连作为本次已完成的验收。

## 界限

S0 如实关闭本地 fs/terminal/MCP、图片／音频／embedded context 和 elicitation。设备执行 grant 需要后续明确设计；本次没有扩展管理权限或新增 NAT 穿透。PostgreSQL 提供对应 038 DDL，本次跨系统服务实测使用 SQLite。

临时测试凭据的文件删除被工具自动审批以 `blocked by policy` 拦截；已通过隔离库撤销该凭据，并关闭测试服务和 SSH 转发。保留的私有临时文件不能用于连接线上账号。
