# 云中枢短运维清单（Ubuntu 24）

- 对齐规格：
  - **`docs/specs/0027-ops-host-runtime.md`**（Ready / rev `2026-10-17.1`）— **生产默认以本规格为准**（loopback、非 root、90 drop-in、install/upgrade/rollback）
  - `docs/specs/0009-cloud-hub-production.md`（Accepted / rev `2026-10-12.4`；见文末 Errata → 0027）
  - **`docs/specs/0026-ops-data-resilience.md`** — 数据面备份/异地/校验；演练见 `docs/octopus/backup-restore-drill.md`
- 主机：`111.228.42.228`（4C8G Ubuntu 24）；产品域名：`https://octop.effaf.me`
- 脚本：`ops/cloud-hub/`（`install-hub.sh` / `upgrade-hub.sh` / `rollback-hub.sh` / `smoke-hub.sh` / systemd + `90-octop` / `ssh-ufw-checklist.md`）
- 更新：2026-10-17（0027 S0：默认 `127.0.0.1` + 非 root + 正式升级骨架）

## 一句话目标

云机跑唯一管理端；设备（Win/Linux 开箱包）默认连 `https://octop.effaf.me`。  
**生产默认拓扑 A**：Hub 只听 **`127.0.0.1:8188`**，公网经 Cloudflare Tunnel / 反代。  
拓扑 B（HTTP IP `0.0.0.0:8188`）仅联调，须显式 `--allow-public-bind`，**禁止**写进产品/包内默认常量。

## 已拍板（0009 DEC + 0027 升级）

| 项 | 决议 |
|----|------|
| 生产拓扑 | **A：loopback + Tunnel**（0027 DEC-S02）；B 仅 `--allow-public-bind` |
| 常驻 | **systemd 系统单元** + **唯一**高优先级 drop-in `90-octop.conf`（0027 DEC-S01） |
| 服务用户 | **非 root**（`octop` 优先，`ubuntu` 过渡）；root 仅 bootstrap + `--allow-root`（DEC-S03） |
| 数据目录 | **`~/OctopData`** → `OCTOP_HOME`（DEC-006 / DEC-S08）；upgrade 不得改丢数据面 |
| 发布 | `install-hub` / `upgrade-hub` / `rollback-hub`；S0 骨架保留 N=3 版本记录；生产 `uv sync --frozen`（DEC-S04/S05） |
| 范围 | **只管理端**（DEC-007） |

## 安全组 / 防火墙 / SSH

可勾选清单：`ops/cloud-hub/ssh-ufw-checklist.md`（AC-S04）。

| 端口 | 用途 | 备注 |
|------|------|------|
| 22 | SSH | 密钥登录；禁密码；限制 Root；建议仅运维 IP |
| 8188 | 管理端 HTTP | **仅 loopback**；**不对公网**（ufw / 安全组均不放行 Anywhere） |
| 443 | HTTPS（若本机反代） | Tunnel 场景可不开公网 443 |

云厂商安全组与 `ufw` 保持一致。

## Access log（0027 DEC-S07）

1. 应用：uvicorn access + query token redact（`log_redaction`）。
2. Tunnel / 源站：按 Cloudflare 或宿主策略保留；变更记入运维记录。
3. 若部署 Caddy：必须配置 `access_log` + 轮转（**不**硬绑 Caddy 为唯一边缘）。

## 部署（Deploy Key → clone → uv → install）

```bash
# 1) 系统依赖（示例）
sudo apt update
sudo apt install -y git curl build-essential

# 2) 创建服务用户（推荐）
sudo useradd --system --create-home --shell /bin/bash octop || true

# 3) 安装 uv（在服务用户下）
sudo -u octop -H bash -lc 'curl -LsSf https://astral.sh/uv/install.sh | sh'

# 4) 获取公开主仓（下载源码不需要 Deploy Key）
sudo -u octop -H git clone https://github.com/CkEFFAF/Octopus-public.git /home/octop/octopus
cd /home/octop/octopus

# 5) 同步依赖（生产冻结锁文件）
sudo -u octop -H bash -lc 'cd /home/octop/octopus && source "$HOME/.local/bin/env" && uv sync --frozen'
# 前端按需：cd dashboard && npm ci && npm run build

# 6) 安装 systemd（默认 127.0.0.1 + User=octop）
sudo ./ops/cloud-hub/install-hub.sh \
  --user octop \
  --repo /home/octop/octopus \
  --home /home/octop/OctopData \
  --sync --frozen

# 本机健康：./ops/cloud-hub/smoke-hub.sh
# 正式入口：https://octop.effaf.me （Tunnel 指到 127.0.0.1:8188）
```

