# 0011 ACP 预置扩展 + 配置归属铁律 + 模型预置刷新（给 GPT 可直接开发）

- Spec ID: `0011-acp-preset-extensions`
- Status: **Implemented in PR (T0 / T1.1–T1.6); T1.7 and T2 release pending**
- Revision: `2026-10-12.3`
- Date: 2026-10-12
- Authoritative path: `docs/specs/0011-acp-preset-extensions.md`
- Handoff: 本文即完整 handoff；若拆分请同步 `docs/specs/0011-gpt-handoff.md` 并在此指向。
- Relates:
  - `docs/acp.md`（Dashboard outbound runners 表 + 故障排查）
  - `docs/octopus/device-acp.md`（专家 `device_binding` / 远程 ACP）
  - `src/octop/infra/agents/settings/acp.py`（`_OCTOP_BUILTIN_RUNNERS`）
  - `src/octop/api/routers/acp.py`（`_BUILTIN_RUNNERS` 删除白名单）
  - `dashboard/src/pages/Agent/ACP/constants.ts` + i18n + 卡片/图标
  - harness 包内：`octop_harness.acp.models._BUILTIN_RUNNERS` / `default_acp_runners()`；`octop_harness/providers/provider_template.json`
  - `src/octop/infra/db/repos/providers.py`（**无 user_id**，整站一份——缺口）
  - `src/octop/infra/devices/acp_bridge.py` / `acp_process.py`（远程不传 hub runner env）
- Non-overwrite: **勿修改** Accepted `0004` 正文；**勿改** enroll / device 协议；本实现阶段可改业务代码的是 **GPT/后续 Coder**，架构师本回合 **只交 docs**。

---

## 0. 给 GPT 的阅读顺序

1. §1 目标 / 非目标
2. §2 **铁律**：配置归属（设备 vs 账号/中枢 vs 半全局）——产品与实现硬约束
3. §3 任务拆分（可勾选）——按 T0 → T1 → T2 顺序做
4. §4–§6 各轨精确路径、伪代码、验收、风险
5. §7 Evolution / Out of scope

仓库根（Windows）：`D:\Agent_Workspace\octopus\octop-source`
依赖：`octop-harness[all]>=1.0.1`（`pyproject.toml` / `uv.lock` 现为 **1.0.1**）。
`provider_template.json` **不在本仓源码树**，在 **octop-harness 包**内；本仓安装副本见 `.venv/Lib/site-packages/octop_harness/providers/provider_template.json`。

---

## 1. 目标 / 非目标

### 1.1 目标

| 轨 | 目标 |
|----|------|
| **T0 配置归属** | 把「跟账号 / 跟设备 / 半全局」写成产品与实现铁律；标明 **providers 整站一份** 缺口，并给出按账号隔离的 schema/API 改法（可与 ACP 分 PR，但必须写进方案）。 |
| **T1 ACP 预置** | Dashboard `/acp` 预置卡片新增 **Hermes**、**Grok Build**（P0）与 **OpenClaw**（P1）；后端合并逻辑、API 删白名单、i18n、`docs/acp.md` 同步；默认关、不可删。 |
| **T2 FU-001** | 在 **octop-harness** 刷新 `provider_template.json`（补独立 **xAI** grok-4.7/4.6/4.5；更新老旧海外模型；补缺主流渠道），本仓 **只 bump** harness 依赖并验证 Dashboard「设置 → 模型」。 |

### 1.2 非目标

- **排除 Grok Bot 产品**进 ACP 列表（它不是 stdio CLI runner / 云端对话通道另议）。
- 不实现 OpenClaw 完整 Gateway 运维 UI / 一键安装 Gateway。
- 不改 ACP 协议本身、不改 `acp_runner` 工具 action 语义、不做 inbound `octop acp`。
- **不修改** Accepted `0004` 正文；不改 enroll / device 协议。
- 本架构师回合 **只改 docs**；实现由 GPT（或日后 Coder）按本文件执行。
- 不做手机端 ACP。
- FU-001 **禁止**把 `provider_template.json` 复制进 Octop 业务仓当第二份真相源。

---

## 2. 铁律：配置归属（设备 vs 账号/中枢 vs 半全局）

> **产品/实现硬约束。** 任何 PR 若把「跟设备」的东西写进 hub DB、或把「跟账号」的密钥只落在 device-state，视为不合格。

