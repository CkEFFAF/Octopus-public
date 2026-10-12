# 0009 云中枢生产切片（Ubuntu 24）

- Spec ID: `0009-cloud-hub-production`
- Status: **Accepted**（OQ-001..004 已关闭；Coder 已派）
- Revision: `2026-10-12.3`
- Date: 2026-10-12
- Authoritative path: `docs/specs/0009-cloud-hub-production.md`
- Relates:
  - `docs/octopus/cloud-hub-ops.md`（短运维清单；本规格定验收与边界，ops 定可执行命令）
  - `docs/octopus/cloudflare-tunnel-entry.md`（稳定入口 / Tunnel）
  - `0005` REQ-008 / `0006` 默认 `https://octop.effaf.me` / `0007` 开箱包默认 server
  - `0003-workstation-migration.md`（迁云只改入口指向）
- Non-overwrite: **不修改** Accepted `0004`；不改 enroll 协议；不改开箱包默认把公网 IP 写死。本任务定规格 + ops 脚本/单元；业务代码不改。S1+S2 由 Coder 规范提交（总管派工）。

## Problem

云主机 **4C8G Ubuntu 24 @ `111.228.42.228`** 将作为唯一（或主）管理端。需要可交接的生产切片：如何 clone、如何常驻、如何暴露入口、设备如何改连，且与已有 Tunnel/域名策略一致。现有 `cloud-hub-ops.md` 给短命令；本规格给边界、REQ/AC、Coder 切片与必须用户拍板的 OQ。

## Goals

1. 云机可重复部署：Deploy Key clone → `uv sync` → 构建前端 → `octop run 0.0.0.0:8188`（或 loopback + 反代/Tunnel）。
2. 常驻：`systemd` 单元，崩溃可拉起；日志可查。
3. 入口：本里程碑先 **HTTP IP** `http://111.228.42.228:8188`（DEC-005）；正式产品入口仍为 `https://octop.effaf.me`（拓扑 A 后续）。
4. 设备改连文档与 0006/0007 默认域名一致；IP 仅 ops 附录。
5. 安全组最小集：22 / 8188（及 443 若上反代）。

## Non-goals

- 不做管理端多活 / 自动选举（属 0008 之外的基础设施）。
- 不做全自动 Cloudflare Tunnel 安装器（宿主机运维手工配）。
- 不把手机做成执行端；不改 0008 桌面交接语义。
- 不在本规格内打 GitHub Release（见 0007 收尾）。
- 不提交 Deploy Key、云厂商密钥、账号密码到 Git。

## 入口策略（两种合法拓扑）

| 拓扑 | 设备 `--server` | 云机监听 | 适用 |
|------|-----------------|----------|------|
| **A. CF Tunnel + 域名（推荐生产）** | `https://octop.effaf.me` | 建议 `127.0.0.1:8188`，Tunnel 源站 | 正式；免公网裸 HTTP |
| **B. MVP HTTP IP** | `http://111.228.42.228:8188` + `--allow-insecure` | `0.0.0.0:8188` | 联调/未配 Tunnel 前 |

产品默认与开箱包 **只认拓扑 A 的域名**。拓扑 B 仅 ops/手测。

## Requirements and acceptance

### REQ-001 — 源码落地（Deploy Key）

- Requirement: 云机用 GitHub **只读 Deploy Key**（或同等只读凭据）clone `CkEFFAF/Octopus`；私钥仅存云机 `~/.ssh/`，不入仓库、不入开箱包。
- AC-001: 新机按 `cloud-hub-ops.md` 可 clone 到约定目录且 `git remote -v` 指向 `CkEFFAF/Octopus`。
- AC-002: 仓库内无 Deploy Key / Token 明文。

### REQ-002 — 运行与健康检查

