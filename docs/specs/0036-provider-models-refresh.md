# 0036 模型提供商页面「更新模型」

- Revision: 2026-10-22.1（Asia/Shanghai）｜Contract: **Ready**
- Owner: Octopus 架构师 → Coder｜权威源：本文件
- Decision basis: 用户王俊浩「模型提供商页面必须加更新按钮，内测期完整方案」；总管派单；对照 tip 代码核验
- Code baseline: `CkEFFAF/Octopus-public` `origin/main` @ **ee2f19d9**（`ee2f19d Merge pull request #43`）
- Delivery: compact SDD｜Verification: standard（单测 + Playwright 真浏览器截图）｜Continuity: collaborative（架构师规格 → Coder 实现）
- 编号说明：tip 上已存在 `0035-connector-skill-live-configuration.md` 与 `0035-conversation-metadata-and-title-model.md`，故本规格取 **0036**（非 0035）

## 1. Goal and boundaries

**用户/调用方**：管理台「设置 → 模型」的账号管理员。  
**问题**：提供商模型列表滞后（打包 `provider_template.json` 过期 + 更新入口深藏抽屉 + 非 openai 协议无法拉远端）。顶栏 Refresh 只 `fetchAll` 重读 DB，不刷新远端/预置目录。  
**结果**：每个已配置提供商卡片上有可见「更新模型」；一点即可按协议能力拉取远端或合并最新 bundled preset，**自动写入 DB**，保留用户手工模型，失败不改坏已有列表。

### In scope
- 卡片级「更新模型」主入口 + 抽屉内保留高级拉取/同步
- 服务端合并策略 + `source` 标记 + 自动 PATCH 持久化
- openai-compatible 远端 `GET /models`；其它协议明确 disable + 文案，仍可走 preset 合并
- 单测 + Playwright 前后截图

### Non-goals
- 不改云端部署 / 不发版镜像；不顺带升级整包 `octop_harness` 版本策略（仅消费当前进程已加载的 bundled preset）
- 不实现 anthropic/gemini 官方 List Models API（记 OQ / S1+）
- 不批量「一键更新全部提供商」（可后续加；本规格单卡）
- 不删除用户已启用模型的启用态；不静默覆盖用户改过的 name/limits/thinking

### Constraints / deps
- 现有：`POST /providers/fetch-models`（仅 `kind=openai`）、抽屉 `handleFetchModels` / `syncPresetModels`、`mergePresetModels`、`PATCH /providers/{id}`、`load_provider_presets()` → `octop_harness` `provider_template.json`
- 相关路径：`src/octop/api/routers/providers.py`、`infra/agents/providers/{presets,catalog,probe,store}.py`、`dashboard/.../Settings/Models/**`

## 2. 现状（代码证据 @ ee2f19d）

| 点 | 路径 | 事实 |
| --- | --- | --- |
| 顶栏 Refresh | `dashboard/.../Models/index.tsx:249-254` | `onClick → fetchAll()`，仅重读 DB/presets，不碰远端 |
| 卡片 | `components/cards/ProviderCard.tsx` | 有测试连接 / 编辑 / 删除；**无**更新模型 |
| 抽屉拉取 | `ProviderConfigModal.tsx:889-986` | `fetchProviderModels`；`kind !== "openai"` → warning `fetchModelsUnsupportedKind`；成功只改 draft + `setFormDirty(true)`，**需用户再点保存** |
| 抽屉同步预置 | 同文件 `:1116-1129` | `mergePresetModels(models, preset.models, preset.models)`，只改 draft |
| 合并函数 | `mergePresetModels.ts` | 保留已有 id 的用户字段；追加 fetched 缺失 id 且 `enabled:false`；**不删**；**无 source 字段** |
| API | `routers/providers.py:385-407` / `:586` | `POST .../fetch-models` openai only，要 api_key；不写库 |
| 远端实现 | `probe.py:274-348` | OpenAI-compatible `GET {base}/models`；Go 特例改写 URL |
| 预置 | `presets.py:216+` | `resources.files("octop_harness.providers")/provider_template.json`；抽样约 40 条，协议以 `openai` 为主，少量 `anthropic` |
| 自定义 kind UI | `CustomProviderModal.tsx:25-29` | `openai` / `anthropic` / `bedrock` |

