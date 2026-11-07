# 本地 ACP 客户端连接云端专家

`octop acp-remote` 通过标准 ACP stdio 协议连接本地客户端，把任务交给云端 Octop 专家。它不会启动本地 OctopServer，也不会下载服务器数据库。协议依赖锁定为 `agent-client-protocol==0.11.0`、protocol version 1。

## 凭据和启动

使用密码或 SSO 登录管理端，通过 `POST /api/auth/agent-access-keys` 创建凭据。请求示例：

```json
{
  "name": "本地 ACP 客户端",
  "days": 30,
  "expert_ids": ["EXPERT_ID"],
  "scopes": ["experts.read", "tasks.create", "tasks.read", "tasks.input", "tasks.cancel", "resources.read"],
  "allow_existing_threads": false
}
```

响应只返回一次 `secret`。将其保存在当前用户可读的私有文件中；Unix 建议文件权限 `0600`。把文件路径设为 `OCTOP_ACP_TOKEN_FILE`，启动命令为：

```text
octop acp-remote --server https://YOUR_OCTOP_SERVER --expert EXPERT_ID
```

客户端的启动配置可采用下面的字段（具体外层结构由客户端决定）：

```json
{
  "command": "octop",
  "args": ["acp-remote", "--server", "https://YOUR_OCTOP_SERVER", "--expert", "EXPERT_ID"],
  "env": {"OCTOP_ACP_TOKEN_FILE": "ABSOLUTE_PRIVATE_TOKEN_FILE_PATH"}
}
```

这里的文件路径必须替换成实际路径。启动参数不依赖 shell 展开 `%变量%` 或 `$变量`。密钥本身不进入命令行参数。远端必须使用 HTTPS；仅回环地址允许 HTTP，供本机测试使用。

## 行为和权限

- 新建 ACP session 会建立独立云端会话，不切换浏览器当前聊天。`cwd` 仅为本地会话元数据，不会变成服务器执行目录。
- prompt 创建独立 work item。运行中的文本通过只读查询转为 `session/update`；任务结束后返回完整历史文本。后续 prompt 建立带有近期会话上下文的新任务。
- 工具需要审批时，客户端收到 `session/request_permission`，其中包含工具及参数。只支持本次允许／拒绝，不修改后续工具策略；超时按拒绝处理，不自动允许。
- `session/cancel` 只取消对应任务。只有服务器确认任务已取消，prompt 才返回 `cancelled`；外部 Job 尚未确认时继续等待。
- `session/load` 校验当前云端授权后重放缓存历史。缓存保存在本机 `$OCTOP_HOME/acp-remote/sessions.sqlite3`（默认 `~/.octop`）。缓存绑定服务器、专家和凭据 ID，不保存密钥。
- 发送前先持久化 `command_id`。响应丢失后，只读查找任务／输入回执，不重发未知操作；`unknown` 状态保留待确认信息，不自动创建替代任务。
- 凭据默认只能读取自己创建的任务和会话。即使发行人是管理员，也不能访问用户管理、管理配置、设备控制、人类验收或其他凭据的会话。撤销、到期、用户禁用、专家取消共享及 scope 变化在后续 HTTP 调用中生效。机器凭据不能连接账号通知、设备或聊天 WebSocket。
- 工具审批以当前 task、attempt 和 pending request 为边界；请求幂等，审批后继续使用服务器原有 HITL 与历史投影链路。机器变更请求和拒绝访问写入审计日志，包含凭据 ID、owner、路径及状态码，不记录请求正文或密钥。

S0 如实关闭图片、音频、embedded context、本地 fs/terminal/MCP 和 elicitation 能力。接入 ACP 不会授予 P2P 或设备磁盘权限；`oaa_` 不能用于网页登录，`oak_` 不能用于机器 Bearer 调用。

S0 凭据没有执行目标授权：机器不能通过任务正文指定管理端本地执行、设备、工作目录或输入资源引用。管理员发行的 key 同样受此限制。远端专家的普通文本任务可正常运行；设备／目录级授权需要后续明确的 execution grant，不能借用发行人的管理员身份。

## API 补充

| 路由 | 用途 |
| --- | --- |
| `GET /api/auth/agent-access-keys/identity` | 机器凭据当前 scopes、专家及语言；安全元数据，不返回账号配置 |
| `POST /api/agents/{expert}/threads` | 为机器凭据建立独立 session |
| `GET /api/work-items?command_id=…&status_group=all` | 只读恢复丢失的任务创建响应；在分页前按凭据过滤 |
| `GET /api/work-items/{task}/inputs?command_id=…` | 只读查询已提交输入／审批回执 |
| `POST /api/work-items/{task}/permissions` | 提交当前 `pending_id`、`attempt_id` 和逐项决定；需要 `tasks.input` |

审批正文为 `{"command_id":"UNIQUE_ID","pending_id":"CURRENT_PENDING_ID","attempt_id":"CURRENT_ATTEMPT_ID","decisions":["reject"]}`。重复相同命令返回同一回执，命令内容冲突或过期审批被拒绝。所有对象读取仍检查当前专家权限和凭据的对象 grant。

## 验证

`tests/integration/test_acp_remote_server_0045.py` 使用官方 `acp.spawn_agent_process` 启动实际 CLI，并连接实际 Octop HTTP app；仅 LLM worker 使用确定性替身，覆盖中文长结果、结束前的增量文本、续聊、load、凭据撤销、取消及批准／拒绝。它不依赖 Zed，也不以模拟云端或 curl 代替协议验收。

`tests/unit/acp_remote/test_recovery.py` 覆盖进程重建后的未知发送恢复、输入回执、未知任务、取消确认和多进程缓存一致性；`tests/integration/test_agent_key_boundaries_0045.py` 覆盖原始 token／机器 JWT 的管理面隔离、跨凭据隔离、scope／到期及专家共享撤销。

2026-11-07 另完成一次 Windows Python 3.13 客户端 → Linux Python 3.12 隔离管理端的实测：官方 ACP stdio 客户端启动实际 CLI，通过 SSH 加密端口转发连接 HTTP 服务，中文结果往返和 load 历史重放均通过。两端产品源码一致，只有 LLM worker 使用确定性替身；未使用线上账号、数据库或模型凭据，也未声称完成 Zed 界面或公网直连验收。测试结束后服务及转发通道已关闭，临时凭据已撤销。
