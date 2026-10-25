# 0038 多用户隔离修复（账号 / 执行端 / 管理服务器）

- Revision: **2026-10-25.1**（Asia/Shanghai）｜Contract: **Ready**
- Owner: Octopus 架构师 → 总管派 Coder｜权威源：本文件
- Decision basis: 用户王俊浩经总管派单「修复多用户隔离」；交接包 `octopus-multiuser-handoff-2026-10-25`；产品三边界不可破
- Code baseline: `CkEFFAF/Octopus-public` **`origin/main` @ `34dd50e6c91fa31d2b5b7607d237b170348951af`**（`34dd50e Merge pull request #57`）
- 审查基准（交接报告行号）：`55e0dbf45e1837614ad94b111692a82a29d29957`；本规格已在 tip `34dd50e6` 干净 worktree 逐项核对
- Delivery: compact SDD（build-adaptively）｜Verification: **strict**（权限/会话/跨账号）｜Continuity: collaborative
- 编号说明：tip 上最高正式号为 `0037-ui-feedback-and-draft-protection`；用户机另有 `0036`/`0036.1`；本规格取 **0038**
- 约束：**只写 docs/specs**；不写生产实现、不 commit、不 push、不部署、不派 Coder；不做新漏洞探索或攻击演示

---

## 1. Goal / Non-goals / 产品边界

### Goal

管理员发邀请 → 新用户注册普通账号 → 安装执行端并绑定自有设备 → 各自独立构建设备网。  
**普通用户不得获得管理服务器 OS、其他账号数据/设备/凭据的访问权。**  
本规格把交接报告 F01–F09 + 上一轮管理权限补丁，落成可执行的领域层修复契约与分批切片。

### 不可破产品边界（DEC 前提）

1. **账号身份与数据**、**用户执行端设备**、**管理服务器本地** —— 三者必须区分。
2. 普通用户：邀请注册 → 自己的设备网；不能访问管理服务器或其他账号数据/设备/凭据。
3. 管理服务器本地执行 = **明确 local 目标** **且** 当前身份为**可用管理员**（DB 现态，非仅 JWT role 快照）。
4. **禁止**只隐藏按钮、删字段或命令黑名单；权限规则进 **infra 领域层**，路由保持薄。
5. 未经用户明确要求：不推送、不部署、不覆盖他人未提交工作。

### In scope

- Batch1 P1：F01–F05（MCP stdio / 代理 backend / 目录 API / 语音密钥 / 存储 config_json）
- Batch2 P2：F06–F07（JWT 会话撤销 / 停用后桌面 WS）
- Batch3：F08 Mermaid；F09 依赖（先权限后依赖）；整合 `octopus-multiuser-55e0dbf4.patch` 管理权限
- Batch4：双账号/双执行端验收（报告 §14 AC01–AC14 + 本规格 AC）
- SQLite **与** PostgreSQL 迁移；历史危险配置处理；与 0025/0028/0001/0005 关系

### Non-goals

- 不新开漏洞扫描、不写攻击 PoC、不扩展探针攻击面
- 不把「容器部署」当成账号隔离
- 不重做 0025 设备能力包 / 0028 OS jail（协同引用，本规格管**跨账号与控制中心边界**）
- 不把公开分享页接上通用 Mermaid 渲染器
- 本规格交付阶段不部署云端

---

## 2. 现状核对表（对 tip `34dd50e6`）

核对方法：干净 worktree `/workspace/octopus-0038-multiuser` @ `34dd50e6`；对照交接报告路径与补丁文件清单。  
图例：**仍需修** = tip 上仍可复现报告语义；**已修** = tip 已有等价防护；**不适用** = 产品已废弃该路径。

