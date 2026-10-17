# Cloud hub SSH / ufw 验收清单（0027 S0 · DEC-S06 / AC-S04）

对齐规格：`docs/specs/0027-ops-host-runtime.md`。  
本清单可勾选；**不**在仓库内自动改 VPS。正式入口优先 Cloudflare Tunnel（拓扑 A）。

## SSH

- [ ] `PasswordAuthentication no`（`/etc/ssh/sshd_config` 或 drop-in）
- [ ] `PermitRootLogin prohibit-password` 或 `no`（密钥运维；禁密码 root）
- [ ] 仅密钥登录；运维公钥在 `~/.ssh/authorized_keys`
- [ ] 可选：`AllowUsers` / `AllowGroups` 限制运维账号
- [ ] `sshd` reload 后新开会话验证（勿锁死当前会话）

## ufw（与云安全组一致）

- [ ] `ufw default deny incoming` / `allow outgoing`（或等价策略）
- [ ] **22/tcp**：仅运维 IP（或 jump host），不对全世界开放（若暂无法限 IP，至少密钥 + fail2ban）
- [ ] **443/tcp**：仅当本机跑反代时开放；Tunnel 场景可不开公网 443
- [ ] **8188/tcp**：**不对公网**（`ufw status` 无 `8188` allow from Anywhere）
- [ ] Hub 监听 **`127.0.0.1:8188`**（`ss -lntp | grep 8188` 仅 loopback）
- [ ] 变更后：`ufw status verbose` 截图/粘贴入变更记录

## Access log（0027 DEC-S07）

- [ ] 应用：uvicorn access + query token redact（见 `src/octop/infra/utils/log_redaction.py`）
- [ ] Tunnel / 源站：Cloudflare 或宿主日志保留策略已成文（天数 / 存放处）
- [ ] 若部署 Caddy：`access_log` 路径 + 轮转已配置（**不强制** Caddy 为唯一边缘）

## 快速审计命令

```bash
ss -lntp | grep 8188 || true
sudo ufw status verbose
sudo systemctl cat octop-hub
ls /etc/systemd/system/octop-hub.service.d/
# 期望仅见 90-octop.conf（或空目录 + 单元内嵌配置）；无残留 50-* 盖过 ExecStart
```
