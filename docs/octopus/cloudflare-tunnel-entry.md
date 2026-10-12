# 稳定入口：Cloudflare Tunnel + 公网域名

规格：`docs/specs/0005-device-permission-management.md` REQ-008 / DEC-008（revision 2026-10-12.3+）。

## 目标拓扑

```text
执行端 --HTTPS--> https://<your-domain>  --CF Tunnel-->  工位本机控制中心
```

- `/api/` REST 与 `/api/devices/connect/ws` 经同一域名可达
- 证书由 Cloudflare 提供；产品不强制用户自签证书
- Cloudflare 账号 / API Token **不**写入产品密钥库；Tunnel 凭证仅宿主机运维配置

## 开箱配置（执行端）

```text
octop device connect --server https://<your-domain> --username <账号>
```

密码优先交互输入。占位符 `<your-domain>` 替换为你的自定义域名；用户暂无域名时可先保留占位，配好 Tunnel 后再填。

## 管理端（工位）

1. 本机控制中心正常监听（默认本机端口）
2. 安装并登录 `cloudflared`（宿主机运维，非产品内置安装器）
3. 创建 Tunnel，将公网域名（含 `/api/` 与设备 WS 路径）指到本机控制中心
4. 验证：浏览器打开 `https://<your-domain>`；设备用域名 + 账号完成登记/重连（无需 `--allow-insecure`）

## 迁云

换机器或上云时：**只改 Tunnel 源站指向**新控制中心；执行端 `--server` 域名与账号不变（对齐 0003）。

## 非目标 / 附录

- 全自动 Tunnel 安装器：非本里程碑必须
- 内网 IP + `--allow-insecure`：仅局域网调试附录，非正式推荐路径
