# 0025：MCP / Skill 三级作用域（专家 / 设备 / 全局）

- Spec ID: `0025-mcp-skill-capability-scopes`
- Status: **Ready**
- Revision: `2026-10-17.1`
- Date: 2026-10-17（Asia/Shanghai）
- Mode: ENHANCEMENT（Enhance existing merge；禁止平行第二套授权）
- Authoritative path: `docs/specs/0025-mcp-skill-capability-scopes.md`
- Sibling: `0019-device-target-defaults-and-session-unify`（binding 形状不变）、`0016-agent-native-configuration`（reload_status）、`0015`（设备发现 ≠ 授权）、`0005`（设备权限/grants 不替代本切片）
- Repository: `CkEFFAF/Octopus-public`
- Git 起点: `origin/main` @ `de5edcef3be4723e4a15e16ba33ad3b01108171e`（探测基线；实现前再 ff）
- 探测: `/workspace/0025-probe/PROBE-REPORT.md`（只读）
- 本文件性质: **GPT/Coder 可落地** compact SDD；**不写生产代码、不部署**（由总管另派）

---

## Goal

MCP、Skill（及同类能力附件：账号连接器注入、主机 skill packages）在 **专家级 / 设备级 / 全局（账号）级** 有统一、可观察的作用域模型，做到：

1. 新专家绑到「服务器」类设备时，**自动**获得该设备策略包中的 MCP/Skill（如 `jdcloud-mon`），无需手补 `agents.mcp_servers`。
2. GPU / 笔记本专家 **不会**因账号级开关被泄漏同一套云 MCP。
3. 解绑 / 换绑后，设备包带来的能力在下一轮生效集合中 **自动收回**，不残留。
4. 管理台可看见「生效来源」、缺工具告警与一键补齐。

用户原话约束：「不管是 MCP 还是 skill，这些设备级、专家级、还是全局级都得做好」。

---

## Non-goals

- 不把能力包塞进 `device_binding` JSON（0019 白名单保持薄：仅 `device_id|target_kind|root_id|working_dir`）。
- 不把 `devices.capabilities`（平台能力发现：shell/browser/…）与本策略包混名混用。
- 不把连接器 `shared` 解释为自动注入（仍仅为可见性）。
- 不把账号 `default_open` 当作「设备级」或推荐给云 MCP（用户已否掉全账号泄漏路径）。
- 不批量 PATCH 各专家的 `mcp_servers` 作为产品方案（手填名单问题会复发）。
- 不在 S0 做命名 pack 库 / SkillHub 市场 / 跨用户凭据代发。
- 不改 team host「无 MCP」既有规则。
- 不直接部署生产；本规格只定契约与切片。

---

## DEC（拍板）