| 编号 | tip 状态 | 证据（文件 / 符号 / 行为） | 说明 |
| --- | --- | --- | --- |
| **F01** MCP stdio 服务器进程 | **仍需修** | `api/routers/connectors.py` `test_custom_mcp`（~L586）仅 `current_user`；`infra/connectors/probe.py` `_probe_stdio_mcp`（~L569）直接 `stdio_client` 在管理服务器起进程 | 保存/重载路径须同规则；不能把握手失败当安全 |
| **F02** 代理 backend / 绝对路径 | **仍需修** | `validators.assert_user_backend_root_dirs`：无 `workspace_root_dir` 时仅 `assert_backend_root_dirs_allowed(..., restrict_to_home=False)`；`resource_policy.assert_backend_within_user_root` 在 `allowed_root` 为空时同样宽松；`workspace.py` 仍允许主机绝对路径语义 | 可选 policy ≠ 默认强制隔离 |
| **F03** 目录 API | **仍需修** | `api/routers/filesystem.py`：`/dirs` `/mkdir` `/rename` `/probe` `/ensure-docker` `/ensure-bwrap` 均为 `current_user`；无 workspace_root 时 `filesystem_roots` 返回宿主浏览根 | 非管理员可列/改控制中心目录 |
| **F04** 语音密钥回显 | **仍需修** | `api/routers/voice.py` `_row_to_dict` 含 `"api_key": r.api_key` 与 `"extra": r.get_extra()`；`GET /providers` 复用该序列化 | 普通列表泄露全局凭据 |
| **F05** 存储 config_json | **仍需修** | `api/routers/storage_backends.py` `_row_to_dict` 返回完整 `config_json`；`list_storage_backends_for_user`（~L367）同样调用；仅 `access_key` 掩码 | 嵌套 `api_key` 等仍回显 |
| **F06** JWT 不撤销 | **仍需修** | `auth.py` `logout`（~L325）注释写明 JWT 不服务端撤销；`change_password` / `reset_password` 不 bump 版本；`tokens.sign_token` 无 `sid`/`auth_version`；无 `browser_sessions` 表；迁移最高 `033_*` | 退出/改密/重置/停用再启后旧 JWT 仍可用 |
| **F07** 停用后桌面 WS | **仍需修** | `middleware/key_sessions.py`：`key_id is None` 时 `valid()` 直接 `True`；`desktop/stream.py` 仅 start 时 `resolve_user_from_token`，输入循环不再查账号状态 | HTTP 拒、旧 WS 仍可派发输入 |
| **F08** Mermaid loose | **仍需修** | `dashboard/.../Markdown/mermaidLoader.ts` `securityLevel: "loose"`；`index.tsx` 将 SVG 插入 DOM | 脚本协议链接可点执行；公开分享 `PublicMarkdown` 独立且无 Mermaid——**保持隔离** |
| **F09** 依赖公告 | **仍需修（延后）** | lock：`mermaid` `^11.13.0`（解析常为 11.15.0 一带）、`xlsx` `^0.18.5`；交接依赖审计摘要仍适用 | **先 F01–F08/管理补丁，再筛可达性升级**；升级 Mermaid ≠ 自动修 F08 |
| **管理补丁** `55e0dbf4.patch` | **仍需修（未合入）** | tip **无** `infra/users/administration.py`；**无** `tests/integration/test_multiuser_administration.py`；补丁 SHA-256 `bb0a9191…68788ba` 相对 `55e0dbf4`，须 rebase 到 `34dd50e6` 后择取 | 保留合法管理员与委派；禁止整文件覆盖 |

**与 `55e0dbf4`→`34dd50e6` 区间**：`git log` 无隔离/会话撤销/密钥脱敏相关合入；tip 前进主要为 UI hotfix（#57 等）。**结论：F01–F09 + 管理补丁在 tip 上全部仍需处理。**

---

## 3. DEC（拍板）

