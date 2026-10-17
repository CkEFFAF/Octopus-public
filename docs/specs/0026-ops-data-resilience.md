# 0026 Ops-1：数据面韧性（备份异地 / 校验演练 / 保留归档 / 密钥与告警）

- Spec ID: `0026-ops-data-resilience`
- Status: **Ready**
- Revision: `2026-10-17.1`
- Date: 2026-10-17（Asia/Shanghai）
- Mode: ENHANCEMENT（Enhance 0009 / 既有 backup；**完全治理**，禁止「只热修日志」）
- Authoritative path: `docs/specs/0026-ops-data-resilience.md`
- Sibling: `0009-cloud-hub-production`（Accepted）、`0027-ops-host-runtime`、`0028-execution-isolation`、`0021`（轨迹 prune/coverage）、`0025`（勿推荐 default_open 挂云 MCP）
- Repository: `CkEFFAF/Octopus-public`
- Git 起点: `origin/main` @ `de5edcef3be4723e4a15e16ba33ad3b01108171e`
- 探测: `/workspace/0026-28-probe/PROBE-REPORT.md`
- 约束: **只规格**；不写生产代码、不直接改 VPS

---

## Goal

云管理端（及同构自托管 hub）在数据面达到可恢复、可审计、可告警的终态：

1. 备份 = **本地成功 + 异地副本 + 校验**；定期 **恢复演练**。
2. **单一数据面** `OCTOP_HOME`（生产规范路径 OctopData），禁止文档/脚本漂移到多根目录。
3. 主库与旁路库有 **retention / 归档 / VACUUM** 策略；history/audit 可查询且有 TTL。
4. 密钥与 JWT：**可轮换、可吊销**；日志 **禁止**明文 token/secret。
5. 最小告警：备份失败、异地失败、磁盘、DB 增速、非主动重启。

---

## Non-goals

- 不改 VPS、不在本切片直接部署。
- 不替代 0027（systemd/install）与 0028（隔离/egress）。
- 不把设备 ZDU（0017）当 hub 备份方案。
- 不静默删除轨迹/请求快照且标「完整」（对齐 0021 DEC-T12）。
- 不引入第二套备份产品绕开既有 `infra/backup/*`。

---

## DEC

| ID | 决议 |
| --- | --- |
| **DEC-B01** | **备份成功定义** = 本地 archive 完成 **且** 异地副本确认（对象存储或第二主机）。异地失败 = 备份失败（须告警）。 |
| **DEC-B02** | 每次备份写 **manifest**（路径、大小、UTC 时间、`sha256`、octop 版本、`OCTOP_HOME` 标识）；日检至少 **verify** 一份（hash + `tar -t`/清单一致）；周检可选隔离目录试 restore。 |
| **DEC-B03** | **演练 cadence**：月 ≥1 次 restore drill（记录 RTO/RPO 实测）；季 ≥1 次「空 `OCTOP_HOME` 拉起服务」全流程；结果进 audit。 |
| **DEC-B04** | **保留档**：本地 auto **N=14**；异地温存 **≥30 天**（可配置至 90）；手工/导出备份不计入 auto prune。 |
| **DEC-B05** | **单一数据面**：生产唯一根 = `OCTOP_HOME`，规范值为服务用户下的 **`~/OctopData` 或 `/var/lib/octop`**（与 0027 服务用户一致后写死一种）；代码默认 `~/.octop` 仅开发；Docker `OCTOP_DATA` **仅挂载别名**，语义=同一 `OCTOP_HOME`。禁止双开同 home（既有锁保留）。 |
| **DEC-B06** | **DB retention**：分对象 TTL —— 审计日志 / 会话附属 / 轨迹与 request_snapshot / 临时导出；归档先 **冷副本再删热**；删热须 `retention_gap`/`reason_codes`（对齐 0021）；SQLite 定期 **VACUUM**/incremental；PG 用官方 vacuum/analyze 节奏。 |
| **DEC-B07** | **JWT/密钥**：保留 `rotate-jwt-secret`（全局作废）；S1 增加 **token_version 或 denylist**（按用户/会话吊销）；`jwt_secret` 仅文件权限 0600 + 服务用户可读。 |
| **DEC-B08** | **日志禁 token**：扩展现有 `log_redaction` —— 覆盖 Authorization/Bearer、query token、`jwt_secret`、连接器 headers；结构化日志字段白名单；违规测试必挂。 |
| **DEC-B09** | **告警最小集**（webhook/邮件/IM 任一通道即可）：① backup/异地失败 ② 磁盘可用 <15%（可配）③ DB 日增长 >阈值 ④ systemd 重启且非 `systemctl`/upgrade 脚本发起（见 0027 联动）。失败不可仅 `logger.exception`。 |
| **DEC-B10** | Enhance 既有 `api/routers/backup.py` + `infra/backup/*` + CLI；异地为 **pluggable sink**（S3 兼容 / rsync / 自定义 hook），非平行备份子系统。 |

