# 0045 受限本地 Agent Token 与标准 ACP 客户端接入（G5）

- Revision: **2026-11-07.1**（Asia/Shanghai）｜Contract: **Ready**
- Owner: Octopus 架构师 → 总管派 Coder｜权威源：本文件
- Decision basis: 用户授权开发；交接 `docs/handoffs/2026-11-07-grok/`（05-agent-token-acp + design-report + README）；用户已确认「管理端生成 token，本地 agent 与服务器专家沟通；**必须兼容标准 ACP 客户端**，禁止 curl-only 冒充」；Codex 负责密钥生成/复制/撤销 UI 与 ACP 启动配置展示，本规格冻结**后端 token/API + 本地 ACP adapter 协议契约**
- Code baseline: `CkEFFAF/Octopus-public` **`origin/main` @ `99719e2de0e086cd49e86f94640a27cd98858b2b`**（`99719e2 docs(handoff): Codex UI after G1/G2 @ ca771fd`；本轮已 `git fetch` 核对）
- Delivery: **compact SDD**（build-adaptively）｜Verification: **strict**（标准客户端互操作 / scope 隔离 / 机器不可自批）｜Continuity: collaborative（GPT 交接）
- 编号说明：tip 已提交 `0040`–`0042`；架构侧 Ready `0043`（G3）/`0044`（G4）；本规格取 **0045**（G5）
- 依赖：功能可**并行**于 0043/0044；**硬复用** tip access-key 生命周期与审计、threads/inputs（`command_id` 幂等）、history、run_events、resources。若 0043 已合：任务创建/进度/取消优先走 work-items（进度只读）；若未合：S0 用「专用 remote session thread + inputs + run_events」，**禁止**用进度查询插入 worker 消息。启用 ACP **不**自动获得 0044 P2P 或设备全盘权
- 约束：**只写 docs/specs**；不改产品代码、不改 `dashboard/`、不碰 `octopus1/chat-task-work`；不 commit / push / PR / 部署；不派 Coder；不替换 Harness；不做全量重构 PR；0039 Mac **搁置勿动**；密钥明文不进日志 / 进程 argv 示例 / 测试快照

---

## 0. 给 Coder / GPT / Codex 的阅读顺序

1. §1 Goal / Non-goals / 模块边界  
2. §2 复用映射（tip 现状 → 缺口）+ **锁定的 ACP SDK 版本**  
3. §3 DEC（已拍板）  
4. §4 契约：Agent Access Key HTTP + ACP adapter JSON-RPC 方法表 + 受限云端 API  
5. §5 REQ / AC（含**真实标准客户端**）  
6. §6 迁移 038 / 错误码 / 授权 / 旧 key 兼容  
7. §7 Coder 实现指南与测试  
8. §8 与 0039 / 0043 / 0044 / `/api/acp` 关系  

---

## 1. Goal / Non-goals / 模块边界

### Goal

让用户在**管理端**（密码/SSO 会话）签发**受限 Agent Access Token**，供**本机标准 ACP 客户端**（Zed / Cursor agent ACP / 其他合规 stdio 客户端）经本地 **stdio JSON-RPC adapter** 连接**云端 Linux 上的指定专家**：建会话、派任务、收增量与最终结果、读进度与已授权成果、取消对应任务——**不**获得完整浏览器账号会话，**不**启动本地 `OctopServer`，**不**复制服务器 DB。

### In scope（S0 = token + remote ACP adapter 端到端）

- 新增 **`/api/auth/agent-access-keys`** 资源（见 DEC-0045-01）：创建 / 列表 / 撤销；明文只返回一次；hash 存储；有效期；scope；专家 allowlist；最近使用；审计
- 专用认证 principal：`actor_kind=machine` + `credential_id` + owner + scopes + expert_allowlist；**每次** HTTP/WS 调用重检撤销/到期/用户禁用/专家授权/缩小范围
- 本地 CLI：**`octop acp-remote`**（stdio ACP agent）→ TLS 调云端受限 API；stdout **仅** ACP 协议；诊断写 stderr 并脱敏
- ACP 行为映射（基于锁文件真实 SDK，见 §2.1）：`initialize`、`session/new`、`session/prompt`、stream `session/update`、`session/cancel`、`session/request_permission`↔客户端回答、`session/load` / `session/resume`（按能力声明）、附件按协商如实声明
- 远端 thread / task / run ↔ ACP `sessionId` 可持久化恢复且受 token 范围限制
- 幂等：同一 `command_id` 重试至多一次副作用；不同 command 可续聊
- 断网后**不得**重发「已产生副作用但结果未知」的 prompt
- Codex：typed OpenAPI + 安全启动配置模板（无明文 token）
- 成对迁移 **038**；单元 + 集成 + **真实标准 ACP 客户端**互操作证据
- Windows 本地客户端 → Linux 云端；中文输入与附件引用正确