### 2.1 跟账号 / 中枢（hub，按 user 隔离）

| 配置 | 现状（2026-10-12 代码） | 铁律 |
|------|-------------------------|------|
| 模型提供商与 API Key | `providers` 表 **无 `user_id`**，`ProviderRepo.list_all()` 整站一份；写接口在 `admin_router`（admin-only write） | **应**按账号隔离（见 §4 缺口改造）；Key 不得写入 device-state |
| 预置模板（LLM presets） | harness `provider_template.json` → `octop.infra.agents.providers.presets.load_provider_presets` | 只读模板；用户启用后的实例跟账号 |
| 会话 / 专家选模 | 会话与 agent config 已按 user/agent | 保持跟账号 |
| ACP runner **定义与开关** | `ACPSettingsStore`：`settings` key = `acp_runners:user:{user_id}`；agent 仅存 `acp.tool_enabled` | **已正确**：定义跟账号；工具开关跟专家 |
| 专家 `device_binding` **记录** | agent `config.device_binding`（device_id + root_id）存 hub | **记录**跟账号/专家；真正进程在设备 |
| IM 通道 / Connectors | 通道与 connector 按账号 | 保持跟账号 |
| 专家工作区与记忆 | 工作区策略 / memory 按 user/agent | 保持跟账号 |

### 2.2 跟设备（执行端本机）

| 配置 | 现状 | 铁律 |
|------|------|------|
| 设备权限 / 共享目录 / `acp_run` | `devices` 权限集含 `acp_run`（HIGH_RISK）；`RemoteACPService._binding()` 校验 `acp_run` + 可写 root | 授权与目录跟设备；hub 只存 grant 元数据 |
| 本机 CLI 安装与登录态 | PATH 上的 `hermes` / `grok` / `openclaw`；CLI 自己的 `~/.hermes`、xAI login 等 | **必须在设备本机**；hub 不代装 |
| device-state 凭证与入口 URL | `acp_process.py` 明确：**No account token, manager environment or ACP output is written to device state** | device-state 只放设备连接/入口所需最小凭证，**禁止**塞 hub API Key / runner env 密钥 |
| 真正 ACP 进程与 cwd | 远程：`acp.open` 在设备 `cwd=共享目录 path` 上 `create_subprocess_exec`；本地 hub：harness `service.py` spawn | 进程永远在「跑的那台」上；cwd = 绑定共享目录（远程）或会话工作区（本地） |

### 2.3 半全局（一份定义，绑哪台跑哪台）

| 规则 | 说明 | 代码锚点 |
|------|------|----------|
| Dashboard ACP **一份定义** | 每用户一份 runner 字典（enabled/command/args/env/trusted…），所有专家共用定义；专家只开关 `acp_runner` tool | `ACPSettingsStore.load_runners(user_id)` |
| 绑哪台跑哪台 | 专家 `device_binding` → `RemoteACPService`；未绑定则本地 harness spawn | `docs/octopus/device-acp.md`；桌面「操控目标」与 binding **相互独立**（0008） |
| **远程不传 hub runner env** | `acp.open` 载荷 **仅** `root_id` / `runner` / `command` / `args`——**无 env** | `acp_bridge.py` → `executor.py` → `DeviceACPProcesses.open(command, args, cwd)` 使用**设备进程环境** |
| 本地可传 env | hub 本机 spawn：`spawn_env = overlay(os.environ, cwd/.env, runner_config.env)` | `octop_harness/acp/service.py` |

**实现含义（OpenClaw / 任意需 token 的 runner）：**

- 远程设备跑时：token 必须在 **设备本机**（设备 OS env，或设备上的 `--token-file` 路径）。
- **禁止**指望把 `OPENCLAW_GATEWAY_TOKEN` 写在 Dashboard runner env 后远程自动生效（当前协议不传）。
- 文档与 intro 必须写清：「本地 hub 跑」可用 runner env；「远程设备跑」请在设备侧配置。

### 2.4 现状缺口：providers 整站一份 vs 文档/产品按用户

**证据：**

- `ProviderRow` 字段：`id, name, kind, base_url, api_key, …`——**无 `user_id`**。
- `ProviderRepo.list_all()` / `get_by_name(name)` 全局唯一 name。
- `GET /api/providers` 注释：*Return all providers. Read-only for regular users.*；写操作走 `/api/admin/providers`。

