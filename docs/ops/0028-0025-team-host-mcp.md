# 0028 × 0025：Team host 无 MCP 不变量

## 不变量（DEC-I03 / AC-I01）

`is_team_agent` → `_resolve_turn_mcp_servers` **必须**返回 `None`。下列来源**全部不能**注入 host：

1. 专家行 `agents.mcp_servers`
2. 账号连接器 `default_open`
3. Dashboard / 客户端显式 `mcp_servers` 列表
4. 设备 `capability_policy_json` 包（0025）

## 与 0025 的代码顺序

0025 在 `_resolve_turn_mcp_servers` 内于 team-host early return **之后**再取 `device_mcp_pack_for_turn`。合入 0025 时：

- **禁止**把设备包查找挪到 `team_host_blocks_mcp` 之前
- 回归：`tests/unit/isolation/test_team_host_mcp_invariant.py` 必须继续绿
- 0025 自身也声明 Non-goal：不改 team host「无 MCP」

本分支（0028）不 cherry-pick 0025；在当前 main 上用 mock 模拟设备包/default_open/显式名单攻击面，证明 early return 足够。
