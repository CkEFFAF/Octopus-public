# 本地 Agent 通过执行端交流专家

本地 Codex、OpenCode、Claude Code 可以用终端工具运行现有执行端程序。
命令自动携带已配置的专家 token，结果以 UTF-8 JSON 返回给本地 Agent。

## 配置一次

在管理端签发专家专用的 oaa_ token，选择可访问的专家。
交流需要 experts.read、tasks.create、tasks.read、tasks.input，取消另需 tasks.cancel。

Windows 便携执行端目录：

```powershell
.\expert.bat configure --server https://你的管理端域名
.\expert.bat list
```

configure 会隐藏输入 token。也可以通过 --token-file 指向私有 UTF-8 文件，
命令参数中不需要出现密钥。已有一个控制端时可以省略 --server。
有多个控制端时使用 --controller 指定 ID，或明确指定 --server。
新凭据认证成功后才替换原配置，不改设备配对或正在运行的设备连接。

Linux 对应使用 ./expert.sh。安装完整 Python CLI 时，对应命令为：

```text
octop device expert --state 你的执行端状态目录 configure --server https://你的管理端域名
```

## 让本地 Agent 发话

把执行端目录和下面的调用约定告诉本地 Agent，或放进你使用的项目说明中。
这些命令既可以由人调用，也可以由 Agent 的终端工具执行。

```powershell
.\expert.bat list
.\expert.bat ask --expert 专家ID --message "请帮我分析这个方案" --command-id review-001
.\expert.bat reply --task 上次返回的task_id --message "请进一步比较两种选择" --command-id review-002
.\expert.bat get --task 返回的task_id
.\expert.bat wait --task 返回的task_id --timeout 60
```

复杂问题可先写入 UTF-8 文本，再使用 --message-file。
省略 --message 和 --message-file 时从标准输入读取。
不要把服务器 token 放进问题、代码仓库或命令参数。

ask 和 reply 默认等待 30 秒，可以使用 --wait 0 立即取得任务标识，
或 --wait 60 等待更久。输出包含 task_id、session_id、status、reply、
current_attempt_id 和 permission_request。长任务用 get 或 wait 读取，
读取不会追加问题。后续轮次要保存本轮返回的新 task_id。

运行中 reply 会追加要求。任务完成后 reply 会在同一个云端会话创建下一轮任务，
携带近期问题与专家回复。上下文最多保留最近 24000 字符。
任务内容不会自动授予专家本机文件、终端或设备权限。

## 超时和取消

每个新操作使用唯一 command ID，重试同一操作继续使用原 ID。
执行端发送前保存私有命令记录。结果不明确时只查询服务端，不自动重新发送。

```powershell
.\expert.bat find --command-id review-001
.\expert.bat cancel --task 任务ID --command-id cancel-001
```

find 返回 task 为 null 代表结果仍未确认，不能据此断言任务没有执行。
命令错误以 JSON 写入 stderr 并返回非零退出码。
网络错误会尽可能带回 command_id 和已知 task_id。
任务的 failed、unknown、cancel_requested 等状态按服务端事实返回，
应读取 status，不能单凭进程退出码判断任务完成。

## 显式审批

出现 permission_request 时，等待命令返回当前请求，不会自动批准。
查看工具和参数后，使用 get/wait 返回的当前 attempt 和 pending ID 决定：

```powershell
.\expert.bat permission --task 任务ID --attempt 当前attempt --pending 当前pending --decision reject --command-id approval-001
```

approve 只批准本次动作。多个动作按原顺序重复 --decision。
过期请求、越权操作以及 token 撤销继续由服务器拒绝。

## 验证边界

集成测试使用真实 CLI 子进程、真实 HTTP 服务、真实 token 和任务权限链路。
模型 worker 使用确定性替身，不消耗线上模型额度。
这证明执行端命令可以用于 Agent 的终端调用，不等于已经在三个产品中验证 Agent 的自主选用策略。
