# 0007 便携 Release 开箱包（Win + Linux ready-to-run）

- Spec ID: `0007-portable-release-packages`
- Status: **Accepted**（OQ-001/002/003 已按用户「按建议」关闭；Coder 已派 S1+S2）
- Revision: `2026-10-12.2`
- Date: 2026-10-12
- Authoritative path: `docs/specs/0007-portable-release-packages.md`
- Relates:
  - `0005-device-permission-management.md`（REQ-006 便携 Release；本规格**覆盖**其「Linux 全量可延后」软门槛）
  - `0006-device-first-run-launcher.md`（默认 `https://octop.effaf.me`、`open-device`）
  - `docs/octopus/run-and-build.md`、`cloud-hub-ops.md`、`same-account-enroll-ops.md`、`cloudflare-tunnel-entry.md`
  - 实现面：`desktop/portable/*`、`.github/workflows/octop-desktop.yml`、`.github/workflows/release.yml`；Release 目标仓 **`CkEFFAF/Octopus`**（DEC-007）
- Non-overwrite: **不修改** Accepted `0004` 正文；不改 enroll 协议；本规格只定 Release 产物、打包与开箱验收。业务代码由 Coder 按本指南实现。

## 与 0005 的覆盖/修订关系

| 项 | 0005（至 `2026-10-12.3`） | 0007（本规格） |
|----|--------------------------|----------------|
| Win amd64 便携 zip | **硬门槛**必出 | **保持**硬门槛 |
| Linux amd64 全量便携 | DEC-006：**软门槛 / 可延后**；device-only 可注记 | **升为硬门槛**：Release **必须**同时提供 Linux ready-to-run（见 REQ-002） |
| 默认 server 示例 | 公网域名 / Tunnel（REQ-008） | 与 0006 对齐：默认 `https://octop.effaf.me` |
| 验收 | 洁净 Win 开箱 | 洁净 Win **+** 洁净 Linux 解压即跑并能 enroll |

0005 Evolution 仅追加一行交叉引用；**不重写** 0005 REQ-006 大段正文。冲突时：Release 出包范围以 **0007** 为准；权限/Tunnel/默认 permissions 仍以 0005 为准。

## Problem

产品要「UU 式」开箱：用户从 GitHub Release 下载 zip/tar，解压即可接入设备网，无需本机装 uv/Node/系统 Python。  
仓库已有：

- `desktop/portable/package.sh` → 全功能绿色包 `Octop-portable-<plat>-<ver>.zip`
- `desktop/portable/package-device-linux.sh` → 无界面设备包 `Octop-device-linux-<arch>-<ver>.tar.gz`
- CI：`.github/workflows/octop-desktop.yml`（多平台 green zip + 挂 Release）
- 启动器：`open-device.bat/.sh`、`start-device.bat/.sh`、`setup-device.bat/.sh`（0006）

缺口：把 **Win + Linux 两边都作为 Release 硬交付**写清（覆盖 0005 Linux 可延后）；统一产物布局、changelog、本地/CI 打 Release 步骤与 Coder 切片，使验收「解压即跑、能 enroll、默认连 octop.effaf.me」。

## Goals

1. GitHub Release（`v*`）同时提供 **Windows amd64** 与 **Linux amd64** ready-to-run 包。
2. 解压后无需 uv/Node/系统 Python；设备入口默认 server = `https://octop.effaf.me`（0006）。
3. 复用现有 `package.sh` / `package-device-linux.sh` / `octop-desktop.yml`，最小增补。
4. 版本号与 changelog 可追踪；SHA256 校验文件随包。
5. 给 Coder 可交接的实现指南（切片、路径、验收命令、风险）。

## Non-goals