**多用户同 hub 时：** A 的 API Key 对 B 只读可见（若 UI 暴露）或至少共享同一套模型实例——与「跟账号」铁律冲突。

**改造步骤（T0，可独立 PR，勾选任务见 §3）：** 见 §4。

---

## 3. 任务拆分（可勾选）

### T0 — 配置归属文档落地 + providers 按账号隔离（缺口）

- [x] **T0.1** 实现/评审时对照 §2 铁律做 code review checklist（远程不传 env、Key 不进 device-state、ACP 定义跟 user）。
- [x] **T0.2** DB：`providers` 表加 `user_id`（NOT NULL，FK users）；迁移回填策略见 §4。
- [x] **T0.3** `ProviderRepo`：所有查询带 `user_id`；`get_by_name(user_id, name)`；去掉全局唯一 name 或改为 `(user_id, name)` UNIQUE。
- [x] **T0.4** API：普通用户 CRUD 自己的 providers；admin 可代管；`GET /presets` 仍全局只读模板。
- [x] **T0.5** Dashboard「设置 → 模型」按登录用户隔离；共享专家场景明确「用所有者的 provider」或「调用方 provider」（产品二选一，默认 **所有者**）。
- [x] **T0.6** 回归：多用户同 hub，A 的 key 对 B 不可见；选模列表互不泄漏。

> T0 可与 T1 **分 PR**。若额度只够做 ACP，至少合并 §2 铁律进评审，T0.2–T0.6 开 follow-up issue 并链接本 spec。

### T1 — ACP 预置扩展（P0 + P1）

- [x] **T1.1** `src/octop/infra/agents/settings/acp.py`：`_OCTOP_BUILTIN_RUNNERS` 追加 `hermes` / `grok_build` / `openclaw`（样例 §5.3）。
- [x] **T1.2** `src/octop/api/routers/acp.py`：`_BUILTIN_RUNNERS` frozenset 同步三 id。
- [x] **T1.3** `dashboard/src/pages/Agent/ACP/constants.ts`：`BUILTIN_RUNNER_ORDER` 在 `pi` 后追加；icons/label/intro keys 补全（无官方图则 `custom-provider.svg`）。
- [x] **T1.4** `dashboard/src/locales/zh.json` + `en.json`：`acp.runner_*` / `acp.intro_*`；OpenClaw intro 强调 Gateway + token 安全 + 远程 env 限制。
- [x] **T1.5** `docs/acp.md`：Built-in 表 + Troubleshooting（Hermes `--check`、Grok 安装/鉴权、OpenClaw Gateway、远程不传 env）。
- [x] **T1.6** 测试：无用户 settings 时 GET 含新 key 且 `enabled=false`；DELETE 内置 → 403；自定义 runner CRUD 不受影响。
- [ ] **T1.7** 手工验收：§5.5 清单（PATH/`--check`、权限流、token 不进 process list）。

### T2 — FU-001 模型预置刷新（harness JSON + 本仓 bump）

- [ ] **T2.1** 在 **octop-harness** 仓改 `providers/provider_template.json`（步骤 §6）。
- [ ] **T2.2** 新增独立 **xAI** provider（id 建议 `xai`），模型 **grok-4.7 / grok-4.6 / grok-4.5**（以发版时官网为准，注释写清核对日）。
- [ ] **T2.3** 更新 OpenAI / Anthropic / OpenRouter / Gemini 等海外预置：去掉过时 id，补稳定渠道当前主力 id。
- [ ] **T2.4** 发布 harness 新版本 → 本仓 `pyproject.toml` / `uv.lock` **只 bump** `octop-harness`（当前 `>=1.0.1` / lock `1.0.1`）。
- [ ] **T2.5** 验证：Dashboard 设置 → 模型 / 预设列表出现 xAI 与刷新后的模型；**无**第二份 JSON 进 Octop 仓。

### 明确不做（勾选确认）

- [x] **X.1** 不出现 Grok Bot 作为 ACP runner id/卡片。
- [x] **X.2** 不把 FU-001 与 T1 强行绑成「必须同 commit」（可同 release，可分 PR）。
- [x] **X.3** 不改 Accepted `0004`。

---

## 4. T0 详细：providers 按账号隔离

### 4.1 精确文件路径

