# 0006 执行端首次启动向导（UU 式开箱接入）

- Spec ID: `0006-device-first-run-launcher`
- Status: **Draft**（待总管/用户确认后可升 Proposed/Accepted）
- Revision: `2026-10-12.1`
- Date: 2026-10-12
- Authoritative path: `docs/specs/0006-device-first-run-launcher.md`
- Relates: `0004-same-account-auto-enroll.md`（Accepted，先登记后配置）、`0005-device-permission-management.md`（尤其 REQ-006 便携 Release、REQ-008 稳定入口）、`REQ-008`、`docs/octopus/same-account-enroll-ops.md`、`desktop/portable/*`
- Non-overwrite: **不修改** Accepted `0004` 决策正文；不改 enroll API/安全边界；本规格只补「开箱 UX / 启动器 / 首次向导」缺口
- Deploy context（非硬编码强制）: 云中枢 4C8G Ubuntu24 部署中；产品默认公网入口域名为 `https://octop.effaf.me`（Tunnel/DNS 指向可变，执行端只记域名）

## Problem

0004 已定义「同账号登录 → 自动 enroll」；0005 已定义便携包与稳定域名入口。但执行端开箱路径仍以 **CLI** 为主：

- `octop device connect --server … --username …` / `setup-device.bat`
- 文档示例要求用户手填 `--server`，默认域名未产品化进启动 UI
- 便携包 `open.bat` 偏「全功能管理端」；设备端首次接入缺少 **UU 式**：安装/打开 → 账号密码（或已登录态）→ 自动进设备网

缺口 = **启动器 / 首次向导**，不是重新设计登记协议。

## Goals

1. 执行端（笔记本 / GPU 等）安装或解压便携包后，**双击打开**即可进入首次向导（少 CLI）。
2. 默认 server = `https://octop.effaf.me`（可配置/可覆盖）；用户多数情况只需账号密码。
3. 已有有效登录态时 **跳过登录页**，直接走 0004 自动登记（或检测已 enroll 则进主界面）。
4. 登记成功后进入设备端主界面；名称 / roots / 细权限 **事后**按 0004「先登记后配置」+ 0005 REQ-007/权限 UI。
5. CLI（`device connect` / `setup-device`）保留为高级/脚本路径，**不删除**。

## Non-goals

- 不改 0004 enroll 凭证规则（用户 JWT；key-session 拒绝；密码不落盘 device-state）。
- 不在向导内强制做权限/共享目录配置（可提供「稍后」入口）。
- 不实现 Cloudflare Tunnel 全自动安装（仍属 0005 REQ-008 运维侧）。
- 不把云主机公网 IP 写死为产品默认（仅域名；IP 仅运维上下文）。
- 不做手机原生执行端；不做多账号并行登录 UX（P1+）。
- 本规格 **不含业务代码实现**（仅 SDD）。

## Requirements

### REQ-001 — 默认 server 与可覆盖

- Requirement: 首次向导与便携包默认 `server_url = https://octop.effaf.me`。允许用户在向导「高级/改 server」中覆盖；允许环境变量 / CLI `--server` 覆盖同一配置键。
- 落盘：与现有约定一致——成功后写入设备本地状态（便携包常用包内 `device-state/`；非便携默认 `~/.octop-device` 或 `--state` / `OCTOP_HOME` 所指路径）。**只持久化 server URL + `odv_` 等设备凭证字段**；账号密码 / JWT **不**写入 device-state（沿用 0004）。
- AC-001: 干净环境首次打开，向导预填 `https://octop.effaf.me`，用户不改即可继续。
- AC-002: 用户改为其他 `https://…` 并成功登记后，再次启动复用已存 server，不再回退错域名。
- AC-003: CLI `octop device connect --server <url> …` 仍可用，并写入同一状态 schema。

### REQ-002 — 首次向导主流程（UU 式）

- Requirement: 设备端启动器检测到「未完成首次接入」时进入向导，步骤固定为：

  1. **打开**（`open.bat` / 设备端入口 / 等价启动器）
  2. **可选改 server**（默认已填产品域名；折叠在「高级」以免打扰）
  3. **登录**：账号密码；若本地已有可用账号登录态则 **跳过**
  4. **自动登记**：调用 0004 账号会话 enroll（`POST /devices/enroll` + Bearer）
  5. **成功 → 主界面**（设备在线）；显示名 / permissions / roots 事后配置（0004 + 0005）

- AC-004: Given 未 enroll 且无登录态，When 输入正确账号密码，Then 自动 enroll 成功并进入主界面，Dashboard 同账号可见新设备。
- AC-005: Given 已有有效登录态且未 enroll，When 打开客户端，Then 不展示密码框，直接 enroll（失败则回登录/错误页）。
- AC-006: Given 本地已有有效 `device-state`（已 enroll），When 打开，Then **跳过向导**，直接连接/主界面（等价现有 `start-device` 无参恢复）。
- AC-007: 浏览器管理页登录 **不得** 静默把本机登记为执行设备（保持 0004 AE-02 / AC-02 精神）。

### REQ-003 — 向导优先，CLI 仍可用