| ID | 决议 | 状态 |
| --- | --- | --- |
| **DEC-0038-01** | 三边界强制：账号数据 ≠ 用户设备 ≠ 管理服务器；模块权限（terminal/desktop/connectors）**≠** 管理服务器管理员 | resolved |
| **DEC-0038-02** | 身份只来自服务端认证上下文；**禁止**信任请求体 `owner_user_id`；空 `device_id` **不得**回退为控制中心 | resolved |
| **DEC-0038-03** | 管理服务器本地执行须 **明确 local** + **DB 现态可用管理员**；CLI 可信本地路径与外部 HTTP 身份分离，禁止兼容旁路 | resolved |
| **DEC-0038-04** | 权限/生命周期规则落 **infra 领域**；路由只适配；同一规则覆盖 HTTP、WS、聊天工具、重载、后台任务 | resolved |
| **DEC-0038-05** | F01：普通账号 **stdio MCP 不得在管理服务器运行**；S0 直接拒绝该组合；若未来支持则必须走用户执行端/账号隔离环境，禁止静默回退控制中心 | resolved |
| **DEC-0038-06** | F02：普通用户 backend **由服务器按账号生成**；禁止任意指定控制中心 `root_dir`/composite/宿主机挂载；解析层（运行中+停止后备）一致校验 | resolved |
| **DEC-0038-07** | F03：控制中心 dirs/mkdir/rename/probe 写路径与 ensure-docker/bwrap → **管理员**；普通用户目录选择走**已授权设备** API；前端按目标类型切换选择器，403 不引导加管理员 | resolved |
| **DEC-0038-08** | F04/F05：公开响应与秘密配置分离；公开模型白名单字段；`has_api_key`/掩码可给管理端；嵌套 JSON 密钥同等处理；PATCH「未提供＝保留 / 显式空＝删除 / 新值＝替换」 | resolved |
| **DEC-0038-09** | F06：采用 **持久浏览器会话（sid）+ 账号 `auth_version`**；logout 撤 sid；改密/重置/停用 bump `auth_version` 并收回相关会话；多 worker 可见；**仅缩短 TTL 或单进程内存黑名单不合格** | resolved |
| **DEC-0038-10** | F07：复用 F06 校验；控制消息前 + 空闲周期复查；停用/撤权/退出主动关流；关闭原因明确，前端停自动重连 | resolved |
| **DEC-0038-11** | F08：不可信 Markdown（聊天/文档/知识库预览）Mermaid → **strict**（或真沙箱）；SVG 独立清理（href + xlink:href、事件、脚本协议）；**禁止**把通用 Mermaid 接进 `PublicMarkdown` | resolved |
| **DEC-0038-12** | F09：权限修复优先；依赖按可达性升级；Mermaid ≥ 公告修复线（如 11.16.1+）且仍须 DEC-0038-11；xlsx 按 SheetJS 官方修复发行版，不假改 semver | resolved |
| **DEC-0038-13** | 管理补丁：rebase 后整合；委派上界写前校验；邀请审计记 ID 不记原始码；禁止停用自己 | resolved |
| **DEC-0038-14** | **邀请角色默认**（可安全默认）：未指定角色的邀请 → 普通用户（无模块管理权限）。**尚未兑换邀请 vs 模板变更** → 见 OQ-0038-1；S0 实现须保证**任何策略不绕过授予上界** | resolved default + OQ |
| **DEC-0038-15** | 历史危险配置：**不**静默删除用户目录/文件；阻止启动并明确错误；保留行并标记需重绑；管理员合法本地配置显式授权保留 | resolved |
| **DEC-0038-16** | 迁移号建议 **034**（tip 最高 033）：`users.auth_version` + `browser_sessions`（或等价）；**SQLite + PostgreSQL 双文件**必须同时交 | resolved |
| **DEC-0038-17** | 设备 access-key / 原生设备凭据与浏览器会话**分轨**生命周期；账号停用阻断全部能力；重新启用**不**自动复活已撤销浏览器会话 | resolved |

---

## 4. 与既有规格关系

| 规格 | 关系 |
| --- | --- |
| **0001** 账号设备网 / **0004** 自动入网 / **0005** 设备权限 | 本规格强化「跨账号不可见、空目标不落控制中心」；不改设备 grant 表语义 |
| **0022** 专家存储边界 / **0028** 执行隔离 | 0028 管专家 FS/OS/egress 与 team-host 无 MCP；本规格管**多账号 vs 控制中心**。协同：host 上的 stdio/MCP 仍受本规格 F01 + 0028 DEC-I03 |
| **0025** MCP/Skill 作用域 | 设备包/resolve union **不**授权控制中心进程；`shared` 仍≠凭据授权（与 DEC-C11 一致） |
| **0019** 执行目标默认 | 解析链保留；本规格禁止「无 device → local 控制中心」对普通用户 |
| 交接 `multiuser-beta-readiness.md`（补丁内） | 管理授权上界并入 Batch3；会话撤销由本规格 F06/F07 承接 |

冲突处理：若实现与 0025/0028 测试冲突，**不得**削弱 team-host 无 MCP 或设备包 resolve-time 语义来「方便」F01。

---

## 5. Requirements & Acceptance