| # | 路径 | 改什么 |
|---|------|--------|
| 1 | `src/octop/infra/db/migrate.py`（及迁移片段） | `providers` 增加 `user_id INTEGER NOT NULL REFERENCES users(id)`；`UNIQUE(user_id, name)` |
| 2 | `src/octop/infra/db/repos/providers.py` | `ProviderRow` + 全方法加 `user_id`；废弃全局 `get_by_name(name)` |
| 3 | `src/octop/api/routers/providers.py` | 用户级 CRUD；admin 路由可指定 user 或保持超管全局视图 |
| 4 | `src/octop/infra/agents/providers/store.py` 及 `harness_factory.py` | 按当前 user 同步到 harness |
| 5 | `src/octop/api/routers/setup.py` | bootstrap 写入 **该 admin/user** 的 providers |
| 6 | Dashboard 模型/Provider 相关页 | 仅展示当前用户数据 |
| 7 | 测试 | 双用户隔离用例 |

### 4.2 迁移伪代码

```text
1. ALTER TABLE providers ADD COLUMN user_id INTEGER NULL;
2. 回填：若系统仅有一名 admin → 全部 user_id = admin.id；
   若多用户 → 默认挂到「历史创建者」或要求运维指定 PRIMARY_OWNER_USER_ID 环境变量后回填。
3. 确认无 NULL 后：user_id NOT NULL + FK + UNIQUE(user_id, name)。
4. 删除旧的全局 UNIQUE(name)（若有）。
```

### 4.3 API 步骤

```text
GET    /api/providers              → 仅当前登录用户
POST   /api/providers              → 当前用户创建（不必再强制 admin；或保留 admin 专口）
PATCH  /api/providers/{id}         → 仅所有者（或 admin）
DELETE /api/providers/{id}         → 仅所有者（或 admin）
GET    /api/providers/presets      → 仍为全局模板（无密钥）
GET    /api/admin/providers        → 可选：admin 跨用户列表
```

### 4.4 验收（T0）

- 用户 A、B 各建 provider，列表互不可见；resolved 模型不串。
- 共享专家：文档写明用所有者 providers（推荐）——实现与文档一致。
- 旧单用户实例迁移后服务可启动、原 provider 仍可用。

### 4.5 风险（T0）

| 风险 | 缓解 |
|------|------|
| 多用户历史数据无法推断 owner | 迁移要求显式 `PRIMARY_OWNER_USER_ID`；拒绝盲目猜 |
| admin-only 写 → 用户可写 | 权限模型与现有 agent 创建对齐；审计日志 |
| harness 同步缓存串用户 | `sync_providers_to_harness` 按 user 分区或按请求重建 |

---

## 5. T1 详细：ACP 预置扩展

### 5.1 Problem（摘要）

Dashboard ACP 页缺少 Hermes / OpenClaw / Grok Build。现状 builtins：

| 层 | 位置 | 现有 id |
|----|------|---------|
| harness | `octop_harness.acp.models._BUILTIN_RUNNERS` | `opencode` / `codebuddy` / `qwen_code`(隐藏) / `claude_code` / `codex` |
| Octop 补丁 | `_OCTOP_BUILTIN_RUNNERS` | `kimi_code` / `cursor_cli` / `pi` |
| API 白名单 | `acp.py` frozenset | 同上（无 qwen_code） |
| Dashboard | `constants.ts` | `BUILTIN_RUNNER_ORDER` |

合并逻辑（已有，保持）：

```python
# src/octop/infra/agents/settings/acp.py
def _runners_response(raw_runners: dict[str, Any]) -> dict[str, Any]:
    merged_raw = dict(raw_runners)
    harness_names = set(default_acp_runners())
    for name, spec in _OCTOP_BUILTIN_RUNNERS.items():
        if name not in harness_names and name not in merged_raw:
            merged_raw[name] = spec
    ...
```

### 5.2 Decisions（沿用并闭合）