| ID | 决议 |
| --- | --- |
| **DEC-C01** | **三级统一模型**：同一套「能力附件」抽象覆盖 MCP server 名与 Skill package id（及后续同类 list 型附件）。三级 = **专家 / 设备 / 全局(账号)**。 |
| **DEC-C02** | **挂载点**：专家继续用 `agents.mcp_servers` + `agents.skill_package_ids`（+ `skills_disabled`）；设备新增 `devices.capability_policy_json`（见 §数据模型）；全局继续用连接器/自定义 MCP 的 `default_open`（语义明确为 **账号全局注入**），Skill 全局自动注入 **S0 不做**（避免新泄漏面；S2 再议「账号 skill pack」且须默认关闭）。 |
| **DEC-C03** | **合并规则 = resolve-time union + deny**：禁止 copy-on-bind 写入专家名单。生效集 = 各层贡献做并集，再减 deny，再与用户可用连接器/已安装包做交集。 |
| **DEC-C04** | **设备包跟随执行设备**：贡献设备包的 `device_id` = 本轮 **已解析** `ExecutionContext.device_id`（与 0019 resolve 链一致：显式 → 会话/房间 → 专家 binding → 账户默认）。**不是**仅看专家默认 binding；房间统一切到 GPU 时，包随 GPU，不泄漏笔记本包。`target_kind=local` / 无 `device_id` → 无设备包贡献。 |
| **DEC-C05** | **优先级 / 冲突**：① turn 显式名单（含 Dashboard `[]`）最高；② deny 任一层命中即剔除；③ 其余层 **union**（专家 ∪ 设备包 ∪ 账号 default_open）；④ 最后 `validate_*_for_user` / 包存在性过滤。专家「故意多挂」与设备包并存，不互相覆盖。 |
| **DEC-C06** | **Dashboard `[]` opt-out**：保持今日语义——`metadata.mcp_servers` 出现（含空数组）→ `apply_defaults=False`，**同时** opt-out **账号 default_open 与设备包**（二者同属「defaults」）。UI 必须披露「本回合已关闭默认注入（账号+设备）」。IM/缺 key 仍 `apply_defaults=True`。 |
| **DEC-C07** | **设备级 ≠ default_open**：设备包只影响「本轮执行落在该 `device_id`」的回合；绝不账号内全专家注入。 |
| **DEC-C08** | **解绑自动收回**：仅改 binding / 解析设备变化即可；因 resolve-time 合并，无需从专家行删除。禁止把设备包永久拷进 `agents.mcp_servers`。 |
| **DEC-C09** | **生效时机**：策略/绑定写入立即落库；与 0016 一致返回/调度 `reload_status`（`pending_current_turn` \| `scheduled`）；**下一轮** `_resolve_turn_mcp_servers` / skill resolve + `prepare_chat_mcp` 生效。进行中回合不强制热换工具集。 |
| **DEC-C10** | **迁移**：不改写既有专家名单；`default_open`/`shared` 存储字段保留；运维可对云设备 **seed** `capability_policy_json.mcp_servers=["jdcloud-mon"]`（或管理台一键）；已手填同一 MCP 的专家 union 幂等。 |
| **DEC-C11** | **shared 不授权**：pack 只能引用当前用户 `list_active_mcp_server_names` 可见且校验通过的名字；不能凭 pack 偷用他人凭据。 |
| **DEC-C12** | **S0→S2 切片**：见 §实施切分；S0 以 MCP 设备包 + resolve union + 管理台最小编辑/告警为主；Skill 设备包字段同存，resolve 可同 PR 或紧随 S0.1。 |

---

## 现状摘要（代码事实 @ de5edce）

| 层 | 今日 | 缺口 |
| --- | --- | --- |
| 专家 | `agents.mcp_servers`、`skill_package_ids`、`skills_disabled` | 仅手填；绑设备不自动带 MCP |
| 设备 | binding 仅执行目标；`devices/capabilities.py` 只发现本机 CLI | **无**授权包 |
| 全局 | `default_open` → 全账号专家；`shared` = 可见性 | 太钝；用户否掉用它挂云 MCP |
| 合并 | `_resolve_turn_mcp_servers`：`default_open ∪ expert`（Dashboard `[]` 退出 defaults） | 缺设备层 |
| 绑定变更 | 只改 `device_binding` | 不碰 MCP/Skill |

关键路径：`connectors/default_open.py`、`connectors/service.py`（`merge_turn_mcp_servers`）、`gateway/process/processor.py`（`_resolve_turn_mcp_servers`）、`agents/manager.py`、`api/routers/agents.py`（binding 白名单）、`native_management_tools.py`（`reload_status`）。

---

## 数据模型

### 1) 设备策略包（新）

```text
devices.capability_policy_json: object | null
{
  "schema_version": 1,
  "mcp_servers": ["jdcloud-mon", ...],          # 可选，默认 []
  "skill_package_ids": ["pkg_...", ...],       # 可选，默认 []
  "deny_mcp_servers": [],                      # 可选硬拒绝
  "deny_skill_package_ids": []
}
```