### REQ-M01 — F01 MCP 执行位置授权
- 领域函数（建议 `infra/connectors/execution_auth.py` 或并入既有 connectors 领域）：输入 = 操作者、transport、拟运行位置、ExecutionContext；输出 = allow/deny + ErrorCode。
- 普通用户 + stdio + 管理服务器 → **deny（进程创建之前）**。
- 覆盖：test、save、enable、聊天装载、代理重载、恢复历史配置。
- AC-M01：无/有 connectors 权限的普通账号，stdio test **均不**创建宿主进程（探针 `test_ordinary_user_cannot_spawn_control_server_process_via_mcp` 语义）。
- AC-M02：已存危险配置重载/聊天工具不得绕过；返回明确需调整错误，配置行保留。
- AC-M03：管理员明确本地 MCP、普通用户设备端 MCP（若产品已有路径）保持可用。
- **禁止**：命令名/扩展名黑名单作为唯一手段。

### REQ-M02 — F02 Backend / 工作区隔离
- 普通用户创建/更新代理：拒绝任意控制中心 `root_dir`；默认与继承/克隆/导入/恢复不得落到服务器根。
- 统一解析：`workspace_for_agent` / `_backend_workspace_for_row` / `backend/resolver` 与权限一致；运行中与停止后备一致。
- 路径：真实 resolve、symlink、盘符/UNC、`file://`、混合分隔符；禁止仅 `startswith`。
- AC-M04：A 不能经自建代理/绝对路径/停止代理读 B 或控制中心标记文件（探针两条 workspace 语义）。
- AC-M05：A 在账号内容存储与自有设备合法路径仍可用；危险请求无部分副作用。

### REQ-M03 — F03 目录与组件 API
- 控制中心 dirs/mkdir/rename/写 probe / ensure-docker / ensure-bwrap → 管理员（`require_admin` 或等价 DB 现态检查）。
- 只读 docker-status 可最小化信息（产品可保留登录可见）。
- AC-M06：普通账号 dirs/mkdir/rename → 403，无副作用（探针 `test_ordinary_user_cannot_manage_host_directories`）。
- AC-M07：管理员管理服务器目录、普通用户经设备目录选择器两条正向路径可用。

### REQ-M04 — F04/F05 秘密分离
- 语音公开列表：无 raw `api_key`、不透传危险 `extra`；可选 `has_api_key`。
- 存储公开列表：不回完整 `config_json`；按 kind 白名单公开字段；嵌套密钥同等剥离。
- 管理 PATCH 三态：未提供保留 / 显式清空删除 / 新值替换；掩码不得写回。
- AC-M08：普通 `GET /api/voice/providers` 响应文本不含合成密钥（探针 voice）。
- AC-M09：普通存储列表不含 `config_json` 内合成密钥（探针 storage）。
- AC-M10：管理员改非秘密字段后旧密钥仍有效；语音/存储代调用仍可用。

### REQ-M05 — F06 持久会话 + auth_version
- `users.auth_version`（INTEGER NOT NULL DEFAULT 1）。
- 表 `browser_sessions`（名可变）：`sid`（不可猜）、`user_id`、`created_at`、`absolute_expires_at`、`revoked_at`、`auth_version_at_issue`。
- JWT 含 `sid` + `av`（auth_version）；认证：验签/exp + 会话未撤 + 用户可用 + `av` 匹配。
- logout → 撤当前 sid；改密/重置/停用 → bump `av` + 收回约定会话（建议该用户全部浏览器会话）。
- 续签复查同一持久会话与绝对寿命。
- 升级后缺新字段的旧 JWT：**要求重新登录**（推荐，无无限兼容窗）。
- AC-M11：logout / change-password / admin reset / disable-enable 后旧 JWT 访问 `/api/auth/me` ∈ {401,403}（探针 parametrize）。
- AC-M12：重启与跨 worker 后撤销仍有效；UserManager 缓存不得长期返回旧 disabled/role/av。

### REQ-M06 — F07 长连接跟随生命周期
- 普通 JWT 与 access-key 均持续检查（语义分轨，见 DEC-0038-17）。
- 桌面（及同构终端/浏览器/移动端路径审阅）：输入前 + 空闲周期检查；撤权主动关流。
- AC-M13：停用后既有桌面连接 **不再**调用输入处理（探针 `test_existing_desktop_socket_stops_after_user_disable`）。
- AC-M14：有权用户正常远控自有目标；闲置过期连接关闭；前端收到关闭原因后不盲重连。

