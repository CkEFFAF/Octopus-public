# 0025：云设备 MCP 策略包 seed

云 MCP（如 `jdcloud-mon`）应写入 **设备** `capability_policy_json`，不要开账号 `default_open`。

## 管理台

设备详情 →「设备能力策略包」→ 选择 MCP → 保存（下一轮生效）。

## API

```http
PUT /devices/{device_id}/capability-policy
{"schema_version":1,"mcp_servers":["jdcloud-mon"]}

POST /devices/{device_id}/capability-policy/seed-mcp
{"mcp_servers":["jdcloud-mon"]}
```

## CLI（离线 / 运维）

```bash
uv run python scripts/seed_device_capability_mcp.py \
  --device-id main --device-id Y39HY4 --mcp jdcloud-mon
```

幂等；**不**批量改写专家 `mcp_servers`。
