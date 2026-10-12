# 0010 过渡期默认入口（双路径：包默认 HTTPS + 过渡 env）

- Spec ID: `0010-transition-default-server`
- Status: **Accepted-transition**（备案完成 / Tunnel HTTPS 可用后按「回切」执行；**不是**永久改产品默认常量）
- Revision: `2026-10-12.2`
- Date: 2026-10-12
- Authoritative path: `docs/specs/0010-transition-default-server.md`
- Relates:
  - `0006-device-first-run-launcher.md`（向导 / `open-device`；**DEC-001 产品默认 HTTPS 不变**；过渡靠本规格路径 B）
  - `0007-portable-release-packages.md`（同一 Win/Linux Release **包内默认仍是** `https://octop.effaf.me`；禁止把 IP 写进包内常量）
  - `0009-cloud-hub-production.md` / `docs/octopus/cloud-hub-ops.md`（本周中枢 HTTP IP 冒烟）
  - `docs/octopus/same-account-enroll-ops.md`（运维示意）
- Non-overwrite: **不修改** Accepted `0004` 正文；**不改** enroll API / 安全边界 / 凭证模型；只约束执行端**如何选默认 server** 与**有限** `allow-insecure` 例外。
- Deploy fact（2026-10-12）:
  - 备案要几天；京东云未备案域名拦 80/443，`octop.effaf.me` **暂不可用**
  - 云中枢已起：`http://111.228.42.228:8188`
  - 产品体验不变（UU 式）：用户**只输账号密码** → 自动采集设备信息 → 进设备网；**不要**手填 `--server`

## Problem

0006 DEC-001 / 0007 / ops 写死：产品默认 = `https://octop.effaf.me`（**禁止**把云主机 IP 当产品默认）；HTTP 远程通常要 `--allow-insecure`；向导默认不允许一键 insecure（0006 AC-013）。

备案前该默认**不可达**。若改包内 `DEFAULT_DEVICE_SERVER` 为 IP，会污染正在打的 Release、违背 DEC-001，且回切成本高。用户/总管确认：**双路径**——包默认永远 HTTPS；备案前用 env / 过渡启动器切到 HTTP IP。

## Dual paths（硬约束）

### 路径 A — 产品 / 包默认（永久，备案后也是这个）

- `DEFAULT_DEVICE_SERVER = "https://octop.effaf.me"`（`src/octop/infra/devices/protocol.py`）
- 同一 Win/Linux Release **包内默认仍是 HTTPS**
- Coder 正在打 Release：**禁止**规格要求改包内常量为 IP
- 未设置 `OCTOP_DEVICE_SERVER` 时，`open-device` / `device first-run` / `device join` 预填 HTTPS 域名

### 路径 B — 备案前过渡

- 设置 `OCTOP_DEVICE_SERVER=http://111.228.42.228:8188`（或等价：过渡期 `open-device.bat/.sh` 内 `set`/`export` 该值；或附带 transition 说明/小脚本）
- 双击后 Server **预填 IP**；用户只输账密
- 对**白名单 URL**自动 `allow_insecure=True`（见 DEC-T03/T04）；**勿**永久放开任意 `http://`

### 回切（备案后）

1. 撤掉 `OCTOP_DEVICE_SERVER` / 过渡 launcher 里的 set/export → 恢复路径 A（包默认 HTTPS）
2. 过渡 insecure 白名单可保留到确认无用后删除（或随本规格 Superseded 一并删）
3. **不要**在回切时再改 `DEFAULT_DEVICE_SERVER`（它本来就一直是 HTTPS）

## Goals

1. 包内 / 常量默认永远是 `https://octop.effaf.me`（路径 A）
2. 备案前：通过 `OCTOP_DEVICE_SERVER`（或过渡启动器写入该 env）让向导预填 `http://111.228.42.228:8188`，用户只输账密（路径 B）
3. 对**过渡白名单 URL**自动 `allow_insecure=True`；范围写死；非白名单 remote HTTP 仍需显式 flag / 边界确认
4. 备案后回切：只撤 env / 过渡启动器设置；常量无需再改
5. 与 0007「包默认 HTTPS」一致；与 0009「中枢 HTTP IP、开箱默认仍域名」一致

## Non-goals

- 改 `DEFAULT_DEVICE_SERVER` 为 IP，或「暂停 DEC-001 改常量」
- 永久放开任意 `http://` remote
- 改 0004 enroll 协议、JWT、key-session、device-state 字段语义
- 改管理端包 / systemd / 安全组（见 0009）
- 本规格直接改业务代码（交 Coder 按下方 brief）
- 手机端

## Decisions