根因（与总管一致，已核验）：**入口深藏 + 不自动保存 + 非 openai 无远端 + 预置随打包滞后**。

## 3. Requirements and acceptance

### REQ-001 — 卡片级「更新模型」入口
- Source: 用户/总管拍板（卡片级主入口）
- Requirement: 已配置的 Provider 卡片（`ProviderCard`；分组内实例同理）在非 hover 依赖下仍可见「更新模型」按钮；点击触发服务端 refresh；进行中按钮 loading；抽屉内保留「获取模型」「同步预置」作高级操作。
- AC-001: Given 已保存的 openai 提供商且有 api_key，When 点卡片「更新模型」，Then 不打开抽屉即可完成更新并 toast 摘要。
- AC-002: Given 无 api_key 但有匹配 preset，When 点更新，Then 走 preset 合并路径（见 REQ-003），不假装拉了远端。
- Verification: Playwright 真浏览器；截图 `docs/specs/assets/0036/before-card.png` / `after-card.png`。

### REQ-002 — 进度 / 失败 / 自动保存
- Requirement: 成功则**自动写入**该 provider 的 `models_json`（等价 PATCH models）；失败 toast 明确原因，**DB 与内存列表保持更新前状态**；进行中禁用重复点击。
- AC-003: Given 远端 5xx / 网络错误，When refresh，Then toast 失败文案，重新打开抽屉模型列表与更新前一致。
- AC-004: Given 成功新增 N 个模型，When 刷新整页，Then 新模型仍在（已持久化），且默认 `enabled:false`（与现 merge 行为一致）。
- Verification: 单测 mock 远端失败不写 repo；Playwright 成功路径刷新后仍见新模型。

### REQ-003 — 数据源优先级与协议范围
- Requirement: 单次 refresh 的数据源决策：
  1. **若** `kind` 支持远端列举 **且** 有可用 api_key → 调用远端 list，得到 `remote[]`；
  2. **始终**（若存在匹配 bundled preset）加载最新 `preset.models` 作为元数据目录；
  3. 合并输入 = `remote`（若有）∪ `preset.models`（仅 id/元数据），再与当前 DB 模型做 merge；
  4. 若既无远端能力/失败且无 preset → 返回明确错误，不写库。
- 协议矩阵（S0）：

| kind / protocol | 远端 list | S0 行为 |
| --- | --- | --- |
| `openai`（含各类 openai-compatible base_url） | ✅ `GET /models`（复用 `fetch_openai_compatible_models`） | 远端优先 + preset 补元数据 |
| `anthropic` | ❌ | 按钮可用：仅 preset 合并；tooltip/toast 说明「本协议暂不支持远端列举」 |
| `bedrock` / 其它非 openai | ❌ | 同上；无 preset 则 disable + 文案 |
| onnx / ollama 本地运行时 | 既有 catalog/本地 list | S0：**卡片按钮 disable** 或走现有抽屉逻辑，不纳入本 API（避免与下载态耦合）；文案指向抽屉 |

- AC-005: openai + key → 响应含 `source_used: "remote+preset"|"remote"`。
- AC-006: anthropic + preset → `source_used: "preset"`，不发起 OpenAI `/models`。
- AC-007: 不支持协议且无 preset → 按钮 disabled，hover 文案可理解。

### REQ-004 — 合并策略与 source（不静默丢掉手工模型）
- Requirement: 在 `mergePresetModels` 之上（可抽共享纯函数，前后端语义一致）增加：
  - **永不删除**当前列表中远端与 preset 都没有的模型；为其标记 `source: "user"`（若尚无 source）。
  - 从远端新出现的 id：`source: "remote"`，`enabled: false`，用 preset 元数据填充（若有）。
  - 仅在 preset 中的 id：`source: "preset"`。
  - 已存在 id：保留用户 `enabled/name/thinking/limits/use_responses_api` 等显式选择；仅在字段为空时用 preset 补齐（与现逻辑一致）。
  - 不得因为「远端不再返回」而删除用户已有模型（远端缩减 ≠ 本地删除）。若未来要做「清理失效」，必须另开规格与二次确认。