### Non-goals

- **不**把现有 `oak_` browser/device key 自动升级为 agent token；**不**默认给 agent token 开 `allow_browser` / `allow_devices`
- **不**经 `POST /api/auth/key-login` 把 agent token 换成无 scope 的完整账号 JWT，再声称 scope 已生效
- **不**把 `/api/acp`（出站 runner 配置）当成远程入站 ACP 服务；**不**把 Grok Build / `grok agent stdio` 出站工具当成「本地客户端接入 Octop 专家」
- **不**修改现有本地 `octop acp`（启动本机 `OctopServer`）的默认行为；remote 是**新命令**
- **不**因启用 ACP 自动获得 0044 P2P 或设备全盘权限；设备工具仍须显式 ExecutionContext + 设备授权
- **不**把本地 `cwd` 解释为服务器任意路径授权，也**不**默认选控制端执行
- **不**实现管理配置 / 用户管理 / 未允许专家 / 他人 thread / 未授权 resource 的访问
- **不**让机器 principal 经 `human=True` 默认自行批准验收或权限确认
- **不**修改 `dashboard/`（密钥 UI / 复制 / 撤销 / 配置模板由 Codex）
- **不**替换 Harness；**不**动 0039 macOS；**不**部署云端；**不**与 G3/G4 混进同一次重构 PR

### 模块边界

| 层 | 职责 | 禁止 |
| --- | --- | --- |
| `api/routers/auth_agent_keys.py`（新建）或 `auth.py` 旁路路由 | 薄 HTTP：创建/列表/撤销 agent-access-keys；OpenAPI | 在路由里签发后写明文到日志；走 key-login |
| `infra/auth/agent_access_keys.py`（新建） | 生命周期、hash、scope 校验、审计、principal 构造 | 复用 `authenticate(..., "browser")` 发完整会话 |
| `infra/db/repos/agent_access_keys.py` + 迁移 038 | 表/列持久化 | 业务状态机 |
| `api/deps.py` / JWT 中间件 | 识别 machine principal；scope 门禁依赖 | 把 `oaa_` 当 `oak_`；缺 scope 放行管理 API |
| `cli/commands/acp_remote.py`（新建） | stdio ACP agent；读 env/文件中的 token；调云端 | 启动 `OctopServer`；stdout 打诊断；argv 带明文 token |
| `infra/acp_remote/`（新建，建议） | session 映射持久化、HTTP 客户端、流式更新、取消、权限转发 | 复制服务器 DB；信任客户端自报越权 expert/thread |
| 既有 `cli/commands/acp.py` + `octop_harness.acp.server` | **仅**本机入站（本地 server） | 假定已支持 remote；为 G5 改坏本机路径 |
| `api/routers/acp.py` | 出站 runner 配置 | **≠** 远程 ACP；禁止冒充入站 |
| Codex `dashboard/` | 密钥 UI / 启动模板展示 | 后端实现 |

---

## 2. 复用映射（tip `99719e2`）与缺口

核对 worktree：`/workspace/octopus-g5` @ `99719e2`。

### 2.1 锁定的 ACP SDK / 协议版本（必须写入实现与测试）

| 项 | tip 实测值 | 来源 |
| --- | --- | --- |
| PyPI 包 | **`agent-client-protocol==0.11.0`**（锁文件解析；harness `extra == 'all'|'acp'` 要求 `>=0.9.0`） | `uv.lock` name=`agent-client-protocol` |
| Import 名 | `acp`（`from acp import …`） | tip `acp_bridge.py` / harness `acp/server.py` |
| Schema ref | **`refs/tags/schema-v1.16.0`** | 包内 `acp/meta.py` 头注释 |
| `PROTOCOL_VERSION` | **`1`** | `acp/meta.py` |
| 本机入站运行方式 | `run_agent(..., use_unstable_protocol=True)` | harness `run_harness_acp_server` |