| ID | 决策 | State |
|---|---|---|
| DEC-T01 | **路径 A**：`DEFAULT_DEVICE_SERVER` **保持** `"https://octop.effaf.me"`；**禁止**改成 IP | **resolved**（用户/总管双路径） |
| DEC-T02 | **路径 B**：备案前用 `OCTOP_DEVICE_SERVER=http://111.228.42.228:8188`（及 open-device/向导/ops 如何设置该 env）切到 HTTP IP；`resolve_default_device_server()` 已有非空 env 覆盖则**保留**该行为 | **resolved** |
| DEC-T03 | **scoped insecure**：仅当 URL 命中过渡白名单时自动 `allow_insecure=True`；其它 remote HTTP 仍要显式 flag / 边界确认；不违反「成功路径不永久一键放开任意 http」 | **resolved** |
| DEC-T04 | 白名单判定：规范化后 `scheme=http` **且** `host=111.228.42.228` **且** `port in {8188}`；无 userinfo；path 空或 `/`；query/fragment 拒绝或不全匹配 | **resolved** |
| DEC-T05 | GUI（Tk）提交时若 server 为白名单 URL：**跳过**未配证书确认框，直接 enroll | **resolved** |
| DEC-T06 | CLI `_prompt_server`：预填来自 `resolve_default_device_server()`；若用户未改且为白名单，**跳过** `click.confirm` insecure | **resolved** |
| DEC-T07 | 0006 DEC-001 **不暂停、不改写**；本规格是 DEC-001 之上的 **env 过渡层** | **resolved** |
| DEC-T08 | 0007 Release 包内默认仍 HTTPS；过渡机靠 env / 过渡启动器，**不**打「默认 IP」专用包（除非用户另拍） | **resolved** |
| DEC-T09 | 回切：撤 `OCTOP_DEVICE_SERVER` / 过渡 launcher 设置即可；可选删除 `is_transition_insecure_allowed` | **resolved** |

## Requirements

### REQ-T01 — 包默认保持 HTTPS（路径 A）

- Requirement: `DEFAULT_DEVICE_SERVER` 保持 `"https://octop.effaf.me"`。未设 `OCTOP_DEVICE_SERVER` 时，`open-device` / `device first-run` / `device join`（含 advanced）预填该 HTTPS。
- AC-T01: 干净机、未设 env、无旧 device-state：双击 `open-device` → Server 栏预填 `https://octop.effaf.me`。
- AC-T02: **禁止**为满足备案前可达而修改包内常量为 `http://111.228.42.228:8188`。

### REQ-T02 — 过渡靠 OCTOP_DEVICE_SERVER（路径 B）

- Requirement: 设置 `OCTOP_DEVICE_SERVER=http://111.228.42.228:8188` 后，同一二进制/解压包预填该 URL。可选：过渡期改 `open-device.bat/.sh` 在启动前 `set`/`export OCTOP_DEVICE_SERVER=...`，或附 `open-device-transition.*` / 说明文档；**不要**改 protocol 常量默认值。
- AC-T03: 过渡机设好 env（或过渡启动器）→ 双击 → Server 预填 `http://111.228.42.228:8188` → 只输账密 → 按 0004 enroll。
- AC-T04: 设 `OCTOP_DEVICE_SERVER=https://example.test` 时预填为该值（通用 env 覆盖，非仅过渡）。

### REQ-T03 — 白名单自动 allow-insecure

- Requirement: 新增 `is_transition_insecure_allowed(url: str) -> bool`（建议 `protocol.py` 或 `client.py`）。`validate_server_url` **不改**「remote HTTP 要 allow_insecure」全局规则；调用方在命中白名单时传入 `allow_insecure=True`。
- 调用点至少：
  1. `run_tk_first_run` → `enroll_with_account(..., allow_insecure=...)`
  2. `_prompt_server`（`device_startup_cmd.py`）：白名单跳过 confirm
  3. 可选在 `enroll_with_account` / `resolve_server_url` 内抬升，防 GUI 漏传
- AC-T05: 白名单 URL：GUI 一键「Sign in and join」成功；**无** insecure 确认框；**无** `remote HTTP requires explicit --allow-insecure`。
- AC-T06: 对 `http://evil.example:8188`（非白名单）仍拒绝，除非显式 `--allow-insecure` / confirm。
- AC-T07: `https://octop.effaf.me` 走 TLS 路径，不因本规格触发 insecure。

### REQ-T04 — 回切

- Requirement: 备案完成后执行「回切」清单；本规格 Status → **Superseded**（或注明 transition ended）。
- AC-T08: 回切后未设 env 的包仍默认 HTTPS；白名单 helper 可删或恒 false；常量本就无需再改。