### REQ-M07 — F08 安全图表渲染
- 通用 Markdown：`securityLevel: "strict"`（或真 iframe sandbox）。
- 最终 SVG 清理：禁脚本协议、事件属性；处理 `href` 与 `xlink:href`。
- AC-M15：普通流程图/时序图可读；脚本协议点击不执行页面脚本。
- AC-M16：`PublicMarkdown` 仍无 Mermaid、无 raw HTML；**不**为复用引入通用加载器。

### REQ-M08 — F09 依赖（Batch3 后半）
- 先完成 REQ-M01–M07 与管理补丁。
- 维护「影响/不影响/待确认」简表；xlsx / mermaid 按官方公告升级；Python 重点 Pillow/pypdf/mcp/aiohttp/urllib3/PyJWT/langgraph-checkpoint。
- AC-M17：锁文件经正常包管理器更新；有简表与依据；不把未运行的审计写成已利用漏洞数。

### REQ-M09 — 管理权限补丁整合
- 行为对齐补丁内 `docs/octopus/multiuser-beta-readiness.md`：委派上界、角色写前校验、邀请范围、审计遮码、禁停用自己。
- AC-M18：补丁验收表场景在 tip 上全绿（`tests/integration/test_multiuser_administration.py` rebase 后）。
- AC-M19：合法管理员全局管理与委派管理范围内账号仍可用。

### REQ-M10 — Batch4 双账号准入（报告 §14）
- AC-M20…AC-M33 一一映射交接报告 **AC01–AC14**（邀请、绑设备、跨账号设备、服务器执行、文件、凭据、委派、会话、长连接、图表、数据后台、配额、升级兼容、管理员正向路径）。  
  实现方交付时按报告编号勾选并附证据路径；本规格不重复展开全文以免双源漂移——**以报告 §14 原文 + 上列 REQ AC 为并集**。

---

## 6. 迁移与历史配置

### 6.1 Schema（建议 migration **034**）

**SQLite + PostgreSQL 必须成对：**

```text
034_browser_sessions_auth_version.sql
034_browser_sessions_auth_version.pg.sql
```

- `ALTER TABLE users ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 1;`（PG 同语义）
- `CREATE TABLE browser_sessions ( ... )` + 索引 `(user_id)`、`(sid)` UNIQUE
- 回滚说明写入迁移头注释；`migrate.py` 双后端路径回归

### 6.2 历史危险配置（F01/F02）

1. 升级时或首次加载时枚举：普通用户代理的本地 backend / composite；普通用户自定义 stdio MCP。
2. 生成迁移清单（日志/管理可读，**不**自动删文件）。
3. 安全账号内配置可规范化路径；指向控制中心/他账号 → **拒绝启动** + 明确错误（需重绑设备或改配置）。
4. 管理员确需的服务器工作区：显式管理授权路径保留。

### 6.3 旧 JWT

- 推荐：升级后旧无 sid/av 的浏览器 JWT 一律重新登录。
- 若产品坚持兼容窗：必须写明截止时间与撤销语义；**默认不采用无限兼容**（本规格 S0 = 强制重登）。

---

## 7. 分批切片（给 Coder）

**分支建议：** `feature/0038-multiuser-isolation`  
**基线：** `origin/main` @ `34dd50e6`（或更新 tip；冲突以本规格为准）  
**顺序：** Batch0 核对（本规格已完成）→ **1 → 2 → 3 → 4**；可分 PR，但不得在仍有服务器执行旁路时宣称「多用户安全完成」。

### Batch1 — F01–F05（P1 阻断）

| 切片 | 可写路径（建议） | 接口/契约要点 | 禁止 |
| --- | --- | --- | --- |
| B1a F01 | `infra/connectors/` 新领域授权；`probe.py` 调用点；`api/routers/connectors.py` 薄适配；重载/装载调用点 | deny 在 `stdio_client` 之前；ErrorCode 复用 FORBIDDEN/既有 | 命令黑名单当主修复；只修 test 不修 save/reload |
| B1b F02 | `resource_policy.py`、`validators.py`、`agents/manager.py`、`backend/resolver.py`、`api/routers/agents.py`、`workspace.py` | 无 policy 时普通用户也不得选控制中心根；默认 backend 生成 | 只靠可选 workspace_root；绕开 BackendWorkspace 直接 Path |
| B1c F03 | `api/routers/filesystem.py`；前端目录选择器按 target 切换 | 管理 API → admin；设备目录另路由 | 403 后引导加管理员角色 |
| B1d F04/F05 | `voice.py`、`storage_backends.py`；公开 DTO；必要时 infra 序列化助手 | 公开/管理两套模型；PATCH 三态 | 只掩码顶层 `secret_key`；掩码写回 |