- 校验：MCP 名走既有 `validate_mcp_servers_for_user(owner)`；skill id 必须在主机 `skill_packages` 存在且调用方有权用。
- **禁止**复用列名 `capabilities`（平台发现列表）。
- API：Device Manager / devices CRUD 可读写该字段；变更记审计（谁改、何设备、diff 摘要）。

### 2) 专家（不变语义，仍为「专家意图名单」）

```text
agents.mcp_servers: JSON list[str]
agents.skill_package_ids: JSON list[str]
config_json.skills_disabled: list[str]
```

### 3) 全局 / 账号

```text
connectors.config_json.default_open: bool     # 账号全局 MCP 注入
custom MCP spec.default_open: bool
connectors.shared / spec.shared: bool         # 仅可见性，永不单独注入
```

UI 文案改为「账号默认注入（所有专家）」；云 MCP **引导走设备包**，不引导开 default_open。

### 4) 可选后期（S2+，本 Ready 不强制建表）

```text
capability_packs(pack_id, owner_user_id, name, mcp_servers, skill_package_ids, denies...)
device_capability_pack_bindings(device_id, pack_id)
```

S0 用设备行内 JSON 足够。

### 5) 生效解析伪代码

```text
function effective_mcp(user_id, agent_id, turn_meta, resolved_device_id):
  explicit = turn_meta.mcp_servers   # missing | list
  apply_defaults = explicit is missing
  expert = AgentManager.default_mcp_servers(agent_id)
  account = list_default_open_mcp_server_names(user_id) if apply_defaults else []
  device = load_device_pack(resolved_device_id).mcp_servers if (apply_defaults and resolved_device_id) else []
  deny = expert_deny ∪ device_pack.deny_mcp_servers ∪ account_deny
  base = (explicit or []) ∪ (expert if apply_defaults or explicit is missing else [])
  # 精确对齐今日：explicit 出现时以 merge_mcp_servers_with_defaults 行为为准；
  # 本规格要求：apply_defaults 时 union(expert, device, account)；否则仅 explicit（可含用户勾选）
  merged = unique(union(explicit_or_empty, expert_if_defaults, device, account))
  merged = [n for n in merged if n not in deny]
  return intersect(merged, list_active_mcp_server_names(user_id))

effective_skills 同理：union(expert packages, device packages) − skills_disabled − deny；
turn.skills 过滤器最后生效；S0 无账号 skill default_open。
```

Coder 实现时以 **最小改动扩展** `merge_turn_mcp_servers` / skill package resolve 为准，保持 Dashboard/IM/cron 分支行为可测。

---

## 生效时机与 reload

| 事件 | 落库 | 工具集何时变 |
| --- | --- | --- |
| 改 `capability_policy_json` | 立即 | 下一轮 resolve；对绑定该设备的活跃专家 `schedule_reload` / 返回 `reload_status` |
| 改专家 `device_binding` | 立即 | 同上（0016） |
| 改专家 `mcp_servers` / packages | 立即 | 同上 |
| 改连接器 `default_open` | 立即 | 既有 `reload_connectors_for_user` |
| 会话/房间切换执行设备 | selection 落库 | **下一则消息**按新 `resolved_device_id` 取包（不必等专家 reload） |

契约：进行中 turn 保持旧工具集；与 `reload_status: pending_current_turn` 语义一致。

---

## 安全边界

1. **设备包 ≠ default_open**（DEC-C07）。
2. **解绑/换设备 → 自动收回**（DEC-C08）；验收禁止「解绑后专家行仍多出仅来自设备包的 MCP」。
3. **跨设备不泄漏**：包跟 `resolved_device_id`；笔记本回合不得带上仅写在云设备包里的 MCP。
4. **共享专家文本范围**（0016）：若已有「共享文本剥离 MCP」规则，必须保留；设备包不得绕过。
5. **校验**：每次合并后 `validate_mcp_servers_for_user`；失效名 → 生效集剔除 + 管理台/回执 `missing_or_unauthorized` 提示，不静默当成功授权。
6. **team host**：继续无 MCP（`_resolve_turn_mcp_servers` → `None`）。
7. **凭据**：pack 不创建连接器实例；只引用用户已有可用 server 名。

