# 0046. 执行端专家交流命令

**Date**: 2026-11-07
**Status**: Accepted

## Summary

本地 Codex、OpenCode、Claude Code 通过执行端命令向云端专家提问和续聊。
用户先配置服务器和受限专家 token，后续调用自动携带凭据。
这是本聊天中确认并授权开发的方案，补充 0045 的直接调用入口。

## Context

0045 已提供专家凭据和云端任务接口。现有执行端支持设备连接和远程执行，
但本地 Agent 还没有可以直接运行的专家交流命令。Linux 精简包也没有 ACP 客户端依赖。

## Requirements

* AC-1：同一个执行端程序提供专家配置和交流命令，安装包包含可直接调用的入口。
* AC-2：服务器可显式指定，也可从唯一已配置控制端读取。token 通过私有文件或隐藏输入配置，
  校验成功才保存。凭据独立于设备身份，输出中不返回密钥。
* AC-3：本地 Agent 可以列出授权专家、发送中文问题、等待和读取完整回复。
* AC-4：运行中的任务接收补充输入，已结束的任务续聊创建新任务，保留原会话和近期上下文。
* AC-5：所有命令输出 JSON。轮询只有读取，请求超时不自动重发消息。
  调用方可指定 command_id，并用只读查询确认创建结果。
* AC-6：支持显式取消及按当前 task、attempt、pending 提交审批，沿用服务端权限判断。
* AC-7：真实 CLI 子进程对真实 HTTP app 验证中文、多轮、撤销及跨凭据拒绝。
  只替换模型 worker，不声称已经验证三个产品的 Agent 自主决策。
* AC-8：Windows 完整包和 Linux 精简执行端包都包含入口，精简包不新增模型运行时依赖。

## Decision

直接扩展 device 命令组，使用 Python 标准库 HTTP 客户端调用 0045 接口。
不新增服务器接口和数据库表。token 权限、任务归属和访问审计继续由云端负责。

## Feature design

### Data model

执行端 state/expert-client/config.json 保存 version、server_url、token、credential_id。
沿用现有私有目录、Windows ACL 和原子写入。新配置在远端认证通过后替换。
会话和任务由服务器保存，本地 Agent 在 JSON 返回值中取得 task_id 和 session_id。
发送前把 command_id、消息指纹、操作类别与目标写入私有 commands 目录。
记录按服务器和 credential_id 隔离，并按命令加进程锁。响应丢失后只读查询回执；
结果仍未知时不重发，不把原补充输入改成新任务。记录不保存 token。
session_id 是任务的 origin_thread_id。配置只保存一个当前服务器与凭据。

### Interface

命令前缀是 octop device expert，可在 expert 后指定 --state。
便携入口 expert.bat 和 expert.sh 自动使用包内 runtime、launch.py 和 device-state。

| 命令 | 输入 | 来源与输出 |
| --- | --- | --- |
| configure | --server 或 --controller，--token-file 或隐藏输入 | 用 identity 验证，返回服务器、credential_id 和 scopes |
| config | 无 | 返回本地安全配置元数据，不返回 token |
| list | 无 | identity 返回的当前授权 experts |
| ask | --expert，--message 或 --message-file 或 stdin，--command-id，--wait | 建立独立 thread 与 work-item，返回任务和回复 |
| reply | --task，消息及 command_id、wait | 读取原任务；运行中追加 input，结束后带上下文创建新任务 |
| get | --task | 读取任务，返回状态、回复和当前审批请求 |
| wait | --task，--timeout | 有界轮询，结束、审批或超时即返回当前状态 |
| find | --command-id | 只读查询创建回执，不派发任务 |
| cancel | --task，--command-id | 服务端确认的当前取消状态 |
| permission | --task、--attempt、--pending、可重复 --decision、--command-id | 原样提交当前审批选择 |

### Value sourcing

| 值 | 来源 |
| --- | --- |
| server_url | 显式 --server，或 DeviceNetwork.controllers 中唯一符合条件的控制端 |
| token | --token-file 的 UTF-8 内容，或隐藏提示输入 |
| credential_id、授权专家和语言 | /api/auth/agent-access-keys/identity |
| session_id | 新建 thread 的 thread_id，或原任务的 origin_thread_id |
| task_id 和状态 | /api/work-items 的创建回执或 detail |
| command_id | 调用方 --command-id，缺省 UUID |
| reply | 终态的已授权 worker history，运行中的 progress.output_text，最后回退 reported_outcome |
| 续聊上下文 | 原任务 instructions 和已授权 worker history，保留最近 24000 字符 |
| permission_request 和 attempt | 任务 progress 和 current_attempt_id |

### Invariants and security

HTTPS 必需，回环 HTTP 仅用于本机测试。拒绝 URL 凭据、控制字符和重定向。
只接受专家 oaa_ token，不能借用设备或账号身份。
每次 HTTP 调用仍受服务端的当前 scope、专家和对象授权约束。
stdout 是 JSON，诊断经过脱敏，不输出响应原文或异常请求内容。
任务失败、等待、取消中和 unknown 状态按服务端事实返回。
unknown 状态禁止自动续派。POST 没有网络重试。
command_id 在同一操作中保持不变，丢失创建响应可使用 find 读取确认。

## Build plan

* [x] 执行端配置和轻量通信模块，满足 AC-2、AC-5、AC-6。
* [x] CLI 注册、中文交流和上下文续聊，满足 AC-1、AC-3、AC-4。
* [x] 双平台启动入口、精简包模块清单和操作说明，满足 AC-1、AC-8。
* [x] 实际 HTTP 与 CLI 验证及回归检查，满足 AC-2 至 AC-8。

## Verification

2026-11-07：新增专项及相关回归 107 项通过。
完整 make all 通过，5435 passed、158 skipped，格式、Ruff 与 728 个源文件的类型检查通过。
Windows 上用真实 CLI 子进程连接真实 Octop HTTP app，模型 worker 使用确定性替身。
Linux Python 3.12.3 精简执行端在隔离 HTTP 替身上完成配置、中文提问和续聊冒烟，
并禁止导入完整管理端或模型依赖。Bash 语法、打包模块闭包和 Git 空白检查通过。
本机实际便携执行端已更新并配置受限 token，通过 HTTPS 连接线上 main 专家完成两轮真实对话。
首轮确认 OCTOP-LOCAL-0046-20261107，续聊在未重述标记时正确复述同一标记。
本功能随 1.0.2b18 进入发布和部署流程。

## Consequences

执行端可以由有终端工具的本地 Agent 直接调用。用户仍需签发专家 token。
单次等待有时间上限，长任务需要继续调用 wait。新消息与完成任务的续聊需要保留返回的任务标识。
修改只涉及客户端，不自动发布安装包或改动线上服务。

## Rationale

用户已选择复用执行端。标准库 HTTP 避免把 ACP、模型运行时及完整管理端依赖加入精简包。
现有 ACP 入口继续服务标准客户端，这次新增的是可由本地 Agent 运行的直接交流命令。