**AGENT_METHODS（S0 必须实现或如实声明不支持）**

| JSON-RPC method | Python | S0 |
| --- | --- | --- |
| `initialize` | `initialize` | **必须** |
| `session/new` | `session_new` / `new_session` | **必须** |
| `session/prompt` | `session_prompt` / `prompt` | **必须** |
| `session/cancel` | `session_cancel` / `cancel` | **必须** |
| `session/load` | `session_load` / `load_session` | **必须**（能力 `loadSession=true`；无映射 → 明确错误） |
| `session/resume` | `session_resume` / `resume_session` | **应支持**若 SDK/客户端协商；否则 initialize 中**不要**谎报 resume 能力 |
| `session/close` | `session_close` / `close_session` | **应支持**（释放本地映射；不删远端历史） |
| `authenticate` / providers / nes / document.* | — | **S0 不实现**；勿宣告能力 |

**CLIENT_METHODS（adapter 作为 agent 调用客户端）**

| JSON-RPC method | S0 |
| --- | --- |
| `session/update` | **必须**（增量文本 / tool 进度摘要） |
| `session/request_permission` | **必须**（转发远端权限请求；等客户端选项；**禁止**机器自批） |
| `fs/*` / `terminal/*` / `mcp/*` / `elicitation/*` | S0 **默认不声明**；若实现须仍受云端授权，不得把本地 cwd 映射为服务器任意路径 |

> 禁止凭方法名猜版本。升级 SDK 须另开规格修订 PROTOCOL / schema tag。

### 2.2 tip 能力 → G5 复用

| 能力 | tip 现状 | 对 G5 的复用 | 缺口（才新增） |
| --- | --- | --- | --- |
| **`POST/GET /api/auth/access-keys` + revoke** | `oak_`；`allow_browser`/`allow_devices`；hash；一次明文；审计；上限 20 | **生命周期与审计模式**（创建/列表/撤销/touch/throttle 思路） | **无** scope / expert allowlist / machine principal；`oak_`≠受限任务 token |
| **`POST /api/auth/key-login`** | browser key → **完整账号 JWT**（`auth_key_id`） | 证明「换 JWT = 完整会话」；G5 **禁止**对 agent token 走此路径 | 需独立认证路径 |
| **`octop acp`** | 启动**本地** `OctopServer` + `run_harness_acp_server` | 可参考 harness ACP Agent 类与 `use_unstable_protocol=True` | **无** remote 模式；会启本地 server（G5 禁止） |
| **`/api/acp`** | 出站 runner 配置 | **不复用为入站** | 文档/UI 文案必须区分 |
| **threads + `/inputs` + `command_id`** | 持久输入队列；幂等 | prompt → input；续聊/重试语义 | 须绑定 machine 创建范围；进度不得走 steer |
| **history / run-events / resources** | 已有鉴权 API | 读进度与成果 | scope + 所有权门禁；机器不可越权 |
| **task-board `human=True` 默认** | `TaskBoardService.action(..., human=True)`；agent 工具显式 `human=False` | 证明默认对人；G5 机器路径**必须**显式 `human=False` 且拒绝人类验收动作 | 缺 machine principal 贯通 |
| **0043 work-items（规格 Ready，tip 未必已合）** | 进度只读、取消边界、`task.changed` | **优先**任务通道 | 未合时用 thread+run_events 降级，仍遵守只读进度 |
| **0039 device ACP runners** | 出站 runner 设备覆盖 | **无关**入站 remote | 勿混 |

**结论**：tip **没有**受限 agent token，也**没有**「标准客户端 → 云端专家」的 remote ACP adapter。S0 必须新增 **agent-access-keys + machine principal + `octop acp-remote`**。

---

## 3. DEC（拍板）

