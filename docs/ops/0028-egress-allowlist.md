# 0028：管理端 Egress 允许名单（S0 骨架）

规格：`docs/specs/0028-execution-isolation.md`（DEC-I04）。S0 仅提供策略对象与检查钩子；**完整拦阻（AC-I04）在 S1**。

## 配置

环境变量之一：

- `OCTOP_EGRESS_ALLOWLIST_JSON='{"enabled":true,"allow_hosts":["api.example.com"],"allow_suffixes":["openai.com"]}'`
- `OCTOP_EGRESS_ALLOWLIST_PATH=/etc/octop/egress-allowlist.json`

示例 JSON：

```json
{
  "enabled": true,
  "allow_hosts": ["updates.example.com"],
  "allow_suffixes": ["openai.com", "anthropic.com"],
  "deny_private": true,
  "notes": "management-plane only"
}
```

## API

```python
from octop.infra.isolation import (
    load_egress_policy_from_env,
    is_management_egress_allowed,
)

policy = load_egress_policy_from_env()
assert is_management_egress_allowed("https://api.openai.com/v1", policy=policy)
```

未启用（默认）时检查恒为通过，避免打断现有出站。专家工具出口仍走设备 grant / 命令 guard。

## S1 待办

- 将钩子接到管理端 HTTP 客户端（更新源探测、模型提供商探测等）
- 测桩：名单外域名被拦或告警（AC-I04）