### REQ-T05 — 文档优先级

- Requirement: 过渡期冲突时优先级：**0010（本双路径）> 0007 包默认叙述 > 0006 DEC-001 产品默认 > 0009「勿写进开箱默认」旧措辞**。0009 管理端 HTTP IP 不变；设备侧过渡机用路径 B，备案后回路径 A。
- AC-T09: `same-account-enroll-ops.md` / `cloud-hub-ops.md` / 0006 Transition 节指向本规格双路径（同一文档变更集）。

## 回切步骤（Coder / 运维）

1. 确认 `curl -sS https://octop.effaf.me/api/health`（或等价）从公网成功。
2. 各过渡机：删除 `OCTOP_DEVICE_SERVER`；若改过 `open-device.*`，去掉过渡 `set`/`export` 或停用 transition 脚本。
3. 可选：删除 `is_transition_insecure_allowed` 及自动抬升；恢复相关单测。
4. 更新 0006/0007/ops 交叉引用；本规格 Status → Superseded；Evolution 记回切日期与 Release tag。
5. **不要**改 `DEFAULT_DEVICE_SERVER`（保持 HTTPS）。

## Coder 实现清单（可交接）

### 现状锚点

| 项 | 路径 | 动作 |
|----|------|------|
| 包默认常量 | `src/octop/infra/devices/protocol.py`：`DEFAULT_DEVICE_SERVER = "https://octop.effaf.me"`；`resolve_default_device_server()` + `OCTOP_DEVICE_SERVER` | **保持常量**；确认 env 覆盖仍有效 |
| URL 校验 | `src/octop/infra/devices/client.py` `validate_server_url` | **不改**全局规则；白名单在调用方传 flag |
| GUI | `src/octop/infra/devices/first_run.py` `run_tk_first_run` | 白名单时 `allow_insecure=True` |
| CLI 提示 | `src/octop/cli/device_startup_cmd.py` `_prompt_server` | 白名单跳过 confirm |
| 开箱脚本 | `desktop/portable/open-device.bat` / `open-device.sh` | **可选**过渡期 set/export `OCTOP_DEVICE_SERVER`；或另附 transition 脚本 + README；**不要**改 protocol 常量 |
| 测试 | `tests/unit/devices/test_first_run_0006.py` 等 | 双路径：无 env→HTTPS；有过渡 env→IP + insecure 抬升；非白名单仍拒 |

### 建议改动顺序

1. `protocol.py`：新增 `is_transition_insecure_allowed(url)`；**不改** `DEFAULT_DEVICE_SERVER`。
2. `first_run.py` / `device_startup_cmd.py`：白名单自动 `allow_insecure=True` / 跳过 confirm。
3. 可选：`open-device.bat/.sh` 过渡 set，或 `docs` + `open-device-transition.*`。
4. 单测：路径 A / 路径 B / 非白名单拒绝 / 通用 env 覆盖。
5. 文档：ops 双路径说明（可同 PR）。
6. **不要**改 `0004` Accepted；**不要**改 enroll HTTP API；**不要**把 IP 写进包内默认常量。

### 验收（人工）

1. **路径 B**：过渡机设 `OCTOP_DEVICE_SERVER=http://111.228.42.228:8188`（或过渡启动器）→ 双击 `open-device` → 只输账密 → 登记成功 → 客户端保持连接。
2. 管理端 Dashboard（`http://111.228.42.228:8188`）同账号可见新设备。
3. **路径 A**：未设 env 的同一 Release 包 → 预填仍 `https://octop.effaf.me`。
4. 非白名单 `http://` 远程地址无 flag 时仍失败或要确认。

## Open Questions

| ID | 问题 | State |
|---|---|---|
| OQ-T01 | 回切后是否给已 enroll 设备提供一键 migrate（device-state 已持久化 server）？ | **deferred**（一般改 device-state 或重装向导即可） |
| OQ-T02 | 过渡说明是否随 `v1.0.2b6` Release notes 附带，或另附 transition 脚本？ | **open**（不阻塞实现；建议 notes 写清双路径） |

## Evolution

- 2026-10-12.1: 初稿曾倾向「改 DEFAULT_DEVICE_SERVER 为 IP / 暂停 DEC-001」——**已作废**。
- 2026-10-12.2: **紧急修订为双路径**。路径 A = 包默认 HTTPS 不变；路径 B = `OCTOP_DEVICE_SERVER`（+ 可选过渡启动器）+ scoped insecure 白名单；回切只撤 env。删除「改常量 / 暂停 DEC-001」表述。对齐用户/总管确认与正在打的 Win+Linux Release。