| ID | 决议 | 状态 |
| --- | --- | --- |
| **DEC-0045-01** | **API 形态**：新增明确资源 **`/api/auth/agent-access-keys`**（不扩展 `oak_` 创建 body 混用）。Codex 与 OpenAPI 只认此资源。旧 `/access-keys` 行为不变 | resolved |
| **DEC-0045-02** | **密钥前缀**：agent secret = **`oaa_`** + `token_urlsafe(32)`。`oak_` 保持 browser/devices。`oaa_` **拒绝** `key-login`；`oak_` **拒绝**作为 agent Bearer 调受限任务 API | resolved |
| **DEC-0045-03** | **认证**：`Authorization: Bearer <oaa_…>` 直接校验 hash → 构造 machine principal（推荐 S0）。可选：`POST /api/auth/agent-access-keys/exchange` 签发**短时** JWT，claims 必须含 `actor_kind=machine`、`auth_key_id`、`scopes`、`experts`；**禁止**与 browser JWT 同形可互换。每次请求重检 credential 状态 | resolved |
| **DEC-0045-04** | **Scopes（枚举冻结）**：`experts.read` \| `tasks.create` \| `tasks.read` \| `tasks.input` \| `tasks.cancel` \| `resources.read`。创建时至少 1 个；缺省**空则非法**。新 token **默认** `allow_browser=0`、`allow_devices=0`（若表有旁路列也不得开启） | resolved |
| **DEC-0045-05** | **专家 allowlist**：创建时必填非空 `expert_ids[]`（agent_id / expert 绑定 ID，与 tip 专家列表一致）。token 只能对 allowlist 内专家建会话/派任务。缩小 allowlist 或取消共享 → 立即 403 | resolved |
| **DEC-0045-06** | **对象范围**：默认只能访问**本 credential 创建**的 session/task 及其显式授权成果。接入既有人类会话须**单独授权字段**（S0 默认**关闭**；若打开须创建时显式 `allow_existing_threads=false` 默认）。禁止仅凭猜 thread_id 进入任意历史 | resolved |
| **DEC-0045-07** | **发行权限**：仅密码/SSO 浏览器会话可创建；带 `auth_key_id` 的 JWT（含 machine）**不能**再生成 token（对齐 tip access-keys） | resolved |
| **DEC-0045-08** | **Principal**：`actor_kind=machine`、`credential_id`、`owner_user_id`、`scopes`、`expert_allowlist`。task-board/actions、权限审批、人类验收：**不得**沿用 `human=True`；机器调用必须 `human=False` 且对确认/验收类动作 **403** | resolved |
| **DEC-0045-09** | **CLI 命令名**：新命令 **`octop acp-remote`**（不改默认 `octop acp`）。参数：`--server URL`、`--expert ID`、`--token-file PATH`（推荐）；环境变量：`OCTOP_ACP_SERVER`、`OCTOP_ACP_EXPERT`、`OCTOP_ACP_TOKEN_FILE`（或 `OCTOP_ACP_TOKEN`，仅当无法用文件）。**禁止** `--token` 明文进 argv 的文档推荐路径 | resolved |
| **DEC-0045-10** | **Adapter 进程边界**：不启动本地 `OctopServer`；不要求本地 DB；stdout=ACP only；stderr=脱敏诊断；协议 = `agent-client-protocol` **0.11.0** / schema-v1.16.0 / `PROTOCOL_VERSION=1` / `use_unstable_protocol=True`（与 harness 本机入站一致，避免客户端握手失败） | resolved |
| **DEC-0045-11** | **Session 映射**：本地持久化（用户配置目录，如 `~/.octop/acp-remote/sessions.json`）保存 `acp_session_id → {server, expert_id, remote_thread_id, remote_task_id?, last_command_id?, credential_id}`。恢复受 token 范围限制；越权映射删除并报错 | resolved |
| **DEC-0045-12** | **任务通道**：若 0043 work-items 已合 → `session/new`+首个 prompt 可创建 work-item；进度 `GET` 只读；取消走 work-item cancel。若未合 → 创建专用 remote thread（metadata 标记 `source=acp-remote`），prompt→`/inputs`，进度→`run-events`/`history` **只读**，取消→对应 run/input 取消语义。两种路径都禁止进度查询写 worker | resolved |
| **DEC-0045-13** | **幂等与断网**：每个 `session/prompt` 生成稳定 `command_id`（ULID）；重试同 id 至多一次副作用。若本地已发出但结果未知 → 只查询状态，**不**新开副作用 prompt。不同 command_id 允许续聊 | resolved |
| **DEC-0045-14** | **权限请求**：远端需要人类/客户端批准时，adapter 发 `session/request_permission`；等待客户端选项。超时/拒绝按远端策略失败。**禁止** adapter 对 machine principal 自动选 allow | resolved |
| **DEC-0045-15** | **执行上下文**：设备工具仍要显式 ExecutionContext + 设备授权。本地 cwd **不是**服务器路径授权；server URL / expert / 文件源目标必须显式；禁止把 Windows 绝对路径复制到 Linux 执行端当工作目录 | resolved |
| **DEC-0045-16** | **迁移编号**：成对 **`038_agent_access_keys.sql` + `038_agent_access_keys.pg.sql`**。0043→036、0044→037（总管已确认）。若合并时 038 被占 → **待总管确认**，禁止改已上线迁移 | resolved |
| **DEC-0045-17** | **旧 key 兼容**：`oak_` 行为不变；**不**自动迁移为 `oaa_`；文档明确两者差异。列表 API 分离，避免 UI 混淆 | resolved |
| **DEC-0045-18** | **验收证据**：AC-0045-01 必须用**真实标准 ACP 客户端**（推荐 Zed 或官方/社区合规 stdio 客户端）；仅 curl/httpx **不能**宣称 ACP 已支持 | resolved |