---

## 现状摘要

- 本地 auto backup + `retention_count`（默认 7）**有**；存 `OCTOP_HOME/backups/`。
- 异地 / checksum 流水线 / 演练 cadence / hub 告警 **缺**。
- `OCTOP_HOME` 机制有；云约定 `~/OctopData` 与默认 `~/.octop`、Docker `OCTOP_DATA` 未统一文档。
- Audit 有；主库产品级 retention/VACUUM **无**；memory VACUUM / trajectory 碎片能力旁证。
- JWT rotate 有；细粒度吊销弱；query token redact 有、未全局策略化。

---

## 数据与接口契约（摘要）

### BackupManifest

```text
manifest_version, backup_id, created_at, octop_version,
octop_home_fingerprint, files[{path, size, sha256}],
offsite[{sink, uri_or_label, status, verified_at?}],
verify_status: pending|ok|failed
```

### OffsiteSink（配置）

```text
type: s3_compatible | rsync | hook
# s3: endpoint, bucket, prefix, creds via env/secret file
# rsync: target host:path, ssh key
# hook: argv template; exit 0 = success
```

### RetentionPolicy（配置JSON，存 OCTOP_HOME）

```text
local_auto_count: 14
offsite_days: 30
audit_days, trajectory_policy_ref, history_archive_days, vacuum_cron
```

---

## 需求与验收

| ID | 需求 |
| --- | --- |
| **REQ-B01** | 自动/手工备份产出 manifest+sha256，并尝试异地；失败告警。 |
| **REQ-B02** | 提供 verify 与 restore drill runbook/命令；演练结果可审计。 |
| **REQ-B03** | 生产文档与 unit 只承认单一 `OCTOP_HOME` 规范路径。 |
| **REQ-B04** | 可配置 retention；执行归档/VACUUM 有日志与 gap 标记。 |
| **REQ-B05** | JWT 轮换可用；日志无明文 token/secret（测试覆盖）。 |
| **REQ-B06** | 告警通道可配置；四类事件至少能打通一条通道。 |

| ID | AC |
| --- | --- |
| **AC-B01** | Given 异地 sink 配置正确；When 跑 auto backup；Then 本地+异地均成功且 manifest.offsite.status=ok。 |
| **AC-B02** | Given 异地不可达；When backup；Then 整体失败/降级为 failed 并触发告警（不可标成功）。 |
| **AC-B03** | Given 一份备份；When verify；Then hash 与清单一致返回 ok。 |
| **AC-B04** | Given drill 脚本；When 在隔离目录 restore；Then 服务可按 runbook 拉起（或 dry-run 明确列出缺口）。 |
| **AC-B05** | Given 日志含 Bearer；When 写 access/app log；Then 落盘为 redact 形态。 |
| **AC-B06** | Given 磁盘 <阈值；When 巡检 job；Then 告警发出。 |

---

## 实施切分

| 切片 | 范围 | 必过 |
| --- | --- | --- |
| **S0** | manifest+sha256；offsite hook/rsync 或 S3 其一；失败告警 webhook；verify CLI；drill runbook；本地 retention 默认改 14；文档统一 OctopData | AC-B01–B03、B05（日志至少扩一类）、B06 骨架 |
| **S1** | 主库/审计/轨迹 retention job + VACUUM；JWT denylist/version；DB 增速告警；季演练清单自动化 | AC-B04 强化、REQ-B04 |
| **S2** | 多 sink、仪表盘备份健康、非主动重启联动 0027 | — |

建议实施顺序（跨规格）：**0027 S0 → 本规格 S0 → 0028 S0**。

---

## Coder brief

```text
规格: docs/specs/0026-ops-data-resilience.md（Rev 2026-10-17.1）
Enhance: src/octop/infra/backup/*, api/routers/backup.py, cli/commands/backup.py, log_redaction.py
不要: 平行备份产品；静默删轨迹无 gap；改 VPS；占用 0025 迁移号
S0 先: manifest + offsite sink + alert webhook + verify
与 0025: 运维文案禁止教用户用 default_open 挂云 MCP
```

---

## 与 0025 协同

无直接冲突。运维/告警文档勿把账号 `default_open` 写成设备授权替代方案。

---

## Evolution

| Rev | 变更 |
| --- | --- |
| `2026-10-17.1` | 首版 Ready（完全治理 Ops-1）。 |
