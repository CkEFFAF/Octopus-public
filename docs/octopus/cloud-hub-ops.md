# 云中枢短运维清单（Ubuntu 24）

- 对齐规格：`docs/specs/0009-cloud-hub-production.md`（Accepted / rev `2026-10-12.3`）；数据面韧性见 **`docs/specs/0026-ops-data-resilience.md`** 与 `docs/octopus/backup-restore-drill.md`
- 主机：`111.228.42.228`（4C8G Ubuntu 24）；产品域名：`https://octop.effaf.me`
- 脚本：`ops/cloud-hub/`（`install-hub.sh` / `smoke-hub.sh` / systemd 示例）
- 更新：2026-10-12（S1+S2：HTTP IP 冒烟 + systemd 系统单元 + `~/OctopData` + 只管理端）

## 一句话目标

云机跑唯一管理端；设备（Win/Linux 开箱包）默认连 `https://octop.effaf.me`；本周冒烟临时用 `http://111.228.42.228:8188`：设备侧走 **0010 路径 B**（`OCTOP_DEVICE_SERVER=...` + 白名单自动 scoped allow-insecure）；CLI 手测仍可显式 `--allow-insecure`。**禁止**把 IP 写进产品/包内默认常量（路径 A 永为 `https://octop.effaf.me`）。

## 已拍板（0009 DEC）

| 项 | 决议 |
|----|------|
| 本周拓扑 | **B：HTTP IP** `0.0.0.0:8188`（DEC-005） |
| 常驻 | **systemd 系统单元** `/etc/systemd/system/octop-hub.service`（DEC-002/008） |
| 数据目录 | **`~/OctopData`** → root 云机 `/root/OctopData`；ubuntu 例 `/home/ubuntu/OctopData`（DEC-006） |
| 范围 | **只管理端**（DEC-007） |
| 数据目录机制 | 环境变量 **`OCTOP_HOME`**（`octop run` **无** `--home` CLI 旗标） |

## 安全组 / 防火墙

| 端口 | 用途 | 备注 |
|------|------|------|
| 22 | SSH | 仅运维 IP 或密钥登录 |
| 8188 | 管理端 HTTP | MVP 可直暴露；上 HTTPS 后可只对 Tunnel/本机开放 |
| 443 | HTTPS（若反代/Tunnel） | 正式路径优先 |

云厂商安全组与 `ufw` 保持一致。

## 部署（Deploy Key → clone → uv → 前台冒烟）

```bash
# 1) 系统依赖（示例）
sudo apt update
sudo apt install -y git curl build-essential

# 2) 安装 uv（官方安装脚本；版本以运维当时为准）
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env" 2>/dev/null || true

# 3) 获取公开主仓；下载源码不需要 Deploy Key
#    当前云上下文示例（root）：
git clone https://github.com/CkEFFAF/Octopus-public.git /root/octopus
cd /root/octopus

# 4) 同步依赖（前端按需）
uv sync
# cd dashboard && npm ci && npm run build && cd ..

# 5) 前台冒烟（确认能起；数据目录用 OCTOP_HOME）
mkdir -p /root/OctopData
OCTOP_HOME=/root/OctopData OCTOP_BIND_HOST=0.0.0.0 OCTOP_PORT=8188 \
  uv run octop run
# 本机：./ops/cloud-hub/smoke-hub.sh
# 或：curl -sS http://127.0.0.1:8188/api/health
# 外网临时：http://111.228.42.228:8188 （安全组已放行时）
```

ubuntu 用户把路径换成 `/home/ubuntu/octopus` 与 `/home/ubuntu/OctopData`。

**禁止双开**：同一 `OCTOP_HOME`（生产规范 `~/OctopData`）只跑一个管理端实例。备份/异地/校验见 `docs/octopus/backup-restore-drill.md`（0026）。

## systemd（S2 常驻）

推荐用仓库脚本（会写系统单元并 `enable --now`）：

```bash
# 云机 root 上下文：
sudo ./ops/cloud-hub/install-hub.sh \
  --user root \
  --repo /root/octopus \
  --home /root/OctopData \
  --sync

# 或 ubuntu：
# sudo ./ops/cloud-hub/install-hub.sh --user ubuntu --repo /home/ubuntu/octopus --home /home/ubuntu/OctopData --sync
```

也可直接安装示例单元：

```bash
sudo cp ops/cloud-hub/octop-hub.root.service.example /etc/systemd/system/octop-hub.service
sudo systemctl daemon-reload
sudo systemctl enable --now octop-hub
sudo systemctl status octop-hub --no-pager
journalctl -u octop-hub -n 50 --no-pager
```

单元要点：`Restart=on-failure`；`Environment=OCTOP_HOME=...`；`OCTOP_BIND_HOST=0.0.0.0`；`OCTOP_PORT=8188`；`ExecStart=.../uv run octop run`。

reboot 抽测：`systemctl is-active octop-hub` 应为 `active`，再跑 `smoke-hub.sh`。

## HTTPS / 域名（与 Tunnel 对齐）

正式入口：`https://octop.effaf.me`（见 `docs/octopus/cloudflare-tunnel-entry.md`）。

两种可接受拓扑（**本里程碑先选拓扑 B**，DEC-005）：

1. **Cloudflare Tunnel（拓扑 A，正式）**：云机可只听 `127.0.0.1:8188`，Tunnel 将 `octop.effaf.me` 指到该源站。
2. **MVP HTTP IP（拓扑 B，本周）**：设备临时 `http://111.228.42.228:8188` + `--allow-insecure`；域名/Tunnel 后续切回。云机本里程碑 **只保证管理端**。

迁云 / 换机：只改 Tunnel 源站或 DNS；设备侧域名与账号不变（0003/0005）。

## 设备改连

```text
# 正式（默认，对齐 0006/0007）
--server https://octop.effaf.me

# 临时联调（勿写入开箱包默认）
--server http://111.228.42.228:8188 --allow-insecure
```

开箱包 / `open-device` 默认必须是域名 HTTPS，不写公网 IP。

## 验收最短路径（S1+S2）

1. `systemctl is-active octop-hub` = active；`./ops/cloud-hub/smoke-hub.sh` → `/api/health` 成功。
2. 运维 IP 浏览器能打开 `http://111.228.42.228:8188`（安全组已放行）。
3. （S3 未做）Win zip / Linux device tar 解压后 `open-device` 默认域名可 enroll，或临时覆盖 server 做联调。
4. 确认开箱包默认 **不是** `111.228.42.228`。

## 非目标（本清单）

- 不写自动 Tunnel 安装器；不做多活选举；不改 Accepted 0004。
- 不把 Deploy Key / Token 写入仓库或开箱包。
- 本切片不做 S3 设备改连手测、不做 S4 Tunnel 切源站（另派）。

## 过渡期执行端（0010 · 双路径）

- **开箱/产品默认仍是** `https://octop.effaf.me`（**禁止**把 IP 写入包内常量）。
- **备案前**：设 `OCTOP_DEVICE_SERVER=http://111.228.42.228:8188` 后再 `open-device`；对该 URL scoped 自动 allow-insecure（`docs/specs/0010-transition-default-server.md`）。
- **回切**：unset `OCTOP_DEVICE_SERVER`。中枢仍按 0009 HTTP IP；与执行端产品默认是两件事。

