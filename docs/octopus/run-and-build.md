# 开发与构建

Octopus 基于 TencentCloud/Octop 1.0.2b6，保留 Python/FastAPI、React、
SQLite/PostgreSQL 和既有 Wails 桌面壳。新增功能从当前源码构建，不能直接用
上游便携包替代。部署步骤见 [快速接入](quick-start.md)。

## 获取与开发

计划将功能分支发布为 `feature/octopus-device-network`；上游来源提交为
`4b17f1c`。发布前以本地工作区源码为准。
依赖与工程边界见根目录 `AGENTS.md`。需要 Python 3.12+、uv、Node.js/npm；
Makefile 使用 Bash，Windows 开发环境还需要 Git Bash 和 GNU Make。

```bash
uv sync --frozen
cd dashboard
npm ci
npm run build
cd ..
```

私有仓库需要你自己的 GitHub 授权。运行管理服务前按 Octop 首次向导创建
账号、配置模型；不要把生产管理端数据复制进源码树，也不要同时运行同一实例
的两份可写副本。

## 检查

```bash
make all PYTEST_JOBS=2
cd dashboard
npx tsc -b
npm test -- --maxWorkers=2 --minWorkers=1
npm run build
```

有界 worker 用于降低资源竞争，测试断言与覆盖范围不变。提交前启用
`make install-hooks`；钩子运行后端检查、受影响测试和 dashboard 构建。
新增设备网/任务看板的用例在 `tests/unit/devices`、`tests/unit/task_board`，
前端测试与组件相邻。真机连接、桌面权限、手机访问和重启恢复仍需要实际设备
验收；单元测试不替代这些行为。

## Windows 便携包

从 Git Bash 运行现有打包入口，首先构建 dashboard：

```bash
cd dashboard
npm run build
cd ..
bash desktop/portable/bootstrap-runtime.sh windows-amd64
bash desktop/portable/vendor-wheels.sh windows-amd64
bash desktop/portable/package.sh windows-amd64
```

输出默认位于 `desktop/portable/release`。运行时和依赖下载按项目打包脚本
校验，包内只包含程序，不包含账号、密钥或部署数据。管理端使用 `open.bat`
/ `start.bat`；设备端使用 `start-device.bat`。当前便携管理界面由浏览器打开，
不能把它表述为已经交付新的 Windows 原生登录窗口。

## Linux 无界面设备包

```bash
bash desktop/portable/package-device-linux.sh linux-amd64
# 在对应架构的构建/验证环境使用：
bash desktop/portable/package-device-linux.sh linux-arm64
```

这个包只包含设备连接依赖，无需 Web UI、账号库、X11 或完整 LLM 运行环境。
Windows Git Bash 可组装 Linux 包，脚本保留 tar 中 Linux 权限与符号链接；
跨平台组装不能替代目标架构原生验证。具体构建、后台服务和验收限制见
[Linux 设备包说明](../../desktop/portable/linux-device/README.md)。

Linux 完整管理宿主仍可使用上游的 `package.sh linux-amd64`，但当前部署选择
Windows 管理端 + Linux 无界面设备端。

## 发布与数据边界

源码保留上游许可证和归属，功能 PR 按仓库约定进入 `develop`；生产发布遵循
`release/*` → `main`。试用程序包放 Releases，源码分支与构建来源必须对应。
`release-*`、`.runtime`、`.cache`、`device-state`、数据库、密钥文件、迁移包
及本地验收证据都不进入 Git。部署数据迁移使用独立的加密迁移工具。
