# 工位管理实例迁移

Status: Implemented — workstation cutover and original data verified; Windows autostart and phone acceptance pending
Source: 用户确认工位唯一常开管理端，并要求继续实施；
[部署清单](../octopus/workstation-rollout.md)。

## Summary

将同一个 SQLite 管理实例从笔记本迁至工位。保留账号、认证/加密密钥、设备身份、
历史与工作文件；迁移工具在本地离线运行，不提供远程任意文件或数据库上传 API。
沿用 Python、cryptography 和现有进程锁/私有目录机制，无新依赖。

## Requirements

- **MOVE-01 离线导出：** 持有 home/.host.lock；管理服务运行、配置为 PostgreSQL、
  有执行中/待执行工作或 home 外的智能体工作区时拒绝。包含 home 下所有普通文件，
  聊天、security/tool_guard、插件和 browser-profiles 均不默认漏掉。跳过实例运行锁、
  SQLite WAL/SHM，SQLite 主文件通过 backup API 复制并核验。
- **MOVE-02 加密包：** 口令不少于 12 字符，仅隐藏提示或私有 password-file 读取，
  不放命令参数。固定版本头、随机 salt/nonce、PBKDF2-SHA256 600000 次和 AES-256-GCM
  流式加密；头纳入 AAD，包含路径/摘要的 manifest 也加密。错误口令/篡改明确失败。
  私有临时目录保存未加密内容，失败清理；不覆盖现有导出文件。
- **MOVE-03 安全恢复：** 恢复到不存在的新 home，不覆盖已有实例；校验归档成员与
  manifest SHA256 对应关系，拒绝相对逃逸、符号/硬链接、特殊文件、重复成员，
  解压总量最多 2 GiB、100000 文件。验证失败不能留下可启动的新实例。
- **MOVE-04 数据归属：** 账号 ID/密码散列/密钥/设备摘要、设备根和权限、会话与
  聊天内容不改。仅修正 config.json、agents/storage_backends 的 config_json 中
  指向旧 home 的已知文件路径字段；home 外的存储根不隐式复制或扩大授权。
  发布前核验所有 SQLite 与配置；迁移不启动新管理服务、不新增设备许可。
- **MOVE-05 客户端迁址：** 显式旧地址匹配、停止原生客户端、离线改受信任地址；
  保留身份/权限/journal，不发送凭据进行探测，不允许 HTTPS 降至远程 HTTP。
  CLI 默认显示旧新地址并要求确认；新独立管理实例仍走独立配对。
- **MOVE-06 切换与回退：** 源实例保留；提供导出/恢复和三台设备接入步骤。只有
  工位原账号、原数据、客户端连接验收后才让其作为唯一可写管理端。
  真实工位部署、Windows 自动恢复及手机真机验收单独记证据，不因单测通过关闭任务。

## Decision

先交付 `backup move-export` / `backup move-import` 和 `device relocate-controller`。
版本化 `.octopmove` 格式为加密 tar.gz，与既有可选内容普通备份分开；该格式用于
同 OS、同 SQLite 实例迁址，不暗示 PostgreSQL/跨 OS 或外部存储自动迁移。
密码可用文件交给本机工具，但不允许把口令文件和加密包一起通过共享目录分发。
2 GiB/100000 文件为首轮受控包上限，超过时失败并保留源数据；当前实例约 50 MiB。
临时文件置于现有私有目录机制，发布只原子改名到新路径；不递归删改用户目标目录。

## Build plan

1. 实现领域归档及恢复、口令保护（MOVE-01 至 MOVE-04）；以真实 SQLite 数据结构
   构造隔离测试，检验账号/设备/聊天保留、工作区改址、错误口令与恶意归档。
2. CLI 和 Windows 快捷入口，复用便携运行时（MOVE-02、MOVE-06）。
3. 客户端迁址及相邻回归（MOVE-05）；独立子 agent 负责，父 agent 集成验收。
4. 更新部署清单、构建便携包，隔离恢复真实数据副本后准备工位切换（MOVE-06）。
   实际发送敏感数据/扩大 Windows 本地权限时按具体目标和动作确认。

## Consequences

迁移包持有实例的认证与设备管理能力，必须加密保管。两个副本不能同时接收新
写入；不是账户同步或故障自动切换。Windows 登录前管理服务和长期 GPU 作业仍
是后续部署/能力工作；本文不将其标记为已完成。

## Evidence — 2026-10-10

- Ruff 全量检查/格式通过（1206 文件）；strict mypy 589 源文件通过。
- 完整 non-live pytest：4406 passed、152 skipped，567.00 秒；迁移/设备邻接/i18n
  聚焦回归 167 passed、2 skipped。
- 当前 home 无活动任务或设备操作；短暂停服、加密导出、恢复至私有隔离目录，
  524 个文件、3 条路径配置修正、10 张身份/聊天/授权相关表逐行一致。
- 密码保存在私有本机文件，未输出或传输；加密包不进入程序分发 ZIP。
  恢复副本未启动服务；源 home 和工位/GPU 真实身份与权限保留。
- 源管理服务已恢复原入口，GPU 到 `10.198.240.130:8188/api/health` 为 200；
  新目录程序出现 LAN 超时，回退原入口后恢复。工位新目录防火墙尚需现场核验。
- 路径变更保留原任务 pin，不自动重新授权；执行前必须重新确认。Windows 浏览器
  配置文件保留不等于跨机器 DPAPI 网站登录保持。MOVE-06 真实工位切换尚未验收。
