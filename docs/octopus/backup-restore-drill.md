# 备份校验与恢复演练（0026 Ops-1）

- 对齐规格：`docs/specs/0026-ops-data-resilience.md`（Ready / rev `2026-10-17.1`）
- 切片：S0 — manifest+sha256、异地 hook/rsync、失败 webhook、verify CLI、本 runbook
- 更新：2026-10-17（Asia/Shanghai）

## 单一数据面

生产唯一根 = 环境变量 **`OCTOP_HOME`**。

| 环境 | 规范路径 |
|------|----------|
| 云中枢 / 自托管 hub | 服务用户下的 **`~/OctopData`**（例：`/home/octop/OctopData`）或 **`/var/lib/octop`**（与 0027 服务用户一致后写死一种） |
| 本地开发 | 默认 `~/.octop`（未设 `OCTOP_HOME`） |
| Docker | `OCTOP_DATA` **仅挂载别名**，语义 = 同一 `OCTOP_HOME` |

禁止双开同一 `OCTOP_HOME`。运维文案**不要**用账号 `default_open` 当作设备 MCP 授权替代方案（见 0025）。

## 备份成功定义（DEC-B01）

本地 archive **且**（若配置了异地）异地副本确认。异地失败 = **整体失败**，并走告警 webhook。

每次成功写入会在 `backups/` 旁落 **`<archive>.integrity.json`**（sha256、offsite、verify_status）。

## 配置（`config.json` → `backup`）

```json
{
  "backup": {
    "auto_enabled": true,
    "schedule": "cron:0 4 * * *",
    "retention_count": 14,
    "alert_webhook_url": "https://hooks.example/octop",
    "disk_free_percent_min": 15,
    "offsite": {
      "enabled": true,
      "type": "hook",
      "hook_argv": ["scp", "{archive}", "{integrity}", "backup@offsite:/var/backups/octop/"],
      "rsync_target": "",
      "rsync_extra_args": []
    }
  }
}
```

环境变量覆盖（节选）：`OCTOP_BACKUP_RETENTION_COUNT`、`OCTOP_BACKUP_ALERT_WEBHOOK_URL`、`OCTOP_BACKUP_OFFSITE_ENABLED`、`OCTOP_BACKUP_OFFSITE_TYPE`、`OCTOP_BACKUP_OFFSITE_HOOK`（JSON 数组或 shell 分词）、`OCTOP_BACKUP_OFFSITE_RSYNC_TARGET`、`OCTOP_BACKUP_DISK_FREE_PERCENT_MIN`。

S0 异地类型：`hook`（exit 0 = 成功）或 `rsync`。`s3_compatible` 留待后续切片。

## 日常命令

```bash
# 自动备份一次（含 integrity + 异地 + verify）
octop backup auto run --home "$OCTOP_HOME"

# 校验一份备份（hash + tar 列表）
octop backup verify "$OCTOP_HOME/backups/octop-auto-backup-….tar.gz"

# 磁盘阈值巡检（AC-B06 骨架）
octop backup health-check --home "$OCTOP_HOME"

# 演练步骤（dry-run，不执行 restore）
octop backup drill --dry-run --home "$OCTOP_HOME"
```

## 月度恢复演练（≥1）

1. `octop backup verify <archive>` 必须 ok。
2. `systemctl stop octop-hub`（或等价）；**禁止**对热库直接 restore。
3. 隔离目录 restore：

```bash
DRILL=/tmp/octop-drill-$(date +%Y%m%d)
mkdir -p "$DRILL"
OCTOP_HOME="$DRILL" octop backup restore /path/to/archive.tar.gz --yes
# 可选：短时前台拉起并 curl /api/health
```

4. 记录实测 RTO/RPO、结果进 audit / 运维笔记；删除 `$DRILL`。
5. 季度：空 `OCTOP_HOME` + 0027 `install-hub` / `upgrade-hub` 全流程（见 `docs/octopus/cloud-hub-ops.md`）。

## 告警最小集（S0）

Webhook JSON：`kind` ∈ `backup_failed` | `offsite_failed` | `disk_low`（另预留 `db_growth` / `unexpected_restart`）。未配置 URL 时至少 ERROR 日志，不可静默吞掉。