- Requirement: 依赖 `uv sync`（及 Dashboard `npm ci && npm run build` 若从源码起）；`octop run --host 0.0.0.0 --port 8188`（或 `OCTOP_HOME` / `OCTOP_BIND_HOST` / `OCTOP_PORT`）后 `/api/health` 返回成功。
- AC-003: 本机 `curl -sS http://127.0.0.1:8188/api/health` 成功。
- AC-004: 安全组放行后，运维 IP 可访问管理端（HTTP IP 或 HTTPS 域名，取决于已选拓扑）。

### REQ-003 — systemd 常驻

- Requirement: 提供 `octop-hub.service`（名称可微调）；`enable --now`；`Restart=on-failure`；WorkingDirectory 指向仓库；`OCTOP_HOME` 指向稳定数据目录。
- AC-005: reboot 或 `systemctl restart octop-hub` 后服务 active，健康检查仍通过。
- AC-006: `journalctl -u octop-hub` 可看到启动日志（无密钥明文）。

### REQ-004 — 入口与设备改连

- Requirement: 文档同时写清域名正式路径与 IP 临时路径；开箱包/向导默认仍为 `https://octop.effaf.me`（0006/0007）。
- AC-007: `cloud-hub-ops.md` 含设备改连示例（域名 / IP+insecure）。
- AC-008: 抽查 0007 产物 README / 向导默认 **不含** `111.228.42.228`。

### REQ-005 — 网络安全最小集

- Requirement: 云安全组 + 主机防火墙开放 22、8188；若上 443/反代则按实开。SSH 密钥登录优先。
- AC-009: 文档列出端口表；未使用的管理端口不默认全网开放（若运维收紧，记入 ops）。

### REQ-006 — HTTPS / Tunnel（生产路径）

- Requirement: 选拓扑 A 时，按 `cloudflare-tunnel-entry.md` 将 `octop.effaf.me` 指到云机源站；`/api/` 与设备 WS `/api/devices/connect/ws` 同域可达。
- AC-010: 浏览器打开 `https://octop.effaf.me` 可达管理端；设备用域名 enroll **无需** `--allow-insecure`。
- AC-011: 换机时只改 Tunnel 源站，设备域名配置不变。

## Decisions

| ID | 决策 | State |
|----|------|-------|
| DEC-001 | 正式产品入口 = `https://octop.effaf.me`；公网 IP 仅 ops 临时 | **resolved**（对齐 0005/0006/0007） |
| DEC-002 | 常驻方式 = **systemd 系统单元**（`/etc/systemd/system/octop-hub.service`；非 screen/tmux；非用户级 `--user` 作为本里程碑主路径） | **resolved**（原 OQ-002） |
| DEC-003 | 代码来源 = `CkEFFAF/Octopus` + 只读 Deploy Key | **resolved**（建议） |
| DEC-004 | 本切片 **可独立** 于 0008 PR #4 / 0007 真包；不阻塞 | **resolved** |
| DEC-005 | 本周入口拓扑 = **先拓扑 B（HTTP IP）** `http://111.228.42.228:8188`；正式产品默认仍为域名 HTTPS（拓扑 A 后续） | **resolved**（原 OQ-001） |
| DEC-006 | 数据目录 = **`~/OctopData`**（展开为 `/home/<user>/OctopData`，例 `/home/ubuntu/OctopData`）；启动用环境变量 **`OCTOP_HOME`** 指向该路径（`octop run` 无 `--home` CLI；root 云机例 `/root/OctopData`） | **resolved**（原 OQ-003） |
| DEC-007 | 本里程碑云机 **只保证管理端**；不同时保证本机设备客户端 | **resolved**（原 OQ-004） |
| DEC-008 | systemd = **系统单元**（User=ubuntu 或实机部署用户） | **resolved**（同 DEC-002 / OQ-002） |

## Open Questions（已关闭）

