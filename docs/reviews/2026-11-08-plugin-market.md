# Review, feature/plugin-market, 2026-11-08

**Reviewed by**: gpt-6-astra (author on gpt-6.1-sol)
**Scope**: 34 implementation/documentation/test files, uncommitted (`git diff HEAD` plus two new regression test files; excludes this report)
**Verdict**: Approve

## Summary
初审提出的配置并发、聊天浮条过期提示和验证错误回显问题均已修复，定向复审未发现新的阻塞或重大问题。当前实现以账号与插件为键保存单个记录，数据库条件写保证旧请求不能覆盖新配置或恢复已删除凭据。此结论针对代码审查；提交与部署仍应等待父任务正在运行的检查通过。

## Resolved findings

### 已解决 [P1] 并发保存恢复卸载或清除的凭据
初审位置为 `src/octop/infra/plugins/marketplace.py:198`。现已将安装、配置与快照合并到 `.state` 记录；`SettingsRepo.compare_and_set()` 使用单条条件 UPDATE 或 INSERT，保存失败返回冲突，不重试合并旧凭据。卸载删除整行；重装创建新的随机 generation，因此即使安装选项相同，旧记录也不可能匹配新记录。刷新先原子领取冷却，再仅针对该 pending 记录提交结果。

复审额外用原方法和可控交错运行“旧配置保存期间删除并重新安装”与“旧配置保存期间清除密钥”：两者均返回 409，最终 `key_configured=False`。结合实际 SQL 条件和新增仓储测试，确认已删除或清除的凭据不会被旧配置写入恢复。刷新同样比较含 generation 与配置的完整 pending 值，删除、重装、清除和更换密钥均使旧提交失效。

### 已解决 [P2] 聊天浮条未标记过期数据
初审位置为 `dashboard/src/pages/Plugins/CostMeterDock.tsx:13`。Dock 现在消费 hook 的连接错误和上游错误状态，显示更新失败而不是无标识的旧百分比；展开面板收到连接失败状态，保留旧快照并显示警告和重试。新增组件测试覆盖两类失败及正常状态。

### 已解决 [P2] 验证错误回显原始密钥输入
初审位置为 `src/octop/infra/plugins/models.py:65`。应用新增仅针对该敏感配置接口的 RequestValidationError 处理，响应仅保留 loc/type/msg，移除 input/ctx，并设置 `Cache-Control: no-store`；该配置区域的领域错误也设置 no-store。新增接口测试覆盖超长字符串、数组和对象输入，断言敏感输入不会进入响应。

## Strengths
- 用户 ID 只来自认证依赖；共享目录和私人安装状态分离，服务器插件权限仍独立。
- 固定 HTTPS 上游、禁止重定向、响应大小限制和错误正文隔离清晰；缺失配额与真实零值分开处理。
- 新增数据库 CAS 与敏感接口回归测试直接保护删除、并发及脱敏契约。

## Test coverage
已阅读原新增 pytest/Vitest 测试及本轮修复测试，未重复执行完整套件。初审的线程交错和密钥错误输入复现确认了原缺陷；复审的两个独立可控交错检查均通过。父任务负责完成正在运行的专项及整体检查。此次审查只修改本报告，没有修改实现、测试、Git 状态或部署。
