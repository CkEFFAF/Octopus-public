# 0017 执行端无感零停机更新（Device ZDU）

- Spec ID: `0017-device-zero-downtime-update`
- Status: **Ready**
- Revision: `2026-10-15.1`
- Date: 2026-10-15
- Authoritative path: `docs/specs/0017-device-zero-downtime-update.md`
- Code baseline: `CkEFFAF/Octopus-public` @ `97fccd2b` (main)
- Relates:
  - Hub 自更新（**非本规格主目标**）：`src/octop/api/routers/update.py`（`/update/status|check|settings|upgrade|progress|restart`）、`src/octop/infra/setup/self_update.py`、`src/octop/cli/commands/update.py`、设置键 `update.stable_only`
  - 便携包 / Release：`docs/specs/0007-portable-release-packages.md`、`docs/octopus/release-process.md`、`docs/octopus/cloud-hub-ops.md`、`desktop/portable/*`、`.github/workflows/octop-desktop.yml` / `release.yml`
  - 设备协议与连接：`src/octop/infra/devices/protocol.py`、`client.py`（`HEARTBEAT_INTERVAL=20` / `heartbeat`↔`heartbeat_ack`）、`service.py`、`executor.py`、`capabilities.py`
  - 权限：`docs/specs/0005-device-permission-management.md`；`CAPABILITIES` 现为 `{desktop_view, desktop_control, files_read, files_write, command_exec, acp_run}`——**尚无** `self_update`（见 DEC-001）
  - 云中枢：`docs/specs/0009-cloud-hub-production.md`
- Non-overwrite: **勿修改** Accepted `0004` 正文；不改 enroll 核心握手语义；本规格回合 **只交 docs**（实现由 Coder/GPT）。

---

## 0. 给 Coder / GPT 的阅读顺序

1. §1 Goal / Non-goals  
2. §2 铁律与策略模型  
3. §3 时序（拉包→旁路→health→cutover/rollback）  
4. §4 接口（Hub API + device protocol）  
5. §5 REQ / AC  
6. §6 Coder 最小切片（可勾选）+ 精确路径  
7. §7 风险 / §8 Evolution  

仓库根（Windows 工作区）：`D:\Agent_Workspace\octopus\Octopus-public`

---

## 1. Goal / Non-goals

### 1.1 Goal

| 轨 | 目标 |
|----|------|
| **G1 执行端 ZDU** | 中枢发布「目标版本」后，已 enroll 的执行端在 **设备本地时窗口**（默认 **0–8**）自动：拉包 → 校验（hash）→ **旁路（side-by-side）安装** → 健康检查 → 成功 cutover / 失败回滚。用户无需手工下载替换。 |
| **G2 策略可控** | Hub 可配置：更新窗口、渠道 `stable`/`beta`、分批百分比、`force`/`deferrable`、忙时跳过（有活跃 ACP/command/桌面控制/大文件传输时不切进程）。 |
| **G3 可观测** | Hub 可查每台设备当前版本、目标版本、更新状态（idle/downloading/staged/healthy/failed/rolled_back）、最近错误。 |
| **G4 Hub 自更次优先** | 现有 PyPI `/update` 保留；本规格 **先打通执行端**；Hub 自身 ZDU 仅 Phase-2 指针。 |

**「无感」定义（写死）**：用户无手工操作 + 失败可回滚 + 忙时不打断；**允许**旁路安装后短暂切换/重启设备进程（非热补丁无重启）。

### 1.2 Non-goals

- 不做多管理端热备；**不修改** Accepted `0004`。
- 本切片 **不重做** Hub PyPI `/update` UX（指针到现有 `update.py` / `self_update.py`）。
- 不要求跨平台热补丁无重启、不要求 Windows 服务式 in-place DLL 替换。
- 不做手机端更新；不做自动跨大版本破坏性迁移（major bump 可标 force + 变更说明）。
- 本架构师回合 **只改 docs/specs 新文件**；不 commit。

### 1.3 与现有 Hub 自更新的边界（一句话）

> `/update/*` + `self_update.py` = **管理端/中枢进程** 从 PyPI 自更；**0017 = 已 enroll 执行端设备** 按 Hub 策略拉 **GitHub Release 便携包**（0007 产物）做旁路更新。二者勿混。

---

## 2. 铁律与策略模型

### 2.1 铁律