---

## 管理台（最小）

| 能力 | 要求 |
| --- | --- |
| 设备策略编辑 | Device Manager：编辑该设备 `mcp_servers` / `skill_package_ids` / deny；保存后提示「下一轮生效」 |
| 专家侧只读来源 | 专家连接器/技能页展示 **生效预览**：专家名单 / 设备包（若当前 binding 有 device_id）/ 账号 default_open；标注来源徽章 |
| 缺工具告警 | 设备包或专家名单引用了用户不可用的 MCP/缺失 skill → 警告条 |
| 一键补齐 | 「将当前缺失的云监控 MCP 写入本设备策略包」类动作（写 **设备包**，不写遍所有专家） |
| 引导 | 云设备向导默认推荐设备包；显著警告「勿对云 MCP 开账号 default_open」 |

手机/桌面只要能达 Device Manager 或等价 API；不强制新一级导航。

---

## 迁移

| 步骤 | 动作 |
| --- | --- |
| M1 | 加列/JSON 字段；默认 `null`/`{}` = 无设备贡献 |
| M2 | 保留所有 `agents.mcp_servers` / `skill_package_ids` 原值 |
| M3 | `default_open`/`shared` 字段不删；文案与文档改为「账号全局」 |
| M4 | **Ops/管理台**：对已知云设备（如生产 `main`、`Y39HY4`）seed `mcp_servers: ["jdcloud-mon"]`（幂等） |
| M5 | 不批量改专家；已含 jdcloud-mon 的专家继续工作 |
| M6 | Skill：仅启用设备∪专家 union；不引入账号 skill 自动注入，直至 S2 单独 DEC |

回滚：忽略 `capability_policy_json` 即回退到旧二层合并。

---

## 需求与验收

### REQ

| ID | 需求 |
| --- | --- |
| **REQ-C01** | 系统提供设备级能力策略包，可配置 MCP 与 Skill 包 id（及可选 deny）。 |
| **REQ-C02** | 回合生效 MCP/Skill 按 DEC-C03–C06 合并；跟 `resolved_device_id`。 |
| **REQ-C03** | 解绑或解析设备变化后，设备包贡献从下一轮生效集消失。 |
| **REQ-C04** | 账号 `default_open` 不得被文档/UI 表述为设备级；云 MCP 推荐设备包路径。 |
| **REQ-C05** | 策略与绑定变更对齐 `reload_status` / 下一轮 `prepare_chat_mcp`。 |
| **REQ-C06** | 管理台可编辑设备包，展示生效来源，缺工具可告警并可一键写入 **设备包**。 |
| **REQ-C07** | 迁移不破坏既有专家名单与连接器数据；seed 可选且幂等。 |

### AC（可观察）

| ID | Given / When / Then |
| --- | --- |
| **AC-C01** | Given 云设备 D 策略含 `jdcloud-mon` 且用户可用该连接器；When 新专家仅 binding→D、专家 `mcp_servers=[]`、账号 default_open 关；Then 下一 IM/缺 key 回合生效集 **含** jdcloud-mon。 |
| **AC-C02** | Given 同账号另一专家 binding→GPU 设备（包不含 jdcloud-mon）；When 回合解析到 GPU；Then 生效集 **不含** jdcloud-mon（除非专家名单或 default_open 显式有）。 |
| **AC-C03** | Given 专家曾因 D 获得设备包 MCP；When 解绑或改绑到无该 MCP 的设备；Then 下一轮生效集不再含仅来自 D 包的项；专家行 `mcp_servers` 未被偷偷改写。 |
| **AC-C04** | Given Dashboard 发送 `mcp_servers: []`；When 回合开始；Then 不注入 default_open **也不**注入设备包；UI/日志可观察 opt-out。 |
| **AC-C05** | Given 设备包含用户不可用的名；When resolve；Then 该名不进入工具集，且管理台或 API 返回 missing 告警（非静默当已授权）。 |
| **AC-C06** | Given team host；When resolve；Then 仍无 MCP。 |
| **AC-C07** | Given 改设备包；When 保存；Then 落库成功并给出 `reload_status` 或等价「下一轮生效」信号；进行中 turn 工具集不变。 |
| **AC-C08** | Given Skill 设备包含 pkgX、专家未列 pkgX；When S0.1/S1 启用 skill union；Then 解析到该设备时可用 pkgX；换设备后收回。 |
| **AC-C09** | Given 迁移后旧专家已手填 jdcloud-mon；When 设备包也含同名；Then union 幂等，行为与单侧有时一致（不双倍工具）。 |