ubuntu 过渡：把 `octop` 换成 `ubuntu` 与对应家目录。

**禁止双开**：同一 `OCTOP_HOME` 只跑一个管理端实例。  
**禁止**生产手改 `.venv` / site-packages；依赖变更只经 `upgrade-hub`（0027 DEC-S05）。

### 联调拓扑 B（非默认）

```bash
sudo ./ops/cloud-hub/install-hub.sh \
  --user ubuntu \
  --repo /home/ubuntu/octopus \
  --home /home/ubuntu/OctopData \
  --host 0.0.0.0 \
  --allow-public-bind \
  --sync --frozen
```

## systemd 真相源（0027 DEC-S01）

| 路径 | 角色 |
|------|------|
| `/etc/systemd/system/octop-hub.service` | 主单元 |
| `/etc/systemd/system/octop-hub.service.d/90-octop.conf` | **唯一**允许的 ExecStart 覆盖 drop-in |
| 其他 `50-*.conf` 等 | install/upgrade **归档**到仓库 `.octop-hub-versions/dropin-archive-*` |

```bash
sudo systemctl cat octop-hub
ls /etc/systemd/system/octop-hub.service.d/
sudo systemctl status octop-hub --no-pager
journalctl -u octop-hub -n 50 --no-pager
```

reboot 抽测：`systemctl is-active octop-hub` 应为 `active`，再跑 `smoke-hub.sh`。

## 升级 / 回滚（S0 骨架）

```bash
# 升级到 origin/main（失败默认尝试 rollback）
sudo ./ops/cloud-hub/upgrade-hub.sh \
  --user octop \
  --repo /home/octop/octopus \
  --home /home/octop/OctopData \
  --ref origin/main

# 显式回滚到某 SHA 或最近一次 pre-upgrade 记录
sudo ./ops/cloud-hub/rollback-hub.sh \
  --user octop \
  --repo /home/octop/octopus \
  --home /home/octop/OctopData \
  --sha <git-sha>
```

版本记录：`<repo>/.octop-hub-versions/*.json`（默认保留 N=3）。  
S1 将强化 health 门禁与目录级版本树；S0 已具备骨架与失败回滚调用。

## HTTPS / 域名（与 Tunnel 对齐）

正式入口：`https://octop.effaf.me`（见 `docs/octopus/cloudflare-tunnel-entry.md`）。

1. **Cloudflare Tunnel（拓扑 A，生产默认）**：云机只听 `127.0.0.1:8188`。
2. **MVP HTTP IP（拓扑 B，联调）**：须 `--allow-public-bind`；设备临时 `http://111.228.42.228:8188` + `--allow-insecure`。

迁云 / 换机：只改 Tunnel 源站或 DNS；设备侧域名与账号不变（0003/0005）。

## 设备改连

```text
# 正式（默认，对齐 0006/0007）
--server https://octop.effaf.me

# 临时联调（勿写入开箱包默认）
--server http://111.228.42.228:8188 --allow-insecure
```

开箱包 / `open-device` 默认必须是域名 HTTPS，不写公网 IP。

## 验收最短路径（0027 S0）

1. `install-hub` 后：`OCTOP_BIND_HOST=127.0.0.1`、`User=` ≠ root、drop-in 目录仅 `90-octop.conf`（AC-S01/S02）。
2. 无 `--allow-public-bind` 时配置 `0.0.0.0` → 脚本拒绝（AC-S05）。
3. `ssh-ufw-checklist.md` 勾选；公网无 8188（AC-S04）。
4. `systemctl is-active octop-hub` = active；`./ops/cloud-hub/smoke-hub.sh` → `/api/health` 成功。
5. 确认开箱包默认 **不是** `111.228.42.228`。

## 非目标（本清单）

- 不写自动 Tunnel 安装器；不做多活选举；不改 Accepted 0004。
- 不把 Deploy Key / Token 写入仓库或开箱包。
- 不现场由本 PR 改 VPS；不把 0017 设备 ZDU 当作 hub 升级。
- S1+：health 自动 rollback 硬化、版本目录制品、journal 非主动重启告警（0026）。

## 过渡期执行端（0010 · 双路径）

- **开箱/产品默认仍是** `https://octop.effaf.me`（**禁止**把 IP 写入包内常量）。
- **备案前**：设 `OCTOP_DEVICE_SERVER=http://111.228.42.228:8188` 后再 `open-device`；对该 URL scoped 自动 allow-insecure（`docs/specs/0010-transition-default-server.md`）。
- **回切**：unset `OCTOP_DEVICE_SERVER`。中枢生产默认 loopback；与执行端产品默认是两件事。