| ID | 决策 | State |
|----|------|-------|
| DEC-001 | 新 runner **仅进** `_OCTOP_BUILTIN_RUNNERS`（同 kimi/cursor/pi）；同步 API + Dashboard + docs；不强制本轮 bump harness | **accepted-for-GPT** |
| DEC-002 | **禁止** Grok Bot；要 **Grok Build**（id=`grok_build`） | **accepted-for-GPT** |
| DEC-003 | P0=`hermes`+`grok_build`；P1=`openclaw`；可同 PR 末切片 | **accepted-for-GPT** |
| DEC-004 | Hermes：`command=hermes` `args=["acp"]` `trusted=True` `tool_parse_mode=update_detail` | **accepted-for-GPT** |
| DEC-005 | Grok Build：`command=grok` `args=["agent","stdio"]`；**默认不加** `--always-approve` | **accepted-for-GPT**（OQ-001 关闭：否） |
| DEC-006 | OpenClaw：`command=openclaw` `args=["acp"]`；token 走 env / `--token-file`；**禁止**默认 args 含 token | **accepted-for-GPT** |
| DEC-007 | 图标：无官方资产则 `custom-provider.svg` | **accepted-for-GPT** |
| DEC-008 | FU-001 非本切片硬门槛；见 T2 | **accepted-for-GPT** |

**OQ 关闭：** OQ-001=否；OQ-002=P0 占位图；OQ-003=同 PR 末切片或分 PR 均可；OQ-004=id 用 `hermes`/`grok_build`/`openclaw`。

### 5.3 精确文件路径 + 伪代码

| # | 路径 | 改什么 |
|---|------|--------|
| 1 | `src/octop/infra/agents/settings/acp.py` | 追加三 dict |
| 2 | `src/octop/api/routers/acp.py` | frozenset 加三 id |
| 3 | `dashboard/src/pages/Agent/ACP/constants.ts` | ORDER + icons + keys |
| 4 | `dashboard/src/locales/zh.json` / `en.json` | 文案 |
| 5 | `dashboard/src/assets/acp/`（可选） | 专用图标 |
| 6 | `docs/acp.md` | 表 + 排查 |
| 7 | `tests/`（若有 ACP settings 测） | 合并/删除 403 |

**仿写样例（照抄进 `_OCTOP_BUILTIN_RUNNERS`）：**

```python
"hermes": {
    "command": "hermes",
    "args": ["acp"],
    "trusted": True,
    "tool_parse_mode": "update_detail",
},
"grok_build": {
    "command": "grok",
    "args": ["agent", "stdio"],
    "trusted": True,
    "tool_parse_mode": "update_detail",
    # 禁止默认加入 "--always-approve"
},
"openclaw": {
    "command": "openclaw",
    "args": ["acp"],
    "trusted": True,
    "tool_parse_mode": "update_detail",
    # 禁止: args 含 "--token", "<secret>"
    # 用户可在卡片 env 填 OPENCLAW_GATEWAY_TOKEN（仅本地 hub spawn 生效）
    # 远程设备：在设备 OS env 或使用 args "--token-file", "C:\\path\\token"（设备本地路径）
},
```

**API frozenset：**

```python
_BUILTIN_RUNNERS = frozenset(
    {
        "opencode", "codebuddy", "claude_code", "codex",
        "kimi_code", "cursor_cli", "pi",
        "hermes", "grok_build", "openclaw",
    }
)
```

**constants.ts 顺序：**

```ts
export const BUILTIN_RUNNER_ORDER = [
  "opencode", "codebuddy", "claude_code", "codex",
  "kimi_code", "cursor_cli", "pi",
  "hermes", "grok_build", "openclaw",
] as const;
```

### 5.4 Runner 目标态

#### 已有（保留）

| ID | command | args | 来源 |
|----|---------|------|------|
| opencode | opencode | `acp` | harness |
| codebuddy | codebuddy | `--acp` | harness |
| claude_code | npx | `-y @zed-industries/claude-agent-acp` | harness |
| codex | npx | `-y @zed-industries/codex-acp` | harness |
| kimi_code | kimi | `acp` | Octop |
| cursor_cli | agent | `acp` | Octop |
| pi | npx | `-y pi-acp` | Octop |

#### 新增

| 优先级 | ID | command | args | env 约定 | 前提 | 备注 |
|--------|-----|---------|------|----------|------|------|
| **P0** | `hermes` | `hermes` | `["acp"]` | 无（Hermes 自管 `~/.hermes`） | PATH 有 `hermes`；建议 `hermes acp --check` | 本地 coding agent |
| **P0** | `grok_build` | `grok` | `["agent","stdio"]` | 可选 `XAI_API_KEY` | 安装 Grok Build CLI；已登录或 API key | **不是** Grok Bot |
| **P1** | `openclaw` | `openclaw` | `["acp"]` | `OPENCLAW_GATEWAY_TOKEN`（本地）；远程用设备侧 env/`--token-file` | **Gateway 已运行** | 本质=session 转发器 |

