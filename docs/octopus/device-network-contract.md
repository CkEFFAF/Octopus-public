# 设备网实现合同（2026-10-09）

规格：`docs/specs/0001-account-device-network.md`，本次版本含 iOS 远程端与配对码。
基线：上游 4b17f1c 加当前未提交的 Octopus 功能；保留现有工作，不重置或提交。

## 并行所有权

- 主 Agent：合同/规格/进度；infra/devices/service.py、protocol.py；API devices.py、
  deps/app/server 接线；Agent 工具、看板、共用后端 i18n 接线；集成验证。
- db worker：022_account_devices.sql/.pg.sql、repos/devices.py、db/services.py；
  tests/unit/db/test_devices.py 和 schema 版本断言。完成后只读审查集成。
- client worker：infra/devices/client.py、executor.py、cli/device_cmd.py，
  cli/main.py 的子命令注册，desktop/portable 的独立设备启动脚本；
  tests/unit/devices/test_executor.py、test_client.py。不改 service/protocol。
- UI worker：dashboard/src/pages/Devices、api/modules/devices.ts；路由/导航、
  dashboard locales 的 devices 自有域；devices 页面测试。不改看板/聊天。

测试端口、数据目录独立；所有 worker 不操作 git index/branch，不重启当前验收宿主。
接口变化先通知主 Agent，不分别发明字段；主 Agent 更新本合同后再继续相关代码。

## HTTP（均 `/api` 前缀）

设备公开结构 Device：device_id/name/platform/capabilities:string[]/permissions:string[]/
roots:Root[]/grant_version:int/online:boolean/last_seen_at:number|null/revoked_at:number|null。
Root：id/name/path/read:boolean/write:boolean。路径仅向所有者显示。
能力枚举：desktop_view、desktop_control、files_read、files_write、command_exec。

- GET /devices -> {devices:Device[]}，当前账号所有设备，含已撤销。
- POST /devices/pairing -> {pairing_code:string, expires_at:number}；登录账号专用，10min。
- POST /devices/enroll（路径仍 JWT-exempt，便于配对码/接入密钥客户端）：
  凭证三选一：pairing_code | access_key | Authorization Bearer 用户 JWT（密码/SSO；
  禁止 auth_key_id 的 key-session；禁止客户端自报 owner_user_id）。
  Body：{name,platform,capabilities,permissions,roots}（+ 所选凭证字段）。
  登记时服务端按 0005 REQ-007 写入默认 permissions（desktop_view/desktop_control/files_read ∩ capabilities）；扩权见 0005 grant_proposal / owner_auto。
  -> {device:Device,device_token:string}；消费单次配对码、颁发 odv_；只存 token_hash。
- PATCH /devices/{id} {name?,permissions?,remote_grant_mode?} -> Device；permissions ⊆ capabilities；扩权按 remote_grant_mode / 高危强制 confirm（0005）。
- GET /devices/{id}/grant-status；POST /devices/{id}/grant-proposals；POST .../resolve。
- POST /devices/{id}/revoke -> Device；断开连接并阻止新操作。
- POST /devices/{id}/operations {action:string,params:object,agent_id?:string}
  -> Operation；操作由宿主执行，关页面仍结算。
- GET /devices/operations?device_id=... -> {operations:Operation[]}，最近100条用户账本。
- GET /devices/operations/{id} -> Operation；POST .../{id}/cancel -> Operation。
- POST .../{id}/confirm -> Operation；仅用户 HTTP，Agent 不得自行确认 command.run。
- POST /devices/{id}/call {action,params} -> object：等待结果的轻量适配；超时返回错误。
  command.run 不允许此入口（走 operations 人工确认）。capture 不落完整图像到数据库。
- POST /devices/transfers {source_device_id,source_root_id,source_path,
  target_device_id,target_root_id,target_path} -> Operation（action=files.transfer）。
  中继分块传输，状态 ledger.result 包含 bytes_total/bytes_done/sha256。

Operation：operation_id/device_id/owner_user_id/agent_id:null|string/task_run_id:null|string/action/params:object/
status: pending_confirmation|queued|running|completed|failed|cancelled|unknown/
result:object|null/error:string|null/created_at/updated_at。拒绝的请求用 Octop 错误信封。

## 设备通道（独立 WS /api/devices/connect/ws）

首帧 {type:'hello',protocol:1,device_id,token}；10s 无认证关闭。
服务端 {type:'hello_ack',protocol:1,grant_version,permissions,roots,connection_id}。
客户端每20s {type:'heartbeat'}；响应 {type:'heartbeat_ack'}；60s 超时断开。
服务端 {type:'request',id,action,params,grant_version,permissions}。
客户端 {type:'result',id,ok:true,result:object} 或 {type:'result',id,ok:false,error:string}。
服务端 {type:'cancel',id}；连接替换/撤销立即 close。断线不自动重发 request。
客户端执行器按 id 保存去重结果（本地持久日志，上限清理但不清除活跃项）；
重连对账不自动再次执行未知请求。token 不放 URL，不打印。
客户端重连发送 {type:'reconcile',results:[{id,ok,result?}]}（≤100项）；服务端仅
接受匹配设备、授权版本且仍未结算的回执。旧连接失败不能覆盖已结算回执。
command.run 非零 returncode 记 failed，不能以传输 ok 宣称命令成功。

## 账号登录/加入密钥（用户补充）

- GET/POST /auth/access-keys：登录账号的具名密钥列表及创建，返回明文一次。
  POST {name,days:1..365,allow_browser:true,allow_devices:true}；默认30天。