- 不实现 0008 桌面交接 / 故障转移。
- 不把云主机公网 IP 写进产品默认 server。
- 不强制本里程碑交付 darwin / windows-arm64 / linux-arm64（CI 已有能力可保留，但 **MVP 验收硬门槛仅 win-amd64 + linux-amd64**）。
- 不改 Accepted 0004；不在本规格内 commit / 打 tag（由总管/发布流程）。
- 不做手机包；不把 Wails 桌面壳验收当作本规格硬门槛（**DEC-008**：本里程碑不验 `Octop-desktop-*`；CI 若仍打可附带；开箱主路径仍是浏览器 + `open-device` / `start-device`）。

## Requirements and acceptance

### REQ-001 — Windows amd64 ready-to-run（硬门槛）

- Requirement: `v*` Release **必须**含 `Octop-portable-windows-amd64-<ver>.zip`（由 `bash desktop/portable/package.sh windows-amd64` 或 CI `octop-desktop.yml` 产出）。zip 内顶层 `Octop-windows-amd64/`，含 `runtime/`、`packages/`、`launch.py`、`start.bat`/`open.bat`、**设备入口** `open-device.bat` / `start-device.bat` / `setup-device.bat`、`README.txt`。
- AC-001: 洁净 Windows 机（无预装 uv/Node/Python）解压后双击 `open-device.bat`（或 README 主入口），向导预填 `https://octop.effaf.me`，账号密码可完成 0004 enroll。
- AC-002: 同包 `start.bat --home <空目录>` 可起管理端（全功能包能力保留）；设备开箱主文档路径指向 `open-device`，不强迫用户先开管理端。

### REQ-002 — Linux amd64 ready-to-run（硬门槛；覆盖 0005 DEC-006 软门槛）

- Requirement: 同一 `v*` Release **必须**至少提供一种 Linux amd64 解压即跑包，满足设备 enroll：
  - **路径 A（推荐同时挂）**：全功能 `Octop-portable-linux-amd64-<ver>.zip`（`package.sh linux-amd64` / CI 已支持）
  - **路径 B（无界面 GPU/服务器必挂）**：`Octop-device-linux-amd64-<ver>.tar.gz`（`package-device-linux.sh linux-amd64`）
- MVP 硬门槛裁定（DEC-001）：**路径 B 必挂**；路径 A 若 CI 已出则一并挂上。仅有 A 无 B 时，须在 Release 说明写明「无界面设备请用 A 内 `start-device.sh`」且 A 内必须含设备入口脚本——否则不合格。
- AC-003: 洁净 Linux amd64（无系统 Python 3.12 / 无 uv）解压路径 B（或合格的 A），`./open-device.sh` 或 `./start-device.sh` 可连默认域名并 enroll（测试可用可达的 staging；默认值仍为 `https://octop.effaf.me`）。
- AC-004: 包内 `VERSION.txt` 含 `octop_version` / platform；路径 B 含 `kind=headless-device-client`。

### REQ-003 — 默认 server 与 0006 对齐

- Requirement: 开箱包内 README / 向导默认 server = `https://octop.effaf.me`；可用 UI 高级项、`OCTOP_DEVICE_SERVER`、`--server` 覆盖。禁止把内网 IP 或 `111.228.42.228` 写为产品默认。
- AC-005: 干净 `device-state` 首次打开，预填域名为 `https://octop.effaf.me`。
- AC-006: README 主路径为「解压 → 双击/执行设备入口 → 登录」；CLI 示例在高级附录。

### REQ-004 — 产物布局与一键启动

**全功能便携 zip（package.sh）**

```text
Octop-<plat>/
  runtime/          # PBS CPython
  packages/         # site-packages
  launch.py
  start.sh | start.bat
  open.bat          # 管理端（若适用）
  open-device.sh|.bat
  start-device.sh|.bat
  setup-device.sh|.bat
  README.txt
  VERSION.txt
  data/             # 运行时创建；不得预置账号/密钥
```

公开文件名：`Octop-portable-<plat>-<version>.zip`。

**Linux 设备包（package-device-linux.sh）**