1. **包来源跟渠道**：`stable` → GitHub Release 正式资产；`beta` → pre-release 或标注 beta 的资产（与 0007 产物名对齐）。禁止设备直连任意 URL（仅允许 Hub 下发的 manifest URL / 同源 CDN）。
2. **校验失败不安装**：SHA256（或 Release 附带 checksum 文件）不匹配 → 状态 `failed`，不碰当前运行树。
3. **旁路安装**：新版本落到 sibling 目录（如 `Octop-next/` 或 `releases/<ver>/`），health 通过后再原子切换启动入口 / 当前指针；旧树保留至确认或 N 次成功启动。
4. **忙时不切**：`skip_when_busy=true`（默认）时，若设备报告 busy（见 §3.2），仅下载/暂存，**推迟 cutover** 到空闲 + 仍在窗口内（或下一窗口）。
5. **权限**：设备侧执行更新安装默认视为高风险操作——见 **DEC-001**。
6. **时区**：窗口按 **设备本地时**（device 上报的 timezone / OS local），不是 Hub `default_timezone`。

### 2.2 策略 JSON / schema 草案

Hub 持久化一份（建议 settings 键 `device_update.policy` 或表 `device_update_policies`；MVP 可用 settings JSON）：

```json
{
  "target_version": "1.2.3",
  "channel": "stable",
  "window_local": { "start_hour": 0, "end_hour": 8 },
  "batch_percent": 100,
  "force": false,
  "deferrable": true,
  "skip_when_busy": true,
  "manifest": {
    "version": "1.2.3",
    "assets": [
      {
        "platform": "windows-amd64",
        "kind": "portable",
        "url": "https://github.com/CkEFFAF/Octopus-public/releases/download/v1.2.3/Octop-portable-windows-amd64-1.2.3.zip",
        "sha256": "...",
        "size": 123456789
      },
      {
        "platform": "linux-amd64",
        "kind": "device",
        "url": "https://github.com/CkEFFAF/Octopus-public/releases/download/v1.2.3/Octop-device-linux-amd64-1.2.3.tar.gz",
        "sha256": "...",
        "size": 123456789
      }
    ]
  },
  "published_at": "2026-10-15T12:00:00Z",
  "notes": "optional changelog excerpt"
}
```

| 字段 | 语义 | 默认 |
|------|------|------|
| `target_version` | 期望设备软件版本（semver 字符串，与包名 `<ver>` 一致） | 无则不推 |
| `channel` | `stable` \| `beta` | `stable` |
| `window_local.start_hour/end_hour` | 设备本地时 `[start, end)`；跨午夜用 `start>end` 语义（本 MVP：**禁止跨午夜**，要求 `0≤start<end≤24`） | `0`–`8` |
| `batch_percent` | 1–100；按 `hash(device_id) % 100 < batch_percent` 入选 | `100` |
| `force` | true 时忽略 deferrable 用户推迟（仍尊重 busy，除非另开 `force_even_when_busy`——**本 MVP 不提供**） | `false` |
| `deferrable` | 允许设备侧「推迟到下一窗口」一次（本地记 flag） | `true` |
| `skip_when_busy` | 忙时只 stage 不 cutover | `true` |

### 2.3 DEC / OQ

| ID | 决定 / 问题 | 状态 | 默认假设（Coder 可跟） |
|----|-------------|------|------------------------|
| **DEC-001** | 更新安装是否新增权限键 `self_update`？ | **resolved（MVP 假设）** | **不新增 CAPABILITIES 键**。已 enroll 设备对 Hub 下发的 **同渠道官方包** 自动更新视为控制面能力；Dashboard「发布目标版本」仅 admin。若产品后续要求用户可见开关，再加 `self_update` + 0005 扩展（Evolution）。 |
| **DEC-002** | 版本号来源 | **resolved** | 设备在 `hello` / 周期性 `status` 上报 `software_version`（读便携包内版本文件或 `importlib.metadata.version("octop")` / `launch.py` 旁 `VERSION`）；Hub `devices` 行缓存 `software_version` + `update_status`。 |
| **DEC-003** | 包形态 | **resolved** | 复用 0007：Win `Octop-portable-windows-amd64-<ver>.zip`；Linux 设备 `Octop-device-linux-<arch>-<ver>.tar.gz`。 |
| **OQ-001** | Hub 多租户下策略按站还是按用户？ | open | MVP：**整站一份** admin 策略（与当前 `update.stable_only` 类似）；多用户隔离留 Evolution。 |

---

## 3. 时序