`qwen_code` 仍在 `_HIDDEN_RUNNERS`。

### 5.5 验收清单（T1）

| ID | 验收项 |
|----|--------|
| AC-001 | 无用户 / 空 settings 时 `GET /api/acp` 含 `hermes`/`grok_build`/`openclaw`，`enabled=false`，command/args 符合上表 |
| AC-002 | 用户已保存同名自定义覆盖时，**不**被默认 spec 盖掉（`name not in merged_raw` 才注入） |
| AC-003 | `DELETE /api/acp/hermes`（等）→ 403；删除用户自定义 → 成功 |
| AC-004 | `/acp` 出现新卡片；可开关；可改 command/args/env；内置不可删 |
| AC-005 | OpenClaw intro（中英）写明 Gateway、token 用 env/`--token-file`、远程不传 hub env、禁止 token 写 args |
| AC-006 | `docs/acp.md` 与 Dashboard 一致；Related **不**列 Grok Bot |
| AC-007 | PATH：装好 CLI 后启用 + agent `acp_runner` `action=start` 能建 session；未装 → 明确失败，非 Unknown runner |
| AC-008 | Hermes：文档/hint 指向 `hermes acp --check` |
| AC-009 | 权限流：默认无 `--always-approve` 时外部 permission 可走 chat `action=respond`（对照 opencode） |
| AC-010 | 自定义 runner CRUD 不受影响 |
| AC-011 | OpenClaw token **不进 process list**：默认 args 无 `--token`；review 拒绝把 secret 写进默认 args；本地 env 注入即可 |
| AC-012 | diff **不出现** Grok Bot 作为 ACP runner |
| AC-013 | 本切片 **不以**「必须改 provider_template」为合并门槛 |

### 5.6 风险（T1）

| 风险 | 缓解 |
|------|------|
| Grok Build CLI 子命令漂移 | 文档钉死 `grok agent stdio`；可配置 args |
| OpenClaw 被误当成本地全功能 agent | intro/docs 强调「Gateway 转发」 |
| harness 随后 ship 同名 → 双份默认 | merge：`harness_names` 优先；届时删 Octop 补丁 |
| 远程 OpenClaw 配了 hub env 却不生效 | docs + intro 写清 §2.3；可选 FU-003 做设备侧引导 |
| 误加 Grok Bot | AC-012 + review 门禁 |

### 5.7 其他主流 agent 扩展点（清单位，本轮不做）

| 候选 | 备注 |
|------|------|
| Aider / Continue / Goose / Zed agent | 待各家稳定 `acp` stdio 入口后再评估 |
| 厂商专有 ACP bridge | 同一扩展点：只加 `_OCTOP_BUILTIN_RUNNERS` + constants + i18n + docs |
| Grok Bot | **永久排除**出 ACP 预置卡片 |

---

## 6. T2 详细：FU-001 模型预置刷新

### 6.1 范围

| 项 | 说明 |
|----|------|
| 真相源 | **octop-harness** 包内 `providers/provider_template.json` |
| 本仓引用 | `octop.infra.agents.providers.presets.load_provider_presets`；依赖 `octop-harness[all]>=1.0.1`（lock **1.0.1**） |
| 现状抽样（venv 副本） | 有 openai/anthropic/gemini/openrouter 等约 40 个渠道；**无独立 xAI**；openai 已有 gpt-5.2 等；anthropic 仍含 `claude-3-5-*` 旧 id |
| Octop 职责 | **只 bump 版本**；禁止把 JSON 拷进业务仓 |

### 6.2 改 harness 的步骤

```text
1. 检出 octop-harness 源码仓（本工作区无 sibling；不要改 .venv 或 portable release 内副本当真相源）。
2. 编辑 providers/provider_template.json：
   a. 新增 xai 条目（见下样例）。
   b. 更新 openai / anthropic / openrouter / gemini：删过时、补稳定主力。
   c. 中国区稳定渠道（deepseek/kimi/dashscope 等）只做必要修正，优先「能连通的稳定 id」。
3. harness 单测 / 模板校验（若有）跑通。
4. 发版 bump harness version（如 1.0.2）。
5. 回 Octop：pyproject.toml 提高 octop-harness 下界；uv lock 刷新。
6. 本地 uv sync 后打开 Dashboard → 设置 → 模型/预设：确认 xAI 与新模型可见。
```