```text
Octop-device-linux-amd64/
  runtime/
  packages/         # 精简设备依赖
  launch.py
  open-device.sh
  start-device.sh
  setup-device.sh
  VERSION.txt
  README（或指向 linux-device/README）
```

公开文件名：`Octop-device-linux-amd64-<version>.tar.gz`（+ `.sha256`）。

- AC-007: 分发包 **不含** `device-state`、账号库、密钥、`.octopmove`、本机 home。
- AC-008: 一键入口：Win=`open-device.bat`；Linux 设备=`./open-device.sh`（无 GUI 可回落 `./start-device.sh` / `./setup-device.sh`）。

### REQ-005 — 版本号、changelog、校验

- Requirement: `<version>` = 根目录 `pyproject.toml` 的 `version`（当前示例 `1.0.2b6`）。GitHub Release tag = `v<version>`（或发布流程规定的 v*）。Release body 从 `CHANGELOG.md` 对应节提取（现有 `release.yml` 已有逻辑）；桌面包由 `octop-desktop.yml` upsert 到同一 Release。
- AC-009: 每个公开资产有同名 `.sha256` 或 Release 附 SHA256SUMS。
- AC-010: 资产文件名含 plat + version，与 `VERSION.txt` 一致。

### REQ-006 — CI 与本地打 Release 步骤

**本地（仓库根，Git Bash）**

```bash
# Win 主机打 Windows 全功能包
make -C . build-frontend   # 或 cd dashboard && npm ci && npm run build
bash desktop/portable/bootstrap-runtime.sh windows-amd64
bash desktop/portable/package.sh windows-amd64
# 产物：desktop/portable/release/Octop-portable-windows-amd64-<ver>.zip

# Linux amd64 设备包（原生 Linux 或 --docker）
bash desktop/portable/package-device-linux.sh linux-amd64
# 或：bash desktop/portable/package-device-linux.sh linux-amd64 --docker
# 产物：desktop/portable/release/Octop-device-linux-amd64-<ver>.tar.gz

# Linux 全功能包（推荐在 Linux/CI；交叉见 Makefile green-linux）
make -f desktop/portable/Makefile green GREEN_PLAT=linux-amd64
# 或：make -f desktop/portable/Makefile green-linux
```

**CI**

1. 推送 / 创建 `v*` tag → `release.yml` 建 GitHub Release（wheel / notes）。
2. 同 tag 触发 `octop-desktop.yml` → 多平台 `Octop-portable-*` 挂到同一 Release。
3. **缺口（Coder 切片）**：确保 `Octop-device-linux-amd64-*.tar.gz` 也进入同一 Release（扩 `octop-desktop.yml` job 或新增轻量 workflow / `workflow_dispatch` 组装后 softprops 上传）。
4. 手工补包：`octop-desktop.yml` → `workflow_dispatch` + `platforms` + `release_tag`（已有）。

- AC-011: 对某一 `v*`，Release 资产列表至少含 Win portable zip + Linux device tar.gz（或合格全功能 linux zip，见 REQ-002）。
- AC-012: PR 路径上 `octop-desktop.yml` 继续对 `linux-amd64,windows-amd64` 冒烟（现有 select-platforms 行为可保留）。

### REQ-007 — 开箱 enroll 验收（跨包）

- AC-013: Given 云中枢或 Tunnel 可达 `https://octop.effaf.me`（或测试覆盖域名），When 用户用 Release 包默认向导登录有效账号，Then 设备出现在同账号设备列表且可重连（无参 `start-device`）。
- AC-014: 失败时错误可读（网络/证书/账号）；默认路径无 `--allow-insecure`。

## Decisions