---

## 实施切分

| 切片 | 范围 | 必过 |
| --- | --- | --- |
| **S0**（建议第一 PR） | `capability_policy_json` + API/Device Manager 最小编辑；扩展 MCP resolve union（DEC-C03–C06）；seed 文档/脚本说明；单测合并矩阵；AC-C01–C07、C09（MCP） | MCP 设备级可用 |
| **S0.1 / S1** | Skill package 同等 union + 专家页来源徽章；AC-C08 | Skill 设备级对齐 |
| **S2** | 缺工具扫描、一键补齐、default_open UX 迁「账号包」文案；可选 named packs | 管理体验 |
| **Out** | 账号级 Skill 自动注入、copy-on-bind、改 binding 白名单塞包 | — |

---

## Coder brief（交接）

```text
规格: docs/specs/0025-mcp-skill-capability-scopes.md（Rev 2026-10-17.1）
仓库: CkEFFAF/Octopus-public；ff 最新 main 后再开分支 feature/0025-capability-scopes
探测: 对齐 PROBE-REPORT @ de5edce（实现前再确认 tip）

S0 必做:
1) devices.capability_policy_json（migration + repo + API）
2) 扩展 merge_turn_mcp_servers / _resolve_turn_mcp_servers：
   apply_defaults 时 union(expert, device_pack[resolved_device_id], account default_open)
   Dashboard [] 同时退出账号+设备 defaults
3) resolved_device_id 取自本轮 ExecutionContext（与 0019 一致）
4) Device Manager 可编辑；保存→reload_status 对齐 0016
5) 测试: AC-C01–C07、C09；team host；校验失败告警
6) 文档: 云 MCP 用设备包；禁止教用户开 default_open 当设备授权

不要:
- 批量 PATCH 专家 mcp_servers
- 把包写入 device_binding
- 复用 devices.capabilities 列
- 本切片部署生产（总管另派）

Skill: 字段可同 migration；resolve 可同 PR 或紧随 S0.1。
```

### 实现触及面（预期）

| 区域 | 文件（探测索引） |
| --- | --- |
| 合并 | `infra/connectors/default_open.py`、`service.py`、`gateway/process/processor.py` |
| 专家 MCP 默认 | `infra/agents/manager.py` |
| 设备存储/API | `infra/db/repos/devices.py`、devices router、Device Manager UI |
| reload | `native_management_tools.py`、`agents` reload、`reload_connectors_for_user` |
| Skill | skill package resolve / overlay 路径（S0.1） |
| 校验 | `api/common/validators.py`、`validate_mcp_servers_for_user` |

---

## OQ（不挡 S0）

| ID | 问题 | 默认 |
| --- | --- | --- |
| **OQ-C01** | 账号级 Skill 自动注入是否要做？ | S0/S1 **不做**；要做单开 DEC |
| **OQ-C02** | deny 是否暴露管理台？ | S0 schema 预留；UI 可隐藏到 S2 |
| **OQ-C03** | cron/无设备上下文回合？ | 无 `device_id` → 无设备包；仅专家∪（若 apply_defaults）账号 |

---

## Evolution

| Rev | 变更 |
| --- | --- |
| `2026-10-17.1` | 首版 Ready：三级作用域、union+deny、设备包跟 resolved device、迁移与 S0 切片；并入 0025-probe。 |