- POST /auth/access-keys/{key_id}/revoke：只撤销自己账号的密钥。
- POST /auth/key-login {access_key}（免用户 JWT）：校验摘要、用途、过期/撤销与
  账号启用状态，返回带 auth_key_id 来源的短期用户 JWT；失败按来源限流。
- /devices/enroll 凭证三选一：pairing_code | access_key | Bearer 用户 JWT；
  账号密钥不写入设备状态；JWT 仅用于登记请求，不得写入 device-state。
  加入后获得独立 odv_ 设备凭据，账号密钥不保存到设备状态。
- 密钥浏览器会话不能创建新密钥或配对码；每次 HTTP 与浏览器 WS 消息及空闲
  检查验证来源密钥，续期不清除来源。撤销密钥不自动撤销已加入的设备。
- 023 SQLite/PostgreSQL 迁移仅持久摘要与名称、用途、期限、最后使用、撤销时间。
  CLI支持 --access-key；推荐 --key-file 私有文件，避免进程参数留下明文。
  账号登录登记：`--username`（密码**优先交互输入**，勿把 `--password` 明文挂命令行）或 `--account-token`；详 `docs/octopus/same-account-enroll-ops.md`。
  扩权（0005）= 管理端可授至 capabilities；owner_auto 非高危在线即生效；command/acp 强制设备 confirm；旧客户端 CLIENT_OUTDATED 双轨。

## 任务与群聊执行关联

聊天目标和看板确认绑定 device_id/grant_version；异步派工成员及主持人回传
继承同一授权快照与 task_run_id，不放宽 ask/plan。权限变化拒绝执行。
看板等待成员派工和所有关联设备操作结算，修复轮同样等待；取消同步中止关联
派工及设备工作。命令结果和设备账本进入裁判证据，模型口头成功不能替代回执。
输入、写入提交/中止等轻量调用有账本记录，图像和文件块不写入账本。

## 执行器动作

- ping/status -> {platform,hostname,capabilities}。
- files.list {root_id,path:''} -> {entries:[{name,path,is_dir,size}],root_id,path}。
- files.stat {root_id,path} -> {size,sha256,is_dir}（sha256 对文件）。
- files.read {root_id,path,offset:0,length:1048576} -> {data_b64,size,offset,eof}。
- files.write_begin {root_id,path,size,sha256} -> {upload_id}，禁止覆盖默认存在目标。
- files.write_chunk {upload_id,offset,data_b64} -> {bytes_done}，按序、每块≤1MiB。
- files.write_commit {upload_id} -> {size,sha256,path}，先校验临时文件再原子提交。
- files.write_abort {upload_id} -> {aborted:true}。
- desktop.capture {quality?:int} -> {jpeg_b64,width,height}，复用 ScreenCapture。
- desktop.input {kind:'click'|'move'|'scroll'|'type'|'key',x?,y?,button?,text?,key?,dy?}
  -> {ok:true}，复用 InputInjector；能力 desktop_control 且 desktop_view 均需授权。
- command.run {argv:string[],root_id,timeout?:int} -> {returncode,stdout,stderr,truncated}。
  不用 shell=true，工作目录限定共享根，超时/取消终止子进程，Agent 请求需人工确认。
  timeout 必须为 1–3600 秒整数，默认 60 秒；管理端等待该期限加 15 秒清理/传输余量。
  stdout/stderr 各按实际 JSON UTF-8 编码限制为 1MiB，截断明确标记；对账逐条发送，
  旧命令 journal 在加载和重放时同样限制，防止过大回执反复断开连接。

capabilities 为硬件/客户端上限；远端 grants 可扩至 capabilities（0005）；高危扩权须设备 confirm；禁止服务端发明路径/自动 mkdir。
目录相对路径，拒绝绝对路径、..、符号链接与 Windows junction/reparse 逃逸。
提交前复核哈希期间的根、父目录和临时文件身份。POSIX 将目录和临时文件绑定到
no-follow fd，使用 dir_fd 提交并复核 inode；Windows 复核已重现的 await 替换窗口，
不承诺抵抗同权限本地进程任意并发修改的 OS 沙箱。
不同 root 必须能包含不同OS路径；不能假定 POSIX/Windows。读/写权限单独判断。
客户端是 Windows/Linux 原生设备端；Android/iOS 是移动响应式控制端，不能假冒已提供原生后台。

## 启动流程

账号登录登记（0004，推荐最小入网）：

`octop device connect --server URL --username USER`
密码**优先交互输入**（勿把 `--password` 明文挂在命令行）；也可用 `--account-token` 短 JWT。
成功后写 device-state（仅 `odv_`），之后无参重连。详 `docs/octopus/same-account-enroll-ops.md`。

配对码路径（保留）：

`octop device connect --server URL --pair-code CODE --name NAME --share PATH`
选项 --read-only、--desktop（查看）、--control（输入）、--allow-command、--allow-insecure。
默认只有已选共享目录读写，其他显式启用；无共享目录仍可注册 ping/status。
--state PATH 可隔离测试和多设备；默认独立设备状态目录，含 device_id/token/local policy。
后续 `octop device connect --state PATH` 使用已保存配置重连，无需重复配对。
HTTP仅loopback默认允许；远程HTTP必须显式 --allow-insecure。
不触碰用户现有账号/数据库，不登录 Windows 账号，不自动改防火墙。

扩权：见 0005；正式 `--server` 示例为 `https://octop.effaf.me`（CF Tunnel），非内网 IP。