| ID | 决策 | State |
|----|------|-------|
| DEC-001 | Linux 硬门槛：Release 必含 linux-amd64 **设备包**（路径 B）；全功能 linux zip 若 CI 已出则同挂 | **resolved**（用户明确两边 ready-to-run；覆盖 0005 DEC-006 软门槛） |
| DEC-002 | MVP 验收平台仅 `windows-amd64` + `linux-amd64`；其余 plat CI 可保留非阻塞 | **resolved** |
| DEC-003 | 开箱主入口 = `open-device.*`（对齐 0006）；管理端 `open.bat`/`start.bat` 次要 | **resolved** |
| DEC-004 | 默认 server = `https://octop.effaf.me`；IP 仅 ops 文档 | **resolved**（0006 DEC-001） |
| DEC-005 | 复用 `package.sh` / `package-device-linux.sh` / `octop-desktop.yml`；禁止平行重写打包栈 | **resolved** |
| DEC-006 | Linux Release：**device tar.gz 必挂**（路径 B 硬门槛）；全功能 linux zip 有则同挂、PR 不阻塞缺 A | **resolved**（原 OQ-001；用户选「按建议」） |
| DEC-007 | 对外 GitHub Release 发到 **`CkEFFAF/Octopus`**；资产文件名保持 `Octop-portable-*` / `Octop-device-*`（不加 `octopus-` 前缀） | **resolved**（原 OQ-002；用户选「按建议」） |
| DEC-008 | 本里程碑 **不验** Wails `Octop-desktop-*`；不写入 AC；CI 若仍产出可附带非阻塞 | **resolved**（原 OQ-003；用户选「按建议」） |

## Open Questions（已关闭）

| ID | 问题 | 决议 | State |
|----|------|------|-------|
| OQ-001 | Linux Release 是否必须同时挂全功能 zip + device tar.gz？ | **device tar 必挂**；全功能 zip 有则挂、缺 A 不挡达标（与 DEC-001/DEC-006 一致） | **resolved** 2026-10-12 |
| OQ-002 | Release 发到哪一仓库？命名是否加前缀？ | 发到 **`CkEFFAF/Octopus`**；文件名保持现有 `Octop-portable-*` / `Octop-device-*` | **resolved** 2026-10-12 |
| OQ-003 | Wails `Octop-desktop-*` 是否写入本里程碑验收？ | **不验**；不纳入 AC；CI 附带即可 | **resolved** 2026-10-12 |


## OQ resolutions (manager 2026-10-12)

- **OQ-001**: Linux Release **must** attach `Octop-device-linux-amd64-*.tar.gz` (path B). Full-function linux zip may follow; not required to unblock S1+S2.
- **OQ-002**: Publish to **CkEFFAF/Octopus** (this product repo), not upstream. Keep existing `Octop-portable-*` / `Octop-device-*` filenames.
- **OQ-003**: Wails `Octop-desktop-*` is **out of** 0007 acceptance; CI may still attach.
- Default domain aligned with 0006: `https://octop.effaf.me`.

## Coder 实现指南

### 可写路径（允许）

- `desktop/portable/**`（README.txt 模板、确保设备入口脚本打进 zip/tar、默认 server 文案）
- `.github/workflows/octop-desktop.yml`（或新增 `octop-device-linux.yml`）— 挂载 `Octop-device-linux-amd64-*.tar.gz`
- `docs/octopus/run-and-build.md`、Release 说明片段、`CHANGELOG.md` 对应节（若发版）
- 测试：`tests/unit/test_green_launch.py` 及打包冒烟（若已有）
- **禁止**：改 Accepted `0004`；改 enroll API 语义；本任务不 `git commit`（除非总管另授）

### 切片顺序（建议）

| 序 | 切片 | 产出 | 验收命令 / 手法 |
|----|------|------|-----------------|
| **S0** | 盘点现状 | 确认 `package.sh` / `package-device-linux.sh` / CI 产物名与入口脚本已在包内 | 读脚本 + 一次本地 dry-run 列表 `release/` |
| **S1** | Win 开箱主路径 | README/`README.txt` 主路径改 `open-device.bat`；默认域名文案对齐 0006 | 洁净目录解压；无参启动见预填域名 |
| **S2** | Linux device 进 Release（**DEC-006 必挂**） | CI 增加 device-linux-amd64 构建并 upload 到 **`CkEFFAF/Octopus`** 同一 `v*` Release | Actions 对 `v*` 或 `workflow_dispatch` 资产列表含 `Octop-device-linux-amd64-*.tar.gz` |
| **S3** | SHA256 + Release notes 一句 | `.sha256` 与「Win+Linux 开箱」说明 | Release 页可见 |
| **S4** | 双端 enroll 手测 | Win zip + Linux tar → 连 `https://octop.effaf.me`（或 staging） | AC-001/003/013 清单打勾 |