```
Admin 发布策略 (target_version + manifest)
        │
        ▼
Hub 持久化 policy；可选 WS 推送 device_update.offer
        │
        ▼
Device: poll on heartbeat_ack 附带 / 或独立 GET /api/devices/me/update
        │  不在窗口或未入选 batch → 仅记录 offer，不下载（force 除外：仍可预下载）
        ▼
Download → 写临时文件 → sha256 校验
        │ 失败 → update_status=failed，上报错误，保留旧树
        ▼
Stage: 解压到 sibling（旁路），不替换当前运行目录
        ▼
Health: 对新树跑 `--version` / 本地 probe 脚本（见 AC）；可选短时拉起旁路进程 ping Hub
        │ 失败 → 删除 stage，rollback 状态，上报
        ▼
Busy? 是 → 等空闲（仍在窗口）或下一窗口
        ▼
Cutover: 切换 current 指针 / 重启 device 进程加载新树；成功后上报 software_version=target
        │ 启动失败 → 回切旧指针并重启（rollback）
        ▼
Hub 更新设备行；Dashboard 可见
```

### 3.2 Busy 判定（设备侧）

任一为真则 busy：

- 存在活跃 `acp.*` session（`executor` / `acp_bridge`）
- 存在未完成 `command.run`
- 桌面控制会话活跃（`desktop.input` 近期授权流）
- 大文件 transfer 进行中（`files.write_*` / transfers）

上报字段：`busy: bool`、`busy_reasons: string[]`。

---

## 4. 接口

### 4.1 Hub API（新建路由器建议）

路径建议：`src/octop/api/routers/device_update.py`，挂到 `devices` 或独立 prefix `/device-update`。

| Method | Path | Who | 说明 |
|--------|------|-----|------|
| `GET` | `/device-update/policy` | admin | 当前策略 |
| `PUT` | `/device-update/policy` | admin | 发布/修改目标版本与策略（body=§2.2） |
| `GET` | `/device-update/devices` | admin | 列表：device_id, software_version, update_status, last_error, eligible |
| `GET` | `/devices/me/update` 或 WS 附带 | device JWT | 设备拉自己的 offer（已按 batch/channel 过滤后的 manifest 子集） |
| `POST` | `/devices/me/update/report` | device | body: `{status, software_version, error?, stage_version?}` |

**伪代码（设备 poll）**：

```python
# device client loop (extend heartbeat path or dedicated task)
offer = await hub.get_update_offer()  # None if no target or not eligible
if offer and in_local_window(offer.window_local) and not deferred:
    path = await download(offer.asset.url, expect_sha256=offer.asset.sha256)
    staged = stage_side_by_side(path)
    if not health_check(staged):
        report(status="failed", error="health"); rollback_stage(); return
    if offer.skip_when_busy and is_busy():
        report(status="staged"); return  # cutover later
    cutover(staged); restart_self(); report(status="ok", software_version=offer.target_version)
```

### 4.2 Device protocol 消息（扩展）

在现有 WS（`client.py` ↔ `service.py`）上增量，**不破坏** `hello`/`grants`/`heartbeat`：

| 方向 | type | 字段 |
|------|------|------|
| Hub→Device | `device_update.offer` | `target_version`, `channel`, `window_local`, `force`, `deferrable`, `skip_when_busy`, `asset{url,sha256,platform,kind}` |
| Device→Hub | `device_update.report` | `status`, `software_version`, `error?` |
| Device→Hub | `hello` / `status` 扩展 | **新增** `software_version: str`（DEC-002） |

实现落点：

- `src/octop/infra/devices/protocol.py` — 常量 / 校验 helper（可选）
- `src/octop/infra/devices/client.py` — poll、download、stage、cutover、上报
- `src/octop/infra/devices/service.py` — 推送 offer、收 report、写 DB
- 新建：`src/octop/infra/devices/updater.py`（下载/校验/旁路/health/rollback）

### 4.3 与 portable / green 的关系

- `self_update.green_packages_dir()` / `OCTOP_GREEN_PACKAGES` 是 **Hub/管理端** 绿色包安装路径，**可参考旁路思路**，但设备更新代码放 `infra/devices/updater.py`，不要把设备流程塞进 `self_update.py`。
- 校验优先读 Release 的 `SHA256SUMS` 或 manifest 内嵌 `sha256`。

---

## 5. REQ / AC

### REQ-001 策略发布与查询

- Requirement: Admin 可 PUT/GET 设备更新策略（§2.2）；无 `target_version` 时设备不主动升级。
- AC-001: Given admin PUT `target_version=1.2.3` + 合法 manifest，When GET policy，Then 返回相同字段。
- AC-002: Given 非 admin，When PUT，Then 403。

### REQ-002 窗口与分批

- Requirement: 设备仅在本地时 `[start,end)` 内 cutover；batch 按 device_id 稳定哈希。
- AC-003: 设备本地 09:00、窗口 0–8、非 force → 可下载但 **不** cutover（或完全不下载——实现选「可预下载、禁止 cutover」，写进代码注释与 AC：本 AC 要求 **禁止 cutover**）。
- AC-004: `batch_percent=0` → 无设备 cutover；`100` → 全部候选。