### 6.3 xAI 条目伪代码（写入 harness JSON）

```json
{
  "id": "xai",
  "name": "xAI",
  "base_url": "https://api.x.ai/v1",
  "protocol": "openai",
  "api_key_env": "XAI_API_KEY",
  "api_key_prefix": "xai-",
  "logo": "xai.png",
  "models": [
    { "id": "grok-4.7", "name": "Grok 4.7", "max_input_tokens": 256000, "input": ["text", "image"] },
    { "id": "grok-4.6", "name": "Grok 4.6", "max_input_tokens": 256000, "input": ["text", "image"] },
    { "id": "grok-4.5", "name": "Grok 4.5", "max_input_tokens": 256000, "input": ["text", "image"] }
  ]
}
```

> 发版前用官网/API 核对 model id 与 context；logo 文件放 harness 静态资源目录（对照现有 `openai.png` 布局）。若 prefix 与实发 key 不符，以实测为准改 `api_key_prefix`。

### 6.4 本仓 bump 路径

| # | 路径 | 动作 |
|---|------|------|
| 1 | `pyproject.toml` | `"octop-harness[all]>=1.0.1"` → 新版本下界 |
| 2 | `uv.lock` | `uv lock` / `uv sync` |
| 3 | （勿改）`.venv/.../provider_template.json` | 安装结果，非源 |
| 4 | （勿改）`desktop/portable/release*/**/provider_template.json` | 打包产物 |

### 6.5 验收（T2）

- 预设列表出现 **xAI** 与 grok-4.7/4.6/4.5。
- 过时 anthropic/openai id 已移除或降级标注（按 harness 惯例）。
- Octop 仓 **无**新增第二份 template JSON。
- 与 ACP runner 列表无关；**不**把 Grok Bot 做成 Provider 产品卡片以外的 ACP 项。

### 6.6 风险（T2）

| 风险 | 缓解 |
|------|------|
| 模型 id 官网变更 | 发版当日核对；changelog 注明 |
| 只改 venv 未改 harness 源 | Code review：diff 必须在 harness 仓 |
| bump 后 portable 旧包仍旧模板 | Release 流水线重打；文档注明 |

### 6.7 相关可选 follow-up（非本必做）

- **FU-002**：ACP runner 上游进 harness `_BUILTIN_RUNNERS` 后删 Octop 补丁。
- **FU-003**：OpenClaw 卡片专用 Gateway URL/token 表单项（写入 env/`--token-file`，永不进默认 argv 明文）。

---

## 7. 切片建议（给 GPT 的 PR 切分）

| PR | 内容 | 依赖 |
|----|------|------|
| PR-A | T1.1–T1.7 ACP 预置（可先 P0，再 commit P1） | 无 |
| PR-B | T2 harness 发版 + Octop bump | harness 仓权限 |
| PR-C | T0 providers 按用户隔离 | 迁移窗口；可后置 |

推荐顺序：**PR-A → PR-B → PR-C**（额度紧时只做 PR-A，并开 issue 链本 spec T0/T2）。

---

## Evolution

| Revision | 变更 |
|----------|------|
| `2026-10-12.1` | 初稿：P0 Hermes + Grok Build；P1 OpenClaw；排除 Grok Bot；可选 harness/LLM follow-up 占位 |
| `2026-10-12.2` | 架构补强：用户确认预置模型很旧；扩写 Optional follow-up（bump/改 octop-harness `provider_template.json`；独立 xAI grok-4.7/4.6/4.5；刷新 OpenAI/Anthropic/OpenRouter；**本仓只 bump 依赖**）；Settings「设备 vs 全局」点到为止仍 Draft |
| `2026-10-12.3` | **Ready-for-GPT**：并入配置归属铁律（账号/设备/半全局 + 远程不传 env）；providers 整站一份缺口的 schema/API 步骤；可勾选 T0/T1/T2；精确路径 + 伪代码 + 验收 + 风险；不派 Coder |

## Out of scope reminder

- 架构师本回合 **只改 docs**，**不**改业务代码、**不** git commit。
- 实现由 GPT（或日后 Coder）按本 Ready-for-GPT 执行；合并前对照 §2 铁律与 §3 勾选。
- **勿修改** Accepted `0004`。