**建议 Coder 先做：S1 + S2**（开箱文案与 Linux 资产入 Release）；S0 可 30 分钟内完成作前置。

### 验收命令（参考）

```bash
# 版本
sed -nE 's/^version[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' pyproject.toml | head -1

# Win（Git Bash）
bash desktop/portable/package.sh windows-amd64
ls -lh desktop/portable/release/Octop-portable-windows-amd64-*.zip

# Linux device
bash desktop/portable/package-device-linux.sh linux-amd64
ls -lh desktop/portable/release/Octop-device-linux-amd64-*.tar.gz*

# 导入冒烟（原生平台）
# 见 octop-desktop.yml「Smoke import」与 package-device-linux 内 verify
```

手测：解压 → `open-device` → 默认域名 → 账号密码 → Dashboard 见设备。

### 风险

| 风险 | 缓解 |
|------|------|
| Windows 上交叉打 Linux device 包无法原生 verify | CI 用 `ubuntu-latest` 跑 `package-device-linux.sh`；`VERSION.txt` 标记 verification |
| 全功能 linux zip 体积大、CI 慢 | MVP 硬门槛靠 device tar；全功能 zip 失败不挡 device 上传（job 分离） |
| 默认域名 Tunnel 未就绪导致手测失败 | 手测可临时 `OCTOP_DEVICE_SERVER` 指云机；**不得**把 IP 写回包内默认 |
| 与 0005 DEC-006 文档漂移 | 0005 Evolution 已交叉引用本规格；发布说明写「Linux 已升硬门槛」 |
| 误打包 `device-state`/密钥 | 保持现有 `.gitignore` / 打包排除；AC-007 检查清单 |

## 真实脚本与 CI 摸底（本修订时）

| 路径 | 作用 |
|------|------|
| `desktop/portable/package.sh` | 全平台 green zip；公开名 `Octop-portable-<plat>-<ver>.zip` |
| `desktop/portable/package-device-linux.sh` | Linux 无界面设备 `Octop-device-<plat>-<ver>.tar.gz` |
| `desktop/portable/package-linux-docker.sh` | 经 Docker 打 Linux 全功能包 |
| `desktop/portable/Makefile` | `green` / `green-linux` / `bootstrap` / `package` |
| `desktop/portable/bootstrap-runtime.sh` | PBS CPython |
| `desktop/portable/open-device.bat|.sh` | 0006 首次向导入口 |
| `desktop/portable/start-device.bat|.sh` | 连接/恢复 |
| `.github/workflows/octop-desktop.yml` | tag/PR/dispatch；挂 `Octop-portable-*`（及 desktop 壳）到 Release |
| `.github/workflows/release.yml` | PyPI + 创建 GitHub Release + changelog 节选 |

**已知缺口：** device-linux tar.gz **尚未**保证进入 `octop-desktop.yml` 的 Release attach（Coder S2）。

## Evolution

- 2026-10-12.1: 初稿 Proposed。用户明确 Win+Linux 两边 ready-to-run；覆盖 0005 Linux 软门槛；对齐 0006 默认域名；含 Coder 切片与 OQ。
- 2026-10-12.2: OQ 关闭（用户选「按建议」）→ **Accepted**。DEC-006 device tar 必挂；DEC-007 Release 发 `CkEFFAF/Octopus`；DEC-008 本里程碑不验 Wails。Coder 已派 S1+S2，切片表与决议对齐。REQ/AC ID 未改号。

