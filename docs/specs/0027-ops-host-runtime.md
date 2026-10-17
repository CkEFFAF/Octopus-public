# 0027 Ops-2：主机运行时与发布（systemd 真相源 / 非 root / install·upgrade·rollback）

- Spec ID: `0027-ops-host-runtime`
- Status: **Ready**
- Revision: `2026-10-17.1`
- Date: 2026-10-17（Asia/Shanghai）
- Mode: ENHANCEMENT（Enhance 0009 + `ops/cloud-hub/*`；**完全治理**）
- Authoritative path: `docs/specs/0027-ops-host-runtime.md`
- Sibling: `0009-cloud-hub-production`（Accepted，本规格升级其生产默认）、`0026-ops-data-resilience`、`0028-execution-isolation`、`0017`（设备 ZDU ≠ hub）
- Repository: `CkEFFAF/Octopus-public`
- Git 起点: `origin/main` @ `de5edcef3be4723e4a15e16ba33ad3b01108171e`
- 探测: `/workspace/0026-28-probe/PROBE-REPORT.md`
- 约束: **只规格**；不写生产代码、不直接改 VPS

---

## Goal

云 hub 主机面单一、可回滚、默认可安全：

1. **systemd 单一真相源**：单元 + **唯一**高优先级 drop-in；无残留 ExecStart 冲突。
2. 生产默认 **绑定 `127.0.0.1`**；公网仅 Tunnel/反代。
3. **非 root** 服务用户运行。
4. 正式 **install / upgrade / rollback**，保留 **N=3** 版本；替代手工脚本堆。
5. 生产 runtime **锁定依赖**；禁裸手改 venv；MCP 随发布锁（中期制品化）。
6. **SSH/ufw** 硬化清单可执行；**访问日志**有规范（Tunnel 与/或 Caddy）。

---

## Non-goals

- 不现场改 VPS（规格落地后由运维/Coder 另派执行）。
- 不把 0017 设备 ZDU 当作 hub 升级方案。
- 不强制 Caddy 为唯一边缘（现网可为 Cloudflare Tunnel；Caddy 为可选并列）。
- 不在 S0 完成完整「自带 mcp 二进制制品」——S0 先冻结 `uv sync --frozen` + 禁手改。

---

## DEC

| ID | 决议 |
| --- | --- |
| **DEC-S01** | **真相源**：只承认 `/etc/systemd/system/octop-hub.service` + `/etc/systemd/system/octop-hub.service.d/90-octop.conf`。install/upgrade **删除或归档** `50-*` 等低优先级残留；禁止双 `ExecStart=` 打架。 |
| **DEC-S02** | 生产 **`OCTOP_BIND_HOST=127.0.0.1`** 为默认；`0.0.0.0` 必须显式 `--allow-public-bind`（或等价 env）并写警告。入口走 CF Tunnel / 反代（0009 拓扑 A）。 |
| **DEC-S03** | **强制非 root**：服务用户 `octop`（或 `ubuntu` 过渡）；`User=`/`Group=` 必填；root 示例降级为 bootstrap-only，文档主路径不再是 root。 |
| **DEC-S04** | 正式脚本三联：`install-hub` / `upgrade-hub` / `rollback-hub`（在 `ops/cloud-hub/`）。upgrade：拉版本 → health → 失败自动 rollback；保留 **N=3** 已安装树或 git+lock 摘要目录。 |
| **DEC-S05** | Runtime：**禁生产手改** `.venv`/site-packages；S0=`uv sync --frozen` + 锁文件入发布记录；S1+ 发布制品（含锁定 MCP/连接器依赖），「禁临时 venv 漂移」写入验收。 |
| **DEC-S06** | SSH：密钥登录、禁密码、限制 Root；ufw：22（建议运维 IP）、443（若反代本机）、**8188 不对公网**（仅 loopback）。 |
| **DEC-S07** | Access log：① 应用 uvicorn（已有 redact，对齐 0026）；② Tunnel/源站日志保留策略；③ 若部署 Caddy，必须 `access_log` 路径与轮转——**不硬绑 Caddy 为唯一边缘**。 |
| **DEC-S08** | 与 0026：`OCTOP_HOME` 指向服务用户 OctopData；upgrade 不得改丢数据面。 |
| **DEC-S09** | 非主动重启：unit 设 `Restart=`；0026 告警识别「非 systemctl/upgrade 发起的重启」（journal 关联）。 |

---

## 现状摘要

- `ops/cloud-hub/install-hub.sh` + service 模板 **有**；默认 **`0.0.0.0`**；root 示例仍主路径之一。
- 实机曾出现 **50-* drop-in 盖过** 新单元（需 90-*）——须规格化。
- Hub **无**对称 upgrade/rollback/版本 N；现状 `uv run` 源码树。
- ufw/SSH 仅原则；Caddy **无**；入口文档为 Tunnel。

---

## 需求与验收

| ID | 需求 |
| --- | --- |
| **REQ-S01** | install 写出单一 unit+90 drop-in，默认 loopback + 非 root + OCTOP_HOME。 |
| **REQ-S02** | upgrade/rollback 可重复执行；保留 N=3；health 失败回滚。 |
| **REQ-S03** | 文档与脚本禁止默认公网 bind；8188 不对公网。 |
| **REQ-S04** | SSH/ufw 清单可勾选验收；access log 策略成文。 |
| **REQ-S05** | 生产依赖变更只经 upgrade 路径，不经手改 venv。 |

| ID | AC |
| --- | --- |
| **AC-S01** | Given 新装；When install-hub；Then bind=127.0.0.1、User≠root、仅 90-octop drop-in 含 ExecStart 覆盖。 |
| **AC-S02** | Given 残留 50-*；When upgrade；Then 残留被清理或不再覆盖 90。 |
| **AC-S03** | Given 坏版本；When upgrade health 失败；Then 自动 rollback 到上一好版本。 |
| **AC-S04** | Given ufw 清单；When 审计；Then 公网无 8188。 |
| **AC-S05** | Given 无 `--allow-public-bind`；When 配置 0.0.0.0；Then install/upgrade 拒绝或强警告并非默认。 |

---

## 实施切分

| 切片 | 范围 | 必过 |
| --- | --- | --- |
| **S0** | 改模板/install 默认 loopback+非 root；90 drop-in 合并与清理 50-*；upgrade/rollback 骨架；SSH/ufw 清单；更新 0009 交叉说明 | AC-S01、S02、S04、S05 |
| **S1** | health 门禁自动 rollback；版本 N=3 目录；frozen sync 强制；journal 重启告警联动 0026 | AC-S03 |
| **S2** | 发布制品 + 自带锁定 MCP；可选 Caddyfile access_log | REQ-S05 强化 |

**跨规格建议最先做本规格 S0**（降爆破面）。

---

## Coder brief

```text
规格: docs/specs/0027-ops-host-runtime.md（Rev 2026-10-17.1）
改: ops/cloud-hub/*、docs/octopus/cloud-hub-ops.md、交叉修订 0009 生产默认说明（不覆盖 Accepted 正文可加 Errata/本规格为准）
不要: 现场 SSH 改 VPS；把设备 0017 当 hub 升级；默认 0.0.0.0
S0: loopback + non-root + 90 drop-in + upgrade/rollback 骨架 + ufw/ssh 清单
```

---

## 与 0025 / 0009

- **0009**：本规格升级生产默认（bind/非 root/发布）；冲突处以 **本 Ready** 为准并回写 ops 清单。
- **0025**：无冲突。

---

## Evolution

| Rev | 变更 |
| --- | --- |
| `2026-10-17.1` | 首版 Ready（完全治理 Ops-2）。 |