- Requirement: 产品文档与便携 README 的 **主路径**改为向导；CLI 标为「高级 / 自动化 / 无 GUI」。
- AC-008: README 开箱步骤以「双击 → 登录 → 完成」为主；`--server` CLI 示例保留在「高级」附录。
- AC-009: `setup-device.bat` / `octop device connect` 行为不回退、不删除；与向导写同一 device-state。

### REQ-004 — 与 0005 便携 Release 衔接

- Requirement: Win 便携 zip（`Octop-portable-windows-amd64-*.zip`）解压后，用户双击的主入口（`open.bat` 或新增明确的设备入口，如 `start-device.bat` 首次形态）在 **device-only / 首次未登记** 场景下进入本向导，而非要求先开终端。
- 说明：若当前 `open.bat` 固定拉起全功能管理端，则 MVP 允许：(a) 为执行端提供独立入口脚本/快捷方式「接入设备网」，或 (b) `open.bat` 在无本地管理端 home / 无 device-state 时分支进设备向导——实现二选一，**DEC-002**。
- AC-010: 洁净 Win 机解压便携包，不预装 uv/Node，按 README 双击主入口，可完成「默认域名 + 账号密码 → 登记」。
- AC-011: 便携 README / 开箱说明默认示例使用 `https://octop.effaf.me`，不把内网 IP 当正式路径（呼应 0005 AC-022）。

### REQ-005 — 错误与安全提示（最小）

- Requirement: 向导对失败给出可读原因：网络/域名不可达、账号错误、HTTPS 证书问题、服务端拒绝 enroll。默认 **不允许** UI 一键开启 `--allow-insecure`（可藏在高级，且需二次确认）；正式路径为 0005 Tunnel HTTPS。
- AC-012: 错误密码不写 device-state；不留下半残 odv_。
- AC-013: 成功路径全程无 `--allow-insecure`。

## 首次向导流程（示意）

```
[双击启动器]
    │
    ├─ 已有有效 device-state？ ──是──► 连接 / 主界面（跳过向导）
    │
    └─ 否 ──► 向导
              ├─ Server（默认 https://octop.effaf.me，可改）
              ├─ 已登录态？ ──是──► 跳过登录
              │              └─否──► 账号 + 密码
              ├─ 0004 自动 enroll（Bearer JWT）
              ├─ 写 device-state（server + odv_ …）
              └─ 主界面（名称/权限/roots → 事后，0004/0005）
```

## Decisions

| ID | 决策 | State |
|---|---|---|
| DEC-001 | 产品默认 server = `https://octop.effaf.me`（可覆盖）；不把云主机 IP 当默认 | **resolved**（总管产品目标） |
| DEC-002 | 便携包主入口如何进入向导：独立「设备接入」入口 **或** `open.bat` 分支；Coder 实现时择一，README 只宣传一条主路径 | **open**（不阻塞规格；阻塞的是实现选型） |
| DEC-003 | 向导为 MVP 主路径；CLI 保留 | **resolved** |
| DEC-004 | 首次向导不强制配置 roots/细权限；沿用 0004 先登记后配置 + 0005 默认 permissions | **resolved** |
| DEC-005 | 密码：UI 输入；不写 device-state；自动化继续用 `--account-token`（0004 ops） | **resolved** |

## Open Questions（尽量少）

| ID | 问题 | State |
|---|---|---|
| OQ-001 | 全功能管理端与纯执行端是否共用同一 `open.bat` 二进制入口 | **open** → 见 DEC-002；产品上执行端开箱只暴露一条路径即可 |
| OQ-002 | Linux 无 GUI 设备是否提供 TUI/文本向导 | **deferred**：MVP 以 Win 便携 GUI + 现有 CLI 为准；Linux 继续 `setup-device.sh` |

## MVP / Coder 任务清单（短）

1. 设备端首次向导 UI（server 预填、登录、进度、错误）；复用 0004 enroll 客户端 API，不新造协议。
2. 启动器：未 enroll → 向导；已 enroll → 直接跑（对齐 `start-device`）。
3. 默认值：`https://octop.effaf.me` 写入客户端默认配置/常量（可被 UI/CLI/环境覆盖）。
4. 便携包：主入口接线 + README 开箱改「双击登录」；CLI 示例移到高级。
5. 测试：AC-001/004/005/006 自动化或清单；洁净 Win 开箱手测 AC-010。
6. 文档：`same-account-enroll-ops.md` / deploy 增加「向导主路径」一段，注明 CLI 仍可用；**不改** 0004 Accepted 正文。

## Out of scope for Coder（本规格）

- 改 0004 正文；实现 Tunnel；改默认权限矩阵（0005 REQ-007）；业务功能代码以外的 git commit 策略由总管定（本执行员不 commit）。

## Evolution

- 2026-10-12.1: 初稿。对照 0004/0005 缺口补齐 UU 式启动器/首次向导；默认域名 `https://octop.effaf.me`；向导优先、CLI 保留；衔接便携 Release 与 REQ-008。
- 2026-10-12.1-impl: Coder MVP — DEFAULT_DEVICE_SERVER=https://octop.effaf.me; `device join` UU path; `device first-run` + `open-device.bat/.sh`; CLI retained; advanced join/setup kept.