### REQ-003 拉包校验与旁路

- Requirement: 下载后 sha256 匹配才 stage；stage 不覆盖当前运行树。
- AC-005: 错误 hash → `failed`，当前 `software_version` 不变。
- AC-006: stage 目录与 current 目录路径不同。

### REQ-004 Health + 回滚

- Requirement: health 失败或 cutover 后进程无法重连 Hub → 回滚到旧树并上报 `rolled_back` / `failed`。
- AC-007: 故意破坏 stage 二进制 → health 失败 → 无 cutover。
- AC-008: cutover 后连续 N=1 次无法完成 hello → 回切旧树（实现可简化为「新进程启动失败则退出码触发旧入口」）。

### REQ-005 忙时跳过

- Requirement: `skip_when_busy` 时有活跃 ACP 不 cutover。
- AC-009: 开着远程 ACP session，到窗口 → status=`staged`，ACP 不中断；ACP 结束后同一窗口或下一窗口再 cutover。

### REQ-006 版本上报

- Requirement: hello/status 带 `software_version`；Hub 列表可见。
- AC-010: 更新成功后 Hub `software_version` 等于 `target_version`。

### REQ-007 渠道

- Requirement: `stable` 忽略 beta 资产；`beta` 可吃 pre-release manifest。
- AC-011: channel=stable 时设备不安装仅标 beta 的包。

---

## 6. Coder 最小切片（可勾选）

- [ ] **S1 策略存储 + 查询** — settings/表 + `GET/PUT /device-update/policy` + admin 鉴权；单测 schema 校验。
- [ ] **S2 设备拉包校验** — `updater.download_and_verify`；`software_version` 上报；`GET /devices/me/update` 或 WS offer。
- [ ] **S3 旁路安装 + health + rollback** — sibling stage、health probe、cutover 指针、失败回滚；设备进程安全重启。
- [ ] **S4 忙时 / 窗口 / 分批** — local window、batch hash、busy 检测与推迟。
- [ ] **S5 Dashboard 发布 UI（P1）** — 设置页「设备更新」：目标版本、渠道、窗口、分批、设备列表状态；可后置，API 先行。

### 6.1 精确文件路径

| 动作 | 路径 |
|------|------|
| 新建 | `src/octop/api/routers/device_update.py` |
| 新建 | `src/octop/infra/devices/updater.py` |
| 改 | `src/octop/infra/devices/client.py`（offer 处理、version 上报、更新任务） |
| 改 | `src/octop/infra/devices/service.py`（推送/收 report） |
| 改 | `src/octop/infra/devices/protocol.py`（可选常量） |
| 改 | `src/octop/infra/db/repos/devices.py`（缓存 `software_version` / `update_status`） |
| 改 | `src/octop/api/routers/__init__.py` 或 app 挂载处注册路由 |
| 可选新建 | `dashboard/src/pages/.../DeviceUpdate*.tsx`（S5） |
| 测试 | `tests/.../test_device_update_0017.py`（名称按仓内惯例） |
| 文档指针 | `docs/octopus/release-process.md` 追加一节「设备 ZDU」（**可另 PR**；本规格不强制改） |

**禁止本切片改**：`self_update.py` 主流程冒充设备更新；Accepted `0004`；无关 dirty WIP。

---

## 7. 风险与回滚

| 风险 | 缓解 |
|------|------|
| 切进程打断长任务 | 默认 `skip_when_busy`；窗口仅深夜 |
| 坏包导致变砖 | hash + health + 保留旧树；启动器优先读 `current` 指针 |
| GitHub Rate limit / 大包 | Hub 可后加镜像 URL；设备断点续传可 Evolution |
| 与 Hub PyPI 更新概念混淆 | Dashboard 文案区分「中枢自更新」vs「设备更新」 |
| 权限争议 | DEC-001；Evolution 可加 `self_update` |

**规格级回滚**：关闭策略（清空 `target_version`）即停止新 cutover；已 stage 未切可清理。

---

## 8. Evolution

- Hub 进程自身也走旁路 ZDU（复用 `/update` 或对齐本策略）。
- 权限键 `self_update` + 0005 用户可见开关。
- 多租户 per-user policy；分批按标签/设备组。
- 签名验真（minisign/cosign）不仅是 sha256。
- 跨午夜窗口；`force_even_when_busy`（需强警告）。

---

## 9. Evolution log

- 2026-10-15.1: 初稿 Ready；执行端 ZDU 主路径；Hub `/update` 标次优先；DEC-001 不新增权限键（MVP）。