**Batch1 完成条件：** AC-M01–M10；普通账号不能起服务器进程、越文件、拿全局密钥；合法设备/管理正向路径冒烟。

### Batch2 — F06–F07

| 切片 | 可写路径 | 要点 | 禁止 |
| --- | --- | --- | --- |
| B2a F06 | `migrations/034_*`；`infra/auth/tokens.py`；新 `infra/auth/sessions.py`（名可变）；`users/manager.py`；`api/routers/auth.py`；`api/deps.py` | sid+av；原子 bump；多实例 | 仅 TTL；仅内存黑名单 |
| B2b F07 | `middleware/key_sessions.py`；`desktop/stream.py`；同类 WS 入口审阅清单写入 PR | 输入前检查；主动 disconnect | 只改桌面忽略其它长连接审阅记录 |

**完成条件：** AC-M11–M14。

### Batch3 — F08 + 管理补丁 + F09

| 切片 | 可写路径 | 要点 | 禁止 |
| --- | --- | --- | --- |
| B3a F08 | `dashboard/.../Markdown/mermaidLoader.ts`、`index.tsx`；SVG sanitizer 单测 | strict + SVG 清理 | 改 `PublicMarkdown` 引入 Mermaid |
| B3b 管理补丁 | 补丁 10 文件 rebase：`administration.py` 新文件、`users/invites/user_roles/admin` 路由、`offline_ops.py`、集成测 | 写前上界；邀请过滤；审计遮码 | `git apply` 盲目覆盖 tip |
| B3c F09 | lock/声明文件；依赖简表 `docs/` 或 PR 说明 | 先权限后依赖 | 手工改 lock 版本号充数 |

**完成条件：** AC-M15–M19 + 依赖简表。

### Batch4 — 双账号验收

- 按报告 AC01–AC14 + AC-M20… 跑真实双账号/双执行端（可用临时账号）。
- 交付：改动文件表、迁移说明、实际命令与结果、未完成项；区分「代码已修 / 检查通过 / 已合入 / 已部署」。

---

## 8. 测试与探针回归（禁止扩展攻击）

### 8.1 既有探针（仅回归）

来源：`octopus-multiuser-handoff/.../evidence/test_security_audit_probes.py`  
**用法：** 修复后迁入 `tests/integration/`（或项目约定安全回归目录），**只跑既有断言语义**；允许因 API 形状变化改调用方式，但**不得**新增攻击场景、不得对生产实例探测。

| 探针函数 | 对应 |
| --- | --- |
| `test_old_session_is_invalidated_after_security_action` | F06 |
| `test_ordinary_user_cannot_manage_host_directories` | F03 |
| `test_voice_provider_list_does_not_return_secret_to_ordinary_user` | F04 |
| `test_storage_list_does_not_return_config_secret_to_ordinary_user` | F05 |
| `test_user_agent_cannot_read_control_server_file` | F02 |
| `test_user_agent_cannot_read_another_users_workspace` | F02 |
| `test_ordinary_user_cannot_spawn_control_server_process_via_mcp` | F01 |
| `test_existing_desktop_socket_stops_after_user_disable` | F07 |

### 8.2 工程门禁

- 默认：`make all`；Python：`uv run pytest`（非 live）；改前端：TypeScript + 相关组件/构建。
- 管理补丁历史参考：`5170 passed` 为 **55e0dbf4 工作区**结果，**不是** tip 验收。
- Mermaid：组件单测 + 必要时独立页面确认脚本协议不可点执行（无真实 XSS 利用链扩展）。

### 8.3 正向验收不可省

每批除「拒绝」外必须保留：管理员合法本地能力、普通用户自有设备网、语音/存储代调用、正常 Markdown 图表。

---

## 9. Coder 实现指南（交接摘要）