| ID | 问题 | 决议 | State |
|----|------|------|-------|
| OQ-001 | 本周上线先拓扑 A（Tunnel+HTTPS）还是先拓扑 B（HTTP IP）？ | **先拓扑 B（HTTP IP）** `http://111.228.42.228:8188`；开箱/产品默认仍域名；尽快补 A | **resolved** 2026-10-12 |
| OQ-002 | systemd 用系统单元还是用户级 `--user` + linger？ | **系统单元**（与 ops 示例一致） | **resolved** 2026-10-12 |
| OQ-003 | 数据目录路径？ | **`~/OctopData`**（root=`/root/OctopData`，ubuntu=`/home/ubuntu/OctopData`；机制=`OCTOP_HOME`） | **resolved** 2026-10-12 |
| OQ-004 | 云机是否同时跑管理端 + 本机设备客户端？ | **本里程碑只保证管理端**；设备客户端可选另开 | **resolved** 2026-10-12 |

## OQ resolutions (manager 2026-10-12)

- **OQ-001**: 先 **HTTP IP**（`http://111.228.42.228:8188`）；设备手测可 `--allow-insecure`；开箱默认仍 `https://octop.effaf.me`。
- **OQ-002**: **systemd 系统单元**。
- **OQ-003**: 数据目录 **`~/OctopData`**（`OCTOP_HOME`；root=`/root/OctopData`）。
- **OQ-004**: **只管理端**；本里程碑不保证云机上的设备客户端。


## Coder / 运维实现指南

### 可写路径

- `docs/octopus/cloud-hub-ops.md`（短清单；可随实机路径微调）
- `ops/cloud-hub/`（install/smoke 脚本、systemd 模板与示例单元）
- 可选：`tests/unit/test_cloud_hub_0009.py`（静态门禁）
- 可选：`docs/octopus/cloudflare-tunnel-entry.md` 增补「源站=云机」一段
- **禁止**：改 Accepted 0004；把 IP 写入 `desktop/portable` 默认 server；提交密钥

### 切片

| 片 | 产出 | 验收 |
|----|------|------|
| **S1** | 安全组 22/8188 + SSH 登录 + Deploy Key clone + `uv sync` + 前台 `octop run` | AC-001..004 |
| **S2** | systemd 单元 enable；reboot 抽测 | AC-005..006 |
| **S3** | 设备改连（临时 IP 或域名）enroll 一只 Win/Linux | AC-007..008；对齐 0004 |
| **S4** |（若 OQ-001=A）Tunnel 指云机；关掉公网裸 8188 或收紧安全组 | AC-010..011 |

**建议先做 S1+S2**（可与 0007 真包并行）。S3 依赖至少一台执行端；S4 依赖用户 Cloudflare 凭据。

### 风险

| 风险 | 缓解 |
|------|------|
| 裸 HTTP 泄露登录材料 | B 仅短窗；尽快 A；审计后轮换密钥 |
| Deploy Key 泄露 | 只读、单仓库、可轮换；禁进 Git |
| 数据目录被第二次实例写坏 | 单实例 + 稳定 `OCTOP_HOME`；文档禁止双开 |
| 与工位旧管理端双主 | 明确「云=主」后停工位管理端或只作设备 |

## Evolution

- 2026-10-12.1: 初稿 Draft；对齐新建/补齐的 `cloud-hub-ops.md`；可独立派运维/Coder。
- 2026-10-12.2: OQ-001..004 全部关闭（用户/总管转达）：先 HTTP IP；systemd 系统单元；`~/OctopData`；只管理端。Status → **Accepted**；写入 DEC-005..008。轻触 `cloud-hub-ops.md` 对齐。REQ/AC ID 未改号。未改业务代码、未 git commit。
- 2026-10-12.3: Coder S1+S2：`ops/cloud-hub/` 系统单元模板 + install/smoke；ops/规格对齐 `OCTOP_HOME`（纠正 `--home`）；Tunnel 文档增补云机源站；静态测试。未做 S3/S4；未在云机执行破坏性操作；未 push/PR。