- AC-008: 手工添加 `my-custom-model` 后 refresh，该行仍在且 `source==="user"`（或等价可见标记）。
- AC-009: 现有 `mergePresetModels.test.ts` 行为回归全绿；新增 source 用例。

### REQ-005 — API 合同
- Requirement: **新增** `POST /api/providers/{provider_id}/refresh-models`（admin 与账号路由对称，与现有 `/{id}/test` 同权限模型：`require_permission("providers")` + 归属校验）。
- 不建议只靠前端串 `fetch-models` + `PATCH`：权限、合并、source、失败原子性应在服务端一次完成，避免抽屉脏写与卡片写两套逻辑。
- 既有 `POST /providers/fetch-models` **保留**给抽屉/未保存 draft 使用。

请求：无 body 或可选 `{ "prefer": "remote"|"preset"|"auto" }`（默认 `auto`，按 REQ-003）。

响应（示例字段）：
```json
{
  "ok": true,
  "provider_id": 12,
  "source_used": "remote+preset",
  "remote_supported": true,
  "added": [{"id": "gpt-x", "source": "remote"}],
  "enriched": 3,
  "kept_user": [{"id": "my-custom-model"}],
  "models": [/* 完整合并后列表，与 GET 单卡一致 */],
  "error": null
}
```
失败：`ok:false` + `error` 字符串；HTTP 可仍 200（与现 fetch-models/test 风格一致）或 4xx 仅用于无权限/无此 id。

- AC-010: 单元/集成测覆盖 auto 决策、写库、失败不写库。
- AC-011: 无权限 / 非本人 provider → 与现 PATCH 相同错误语义。

### REQ-006 — 验收证据
- AC-012: `tests/unit/` 合并与 refresh 服务逻辑；扩展或并列 `test_provider_fetch_models.py`。
- AC-013: Playwright 真浏览器（dashboard）路径：打开设置/模型 → 截图更新前 → 点「更新模型」→ 等待 toast/loading 结束 → 截图更新后 → 打开抽屉确认列表；产物目录 `docs/specs/assets/0036/`。
- AC-014: 中英文 i18n 键齐全（按钮、disable 原因、成功摘要含 added 数、失败）。

## 4. Decisions

| ID | Decision | State | Source | Affected | Blocking? |
| --- | --- | --- | --- | --- | --- |
| DEC-0036-1 | 主入口在**卡片**「更新模型」；抽屉保留获取/同步预置 | resolved | 用户/总管倾向 | REQ-001 | 否 |
| DEC-0036-2 | 数据源：可探测协议+有 key → 远端；否则/同时合并 bundled preset；**不**静默删除仅用户有的模型；写 `source` | resolved | 拍板 + 代码缺口 | REQ-003/004 | 否 |
| DEC-0036-3 | 成功**自动写 DB**；失败 toast 且不改库 | resolved | 拍板 | REQ-002 | 否 |
| DEC-0036-4 | 新增 `POST /providers/{id}/refresh-models`；保留 draft 用 `fetch-models` | resolved | 原子性/权限 | REQ-005 | 否 |
| DEC-0036-5 | S0 远端仅 **openai-compatible**；其它协议 preset-only 或 disable+文案 | resolved | 拍板 | REQ-003 | 否 |
| DEC-0036-6 | `mergePresetModels` 语义扩展（source + 明确 never-delete）；前后端共用策略说明；TS 单测保留，Python 侧重服务端持久化 | resolved | 现有测试资产 | REQ-004 | 否 |
| DEC-0036-7 | 顶栏 Refresh **保持**「重读 DB」语义，不改成全员远端刷新（避免意外打爆上游） | resolved | 降低风险 | — | 否 |