```text
规格: docs/specs/0038-multiuser-isolation.md（Rev 2026-10-25.1 Ready）
基线: origin/main @ 34dd50e6
分支: feature/0038-multiuser-isolation
顺序: Batch1(F01-F05) → Batch2(F06-F07) → Batch3(F08+管理补丁+F09) → Batch4(AC01-AC14)
领域优先: infra；路由薄；双迁移 034 sqlite+pg
探针: 只迁既有 test_security_audit_probes 语义；禁止扩攻击
补丁: previous-fixes/octopus-multiuser-55e0dbf4.patch rebase 后择取，勿覆盖 tip 无关改动
不要: 黑名单当主修复；只藏按钮；静默删用户文件；PublicMarkdown 接 Mermaid；部署云端
与 0025/0028: 协同，不削弱 team-host 无 MCP / 设备包 resolve
```

### 建议新/重点文件

| 区域 | 路径 |
| --- | --- |
| MCP 授权 | `src/octop/infra/connectors/execution_auth.py`（新）+ `probe.py` / 重载调用点 |
| Backend 隔离 | `infra/users/resource_policy.py`、`api/common/validators.py`、`infra/agents/manager.py`、`infra/backend/resolver.py` |
| 目录 | `api/routers/filesystem.py` + 前端设备目录选择器 |
| 秘密 DTO | `api/routers/voice.py`、`storage_backends.py` |
| 会话 | `infra/db/migrations/034_*`、`infra/auth/sessions.py`、`tokens.py`、`users/manager.py`、`api/routers/auth.py`、`deps.py` |
| WS | `api/middleware/key_sessions.py`、`api/routers/desktop/stream.py` |
| Mermaid | `dashboard/src/components/Markdown/*` |
| 管理 | 补丁文件集 + `tests/integration/test_multiuser_administration.py` |

---

## 10. 假设与未决（OQ）

| ID | 问题 | 安全默认（S0） | Owner | 阻塞 S0？ |
| --- | --- | --- | --- | --- |
| **OQ-0038-1** | 角色模板变更后，**尚未兑换**的邀请继承最新模板还是创建时权限快照？ | **S0：兑换时读当前模板**（与交接「角色模板在兑换时读取」一致）；但**授予上界**始终按创建者现态校验，越权邀请不可兑 | 产品 | 否（默认已定；若改快照另开变更） |
| **OQ-0038-2** | logout 是否撤销该用户**全部**浏览器会话，还是仅当前 sid？ | **S0：仅当前 sid**；改密/重置/停用 → **全部**浏览器会话 | 产品 | 否 |
| **OQ-0038-3** | 普通用户自定义 **HTTP** MCP 访问管理端内网是否默认拒绝？ | **S0：拒绝指向管理服务器环回/链路本地的非管理员请求**；完整 SSRF 策略可 S1 单独立项 | 安全/产品 | 否（最小默认） |
| **OQ-0038-4** | 停用后持久 Job/定时任务：取消 vs 挂起？ | **S0：控制权限立即收回**；可恢复任务语义保持产品现状，但**不得**在停用期间继续对外副作用 | 产品 | 否 |
| **OQ-0038-5** | F09 全量升级是否同 PR | **S0：可同 Batch3 后半或 follow-up PR**；不阻塞 F01–F08 合入 | 总管 | 否 |

---

## 11. 风险

| 风险 | 缓解 |
| --- | --- |
| 只脱敏响应、仍留服务器执行旁路 | Batch 完成门禁；总管验收按批 |
| 迁移只做 SQLite | AC 明确双后端；CI/本地各跑一种或 migrate 单测覆盖 |
| 补丁与 tip 冲突 | rebase 择取；以本规格行为表为准 |
| UserManager 缓存导致撤权延迟 | F06 要求缓存失效/短 TTL；测跨请求 |
| Mermaid strict 破坏图表 | 保留布局/安全链接的视觉回归 |
| 脏工作区被 reset | Coder 须干净 worktree；禁止 reset/clean 用户机未提交改动 |

---

## 12. Evolution

| Rev | 变更 |
| --- | --- |
| `2026-10-25.1` | 初版 Ready：F01–F09 tip 核对全「仍需修」；管理补丁未合入；compact SDD + 分批 + 探针回归约定 |

- Contract: **Ready** —— 第二实现者可按 Batch 开工；无阻塞 OQ
- Implementation / verification / release: planned / not run / **不部署**