---

## 4. 契约（冻结）

### 4.1 Agent Access Keys（Codex HTTP）

鉴权：创建/列表/撤销 = 密码/SSO `current_user`（**禁止** machine / access-key JWT）。  
使用 token 的业务 API = machine principal（Bearer `oaa_` 或 scoped exchange JWT）。

#### 4.1.1 创建

`POST /api/auth/agent-access-keys` → **201**

```json
{
  "name": "laptop-zed",
  "days": 30,
  "scopes": ["experts.read", "tasks.create", "tasks.read", "tasks.input", "tasks.cancel", "resources.read"],
  "expert_ids": ["opaque-expert-or-agent-id"],
  "allow_existing_threads": false
}
```

**响应 201**（`secret` 仅此一次）：

```json
{
  "key": {
    "key_id": "01JBKEY...",
    "owner_user_id": 1,
    "name": "laptop-zed",
    "prefix": "oaa_",
    "scopes": ["experts.read", "tasks.create", "tasks.read", "tasks.input", "tasks.cancel", "resources.read"],
    "expert_ids": ["opaque-expert-or-agent-id"],
    "allow_existing_threads": false,
    "expires_at": 1765000000.0,
    "revoked_at": null,
    "last_used_at": null,
    "created_at": 1762400000.0
  },
  "secret": "oaa_…",
  "acp_launch": {
    "command": "octop",
    "args": ["acp-remote", "--server", "https://example.example", "--expert", "opaque-expert-or-agent-id", "--token-file", "%OCTOP_ACP_TOKEN_FILE%"],
    "env_names": ["OCTOP_ACP_SERVER", "OCTOP_ACP_EXPERT", "OCTOP_ACP_TOKEN_FILE"],
    "protocol": {
      "package": "agent-client-protocol",
      "package_version": "0.11.0",
      "schema_ref": "refs/tags/schema-v1.16.0",
      "protocol_version": 1
    },
    "notes": "Put the secret in a private file referenced by OCTOP_ACP_TOKEN_FILE. Never paste the secret into IDE args."
  }
}
```

