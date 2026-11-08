# 0050 具名后台任务与完成反馈

**Status**: In Progress
**Date**: 2026-11-08

## Problem and decision

用户提供的 execute 调用先 sleep 420，再读取日志，timeout=600。同步等待占用当前回答。现有 ExecutionReconciler 每 15 秒更新持久任务回执，但不会因此唤醒专家。job_start 缺少名称字段，活动界面只能显示 shell 程序名。

沿用已有持久 Jobs、run_events、每 15 秒协调器和绑定原会话的 self_reminder。无需新队列、设备协议升级或数据库迁移。Agent 创建任务必须给出用户语言的业务名称。同步 Agent 工具仅承接短操作；等待未来时间用 schedule_self_check，真正长任务用 job_start。任务结束通过真实终态回执调度一次原会话的只读反馈，不让 Agent 自己 sleep 轮询。

## Requirements and value sources

1. Agent job_start 的 title 必填，1 至 120 字、单行，不接受 bash 等纯程序名。argv、cwd、idempotency_key 和原有权限、幂等语义保留。名称来源是 Agent 的明确参数，在 Hub 回执元数据保存；旧设备不支持该字段仍可显示和保留名称。
2. 同步 execute 和 device_run(command.run) 在派发前拒绝超过 60 秒的超时或明确超过 10 秒的 shell sleep / PowerShell Start-Sleep。错误明确指导具名 job_start 或一次 schedule_self_check。短命令照常执行，不自动后台化、不重放、不取消已存在任务。
3. job_start 默认要求完成反馈，可显式关闭。notify_on_exit 与名称保存在同一个原 Job 回执内；协调器只处理 completed、failed、cancelled 的真实回执，unknown、离线和接受状态均不是完成。
4. 待反馈查询来自 run_events 的持久元数据。终态与通知调度之间的重启仍可恢复。每个 owner、origin context、job 只有一个确定性 cron ID；重复协调和创建后未确认的重试不重复调度。
5. 唤醒沿用 self_reminder 的 origin_thread_id、原会话锁和持久投递。提示仅含有界任务名、原 Job ID、终态、返回码和来源，不搬运完整日志。反馈请求使用原执行 context 的 for_run 验证及 ask 模式，不跟随后来选择的设备，不自动重启实验。已撤销、跨账号或已删除的来源不能唤醒其他会话。
6. 列表、图谱、详情和会话悬浮摘要优先显示明确任务名。旧 shell 包装任务可从已保存命令中提取脚本或日志名作保守回退，不编造实验目的。Job ID、原命令与真实状态仍在详情保留。
7. 通用 Hook 不限定实验等业务字段。Agent 自定 event_type，回调 data 接受任意 JSON 值，编码后最多 8192 字节。注册、查看、取消绑定当前账号、专家和原会话；执行 context 可为空，空来源的唤醒仅处理事件数据，不开放工具。
8. 注册参数包含业务标题、事件名、唤醒目的、幂等键、有效期（默认七日，最多三十日）。回调凭据是现有服务端密钥对 owner 与 hook ID 的独立 HMAC，不能用于账号或其他 Hook。只有精确 POST /api/wakeup-hooks/wh_<32hex>/fire 使用该凭据，其余接口仍走原 JWT。凭据验证在读取回调正文之前，正文最多 12288 字节。重复信号不会再次唤醒；待处理状态保存在 run_events，沿已有协调器和原会话 self_reminder 恢复。

9. 命令进度使用 delivery_mode=progress 的独立持续上报通道。Agent 先注册、把回调地址与凭据配置给脚本，再用 progress_hook_id 关联 job_start。百分比仅取脚本 data.percent 的真实数值，范围 0 至 100；没有百分比时仅显示阶段和说明。data.phase 最多 100 字，message 最多 300 字，sequence 为可选递增整数，旧序号和重复上报不覆盖新进度。data.done 关闭进度通道，不代表进程已退出或任务成功。
10. 进度保存在 Hook 元数据，任务状态仍来自独立的真实进程回执；两个来源不会互相覆盖。进度不触发模型与 Cron。任务浮层、列表、详情和执行工作区读取持久进度，刷新或重启后仍能恢复。完成、异常或另行注册的关键事件才唤醒专家。缺少回调、权限撤销或离线不伪造百分比，旧命令无需设备升级。
11. 唤醒在真正派发模型之前，以状态比较原子领取为 running。此后取消会如实返回 running，不声称中断已经开始的分析。进程在分析中重启时记为 unknown，沿现有投递尝试显示结果未确认，不自动重放模型。尚未派发的持久事件继续恢复，已记录的确定性回答不会重复写入。

## Validation

验证同步和异步工具门禁均在派发前拒绝长等待，短命令与包含 sleep 字样的普通文本不误拦。验证名称贯穿旧设备回执及状态刷新。验证无浏览器时终态触发一次、重复 tick、重启恢复、失败和取消、未知与撤销、原线程及原设备隔离。复用 0042 的投递和会话串行测试，新增完成请求的只读 context 断言。发布前完成有关 Python、前端、i18n、严格类型检查和独立审查。