## 5. Coder 实现指南

### 分支
`feature/0036-provider-models-refresh`（基于 `main` @ ee2f19d9 或更新 tip；若 tip 前进则 rebase，冲突以本规格 REQ 为准）。

### 切片

**S0（可合并的最小完整）**
1. 后端：`refresh_provider_models` 领域函数（probe 远端 optional + load preset + merge + repo.update models_json）；路由挂 admin + user 对称。
2. 扩展模型 dict 允许可选 `source` 字段（读写透传；旧数据缺省按规则回填）。
3. 前端：`ProviderCard`（及展示已配置实例的卡片）加按钮 → 调新 API → toast → `onSaved()`。
4. i18n zh/en。
5. 单测：merge/source、refresh 成功写库、远端失败不写、anthropic 走 preset。
6. Playwright：1 条主路径 + 截图目录。

**S1（增强，可同 PR 或 follow-up）**
- 抽屉「获取模型」成功后可选「立即保存」与卡片路径对齐（或提示已脏）。
- anthropic Messages Management / Gemini list 若官方稳定再接入（本规格不阻塞）。
- 列表级「更新全部 openai 提供商」带并发上限。

### 文件边界（建议可写）

| 区域 | 文件 |
| --- | --- |
| API | `src/octop/api/routers/providers.py` |
| 领域 | `src/octop/infra/agents/providers/probe.py`（复用 fetch）、**新建** `.../providers/refresh.py`（或 `store.py` 旁）放合并+持久化 |
| 预置 | `presets.py` / `catalog.py` 只读复用 |
| 前端卡片 | `dashboard/src/pages/Settings/Models/components/cards/ProviderCard.tsx`（必要时 `PresetGroupCard` 内已配置实例） |
| 合并 | `mergePresetModels.ts` + `.test.ts`；`providerApi.ts` 新客户端函数 |
| 文案 | `dashboard/src/locales/{zh,en}.json` |
| 测试 | `tests/unit/test_provider_refresh_models.py`（新）；现有 fetch-models 测不删 |
| E2E | 项目既有 Playwright/ego-browser 约定目录（若无则 `dashboard/e2e/provider-models-refresh.spec.ts`，脚本写入 `docs/specs/assets/0036/`） |
| 规格资产 | `docs/specs/assets/0036/*.png` |

**不要改**：Harness 打包流水线、provider_template.json 内容本身（滞后用「更新」消费当前包；升级模板是独立发布问题）、顶栏 Refresh 语义。

### 实现伪流程（服务端）
```
row = repo.get(user, id)
preset = match_preset(row)
remote_ok, remote_models, remote_err = (False, [], None)
if row.kind == "openai" and row.api_key:
    r = await fetch_openai_compatible_models(...)
    if r.ok: remote_ok, remote_models = True, r.models
    else: remote_err = r.error  # 若有 preset 可降级；两者皆无则 fail
fetched = remote_models
presets = preset.models if preset else []
if not remote_ok and not presets: return fail(remote_err or "no catalog")
merged = merge_with_source(row.models, fetched, presets)
repo.update(..., models_json=merged)
return ok summary
```

## 6. Open questions

| ID | Question | Owner | Affects | Blocking S0? |
| --- | --- | --- | --- | --- |
| OQ-0036-1 | anthropic/gemini 官方 list API 是否纳入 S1？ | 产品 | REQ-003 | 否（S0 已 disable/preset） |
| OQ-0036-2 | 是否在 ModelListEditor 展示 source 徽章（user/remote/preset）？ | 产品 | REQ-004 | 否（字段先落库；UI 徽章可 S1） |
| OQ-0036-3 | 用户机权威工作副本是 `octopus-public` 还是另建 `docs/specs` 根？ | 总管 | 同步路径 | 否 |

## 7. Evolution

- Change history: 2026-10-22.1 初版 Ready（compact SDD）
- Contract readiness: Ready —— 第二实现者可按切片开工，无阻塞 OQ
- Implementation / verification / release: planned / not run / 不部署云端