#### 4.1.2 列表 / 撤销 / 可选专家候选

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/auth/agent-access-keys` | 无 `secret`；含 prefix/scopes/experts/expiry/last_used/revoked |
| `POST` | `/api/auth/agent-access-keys/{key_id}/revoke` | **204**；后续一切调用失败 |
| `GET` | `/api/auth/agent-access-keys/experts` | 当前用户可写入 allowlist 的专家摘要（需已登录人类会话） |
| `POST` | `/api/auth/agent-access-keys/exchange` | 可选；body `{ "secret": "oaa_…" }` → 短时 machine JWT |

错误：`401` 未登录；`403` 用 key 会话创建 / 无权限；`422` scope/专家非法；`429` 数量上限（建议对齐 20 或单独限额，实现写清）。

OpenAPI：每个路由须有 summary + response schema（含 `AgentAccessKeyInfo`、`AgentAccessKeyCreated`、`AgentScope` 枚举）。

### 4.2 受限云端 API（machine 可调用的最小面）

> 路由可复用 tip 路径，但**鉴权与授权过滤器**必须认 machine + scope。未列面一律 403。

| Scope | 允许的调用（示意） |
| --- | --- |
| `experts.read` | 读取 allowlist 内专家元数据（非全局管理） |
| `tasks.create` | 创建 remote session / work-item（仅 allowlist 专家） |
| `tasks.read` | 读自己 credential 创建的 task/thread 状态、run-events、history（范围内） |
| `tasks.input` | `POST .../inputs` 或 work-item input（`command_id` 幂等） |
| `tasks.cancel` | 取消**对应** task/run；不影响其它 token 的任务 |
| `resources.read` | 读**已授权** resource metadata/content |

**硬拒绝**：`/api/admin*`、用户管理、全局配置、未允许专家、他人 thread、未授权 resource、devices enroll（无 devices scope 且本 token 默认无）、`/api/acp` runner 写配置、创建新 agent-access-key。

### 4.3 ACP adapter：JSON-RPC 方法表（stdio）

进程：`octop acp-remote …`  
传输：stdio JSON-RPC（`acp.run_agent` / 等价 AgentSideConnection）。  
能力声明（initialize 响应须诚实）：

```json
{
  "protocolVersion": 1,
  "agentCapabilities": {
    "loadSession": true,
    "promptCapabilities": { "image": false, "audio": false, "embeddedContext": false }
  },
  "agentInfo": { "name": "octop-acp-remote", "title": "Octop Remote Expert", "version": "<octop-version>" }
}
```

| Client → Agent | 云端动作 | 失败 |
| --- | --- | --- |
| `initialize` | 本地握手；可 HEAD/鉴权探测 server（失败则后续 session 明确错） | 协议不匹配 |
| `session/new` | 校验 expert ∈ allowlist；创建远端 thread 或 work-item；持久化映射；返回 `sessionId` | 401/403/专家不在名单 |
| `session/prompt` | 生成/复用 `command_id`；`tasks.input`；订阅/轮询更新 → `session/update`；结束 `PromptResponse.stopReason` | 幂等冲突 409；撤销 401 |
| `session/cancel` | 仅取消该 session 映射的远端 task/run | 找不到映射 |
| `session/load` / `session/resume` | 读本地映射 + 远端仍授权则恢复；不新建任务、不重放未知副作用 | 越权/撤销 → 错误 |
| `session/close` | 清本地映射（可选通知远端）；保留远端历史 | — |
| Agent → `session/request_permission` | 远端审批需求 | 客户端拒绝/超时 → 远端失败 |
| Agent → `session/update` | 增量消息/工具摘要（无密钥） | — |

附件：S0 若未实现 embedded resource，initialize **不得**宣称 `embeddedContext=true`。中文文本按 UTF-8 原样上传。

### 4.4 IDE 配置示例（无明文）

Zed `settings.json` 示意：

```json
{
  "agent_servers": {
    "Octop Cloud": {
      "command": "octop",
      "args": ["acp-remote", "--token-file", "C:/Users/you/.octop/oaa-laptop.token"],
      "env": {
        "OCTOP_ACP_SERVER": "https://octop.example",
        "OCTOP_ACP_EXPERT": "opaque-expert-or-agent-id"
      }
    }
  }
}
```

---

## 5. REQ / AC

### Requirements

| ID | 要求 |
| --- | --- |
| **REQ-0045-01** | 人类会话可创建 `oaa_` agent key；明文一次；hash 存储；可撤销；列表无明文 |
| **REQ-0045-02** | Token 带 scopes + expert allowlist + owner；默认无 browser/devices |
| **REQ-0045-03** | Machine principal 贯穿；每次调用重检撤销/到期/禁用/缩权 |
| **REQ-0045-04** | `octop acp-remote` 对标准客户端提供 §4.3 方法；不启本地 OctopServer |
| **REQ-0045-05** | Session 映射可恢复；不重复创建任务；不重放未知副作用 prompt |
| **REQ-0045-06** | `command_id` 幂等；取消仅影响对应远端会话/工作项 |
| **REQ-0045-07** | 权限提示保留；机器不可 `human=True` 自批 |
| **REQ-0045-08** | 进度只读（对齐 0043 DEC-0043-06）；不插入 worker 消息 |
| **REQ-0045-09** | 日志/异常/argv/测试快照无 token、Cookie、provider key |
| **REQ-0045-10** | Windows→Linux 云端；中文与附件引用正确（在已声明能力内） |
| **REQ-0045-11** | 迁移 038 成对；`oak_` 兼容策略见 DEC-0045-17 |
| **REQ-0045-12** | Codex OpenAPI + `acp_launch` 模板无明文 |

### Acceptance

| ID | 场景 | 期望 |
| --- | --- | --- |
| **AC-0045-01** | **真实标准 ACP 客户端**连接 `octop acp-remote` | 建会话 → 云端专家收任务 → 增量 + 最终结果。**禁止**仅 curl 冒充 |
| **AC-0045-02** | 客户端重启/断线后 load/resume | 恢复同一授权会话；不重复建任务；不重跑未知副作用 |
| **AC-0045-03** | 同 `command_id` 重试 vs 新 command | 同 id ≤1 次副作用；新 id 可续聊 |
| **AC-0045-04** | 撤销 / 到期 / 用户禁用后 | HTTP 与既有 WS/adapter 后续调用均失败 |
| **AC-0045-05** | 越权面 | 管理配置、用户管理、未允许专家、他人 thread、未授权 resource → 403/404 |
| **AC-0045-06** | 权限请求 | 客户端可见选项；机器 token 无法经 human 默认自批 |
| **AC-0045-07** | 取消 | 仅对应 task/run 停；另一任务继续；进度查询无新 worker user 消息 |
| **AC-0045-08** | 密钥泄漏面 | 日志/异常/进程参数/测试快照无 `oaa_`/`oak_` 明文、Cookie、provider key |
| **AC-0045-09** | Win 本地 → Linux 云端 | 成功；中文 prompt 往返正确 |
| **AC-0045-10** | `key-login` + `oaa_` | **失败**；`oak_` 作 agent Bearer 调 tasks API → **失败** |

---

## 6. 迁移 / 错误码 / 授权

### 6.1 迁移 038

新建表 **`agent_access_keys`**（推荐与 `account_access_keys` 分离，避免 CHECK 与语义污染）：

- `key_id` PK、`owner_user_id` FK、`name`、`secret_hash` UNIQUE  
- `scopes_json` TEXT NOT NULL  
- `expert_ids_json` TEXT NOT NULL  
- `allow_existing_threads` INTEGER NOT NULL DEFAULT 0  
- `expires_at` / `revoked_at` / `last_used_at` / `created_at`  
- 索引：`(owner_user_id, created_at DESC)`、`secret_hash`

成对：`038_agent_access_keys.sql` + `038_agent_access_keys.pg.sql`。  
**不**改 023/`account_access_keys` 历史迁移。若 038 撞车 → 待总管确认新号。

### 6.2 错误码（建议）

| 场景 | ErrorCode / HTTP |
| --- | --- |
| 无效/撤销/过期 token | `AUTH_FAILED` 401 |
| scope 不足 / 专家不在名单 / 他人对象 | `FORBIDDEN` 403 |
| 幂等冲突载荷 | `CONFLICT` 409 |
| 创建参数非法 | `DEVICE_INVALID` 或既有 validation 422 |
| 用户禁用 | `USER_DISABLED`（与 tip 一致） |

### 6.3 授权矩阵（摘要）

| 动作 | 人类 SSO/密码 | `oak_` browser JWT | `oaa_` machine |
| --- | --- | --- | --- |
| 创建 agent key | ✅ | ❌ | ❌ |
| 使用 tasks.* | ✅（完整会话） | ✅（完整会话，非本规格重点） | ✅ 仅 scope+allowlist |
| key-login | n/a | ✅ browser | ❌ |
| 管理/用户 API | 按角色 | 按角色 | ❌ |
| task-board 人类确认 | ✅ human | ✅ | ❌ |

---

## 7. Coder 实现指南与测试

### 建议分支

`feature/0045-agent-access-token-and-acp-adapter`（基线 `99719e2`+；若 0043 已合可基于其 tip 以启用 work-items 路径）

### 建议触及路径

- `src/octop/api/routers/auth_agent_keys.py`（或 `auth.py` 扩展但保持资源分离）
- `src/octop/infra/auth/agent_access_keys.py`
- `src/octop/infra/db/repos/agent_access_keys.py`
- `src/octop/infra/db/migrations/038_agent_access_keys.sql` + `.pg.sql`
- `src/octop/api/deps.py`（machine principal）
- `src/octop/cli/commands/acp_remote.py` + `cli/main` 注册
- `src/octop/infra/acp_remote/`（session store、HTTP、stream、权限桥）
- 业务路由的 scope 门禁（threads/inputs/history/run-events/resources/work-items）
- `tests/unit/auth/test_agent_access_keys_0045.py`
- `tests/integration/test_acp_remote_0045.py`
- **互操作**：文档化手动/半自动 Zed（或等价）步骤与录屏/日志证据（脱敏）

### 实现要点

1. **先门禁后业务**：deps 解析 `oaa_` → principal；路由装饰/依赖检查 scope。  
2. **禁止捷径**：测试必须覆盖「key-login(oaa_) 失败」与「无 scope JWT 假成功」。  
3. **Adapter**：实现 `Agent` Protocol 时 **实现类在前**（与 harness 注释一致），避免 Protocol stub 返回 null。  
4. **流式**：可用短轮询 run-events + 可选 WS；UI 体验可后续优化，但 AC-0045-01 须有增量。  
5. **取消**：映射到准确远端 id；另一 session 不受影响。  
6. **0043**：检测 work-items 路由/表存在则走 work-items；否则降级 thread 路径，测试两种或 skip 标记。  
7. **密钥**：红片断言；token-file 权限提示（Unix 0600 建议）。

### 测试命令

```bash
uv run pytest tests/unit/auth/test_agent_access_keys_0045.py tests/integration/test_acp_remote_0045.py -q
# 须含：scope 拒绝、撤销后失败、command_id 幂等、human 自批拒绝、key-login(oaa_) 失败
# AC-0045-01：真实标准客户端证据（步骤写入 PR；禁止只交 curl）
make all   # 须绿；CI Linux + Windows
```

### 交付物（Coder → Codex / 总管）

- §4 OpenAPI / JSON 冻结示例  
- `acp_launch` 模板（无明文）  
- 实际测试命令与结果 + **标准客户端互操作证据**  
- 未实现项显式列出（如 elicitation、fs/terminal、embeddedContext）  
- 迁移 038 成对验证；若编号冲突已升级总管  

---

## 8. 与其它规格

| 规格 | 关系 |
| --- | --- |
| **0039 device ACP runners** | **出站** runner 设备覆盖；**≠** G5 入站 remote；本规格不改 0039 |
| **0011 ACP presets** | 出站预设；不解决本地客户端接云端专家 |
| **`docs/acp.md` / `octop acp`** | 本机入站；G5 新增 `acp-remote` 后应在实现 PR 更新文档（本规格阶段只写 specs） |
| **`/api/acp`** | 出站配置 ≠ 远程 ACP 服务 |
| **0041** | 账户事件可提示；非硬依赖 |
| **0043 G3** | 进度只读/取消/work-items **优先复用**；未合时可降级；机器不可破坏其硬边界 |
| **0044 G4** | 启用 ACP **不**自动获 P2P；文件直连另授权 |
| **0004 / oak_ keys** | 生命周期模式可借鉴；语义分离（DEC-0045-02/17） |
| **0039 macOS** | **搁置**；勿派 |

### Evolution（非 S0）

- 更丰富的 ACP 能力（embeddedContext、fs、terminal）在云端授权下开放  
- 官方一键安装包与 IDE 市场配置  
- 细粒度 resource grant 票据  
- 与 0043 深度绑定的 ACP session ≡ work_item 一等可视化（Codex）  

### 风险

| 风险 | 缓解 |
| --- | --- |
| curl-only 冒充 ACP | DEC-0045-18；AC-0045-01 |
| 换成无 scope browser JWT | DEC-0045-02/03；AC-0045-10 |
| 机器自批 | DEC-0045-08/14；AC-0045-06 |
| 与本地 `octop acp` 混淆 | 新命令名；文档区分 |
| 迁移撞车 | DEC-0045-16；总管确认 |
| 进度插入 worker | DEC-0045-12；AC-0045-07 |
| 本地路径落到 Linux | DEC-0045-15 |

---

## 9. Ready 检查

- [x] 第二实现者无需猜测：HTTP + ACP 方法表 + SDK 版本已冻  
- [x] 明确「标准 ACP 客户端」验收，禁止 curl-only  
- [x] 与 oak_/key-login/`/api/acp`/出站 runner/本地 `octop acp` 边界硬性  
- [x] machine principal 与 human 默认隔离  
- [x] 复用映射已写；tip 无 remote adapter  
- [x] 迁移 038 避让 036/037；冲突升级总管  
- [x] 0039 Mac / 正式 `0039-device-acp-runners` 未当作本规格实现面；Mac 搁置  
- [x] **可立刻派 Coder**（建议分支 `feature/0045-agent-access-token-and-acp-adapter`；基线 `99719e2`+；若需 work-items 路径则等/叠 0043）  

**Contract: Ready · Rev 2026-11-07.1**
