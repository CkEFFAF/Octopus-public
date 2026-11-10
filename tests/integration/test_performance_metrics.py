from __future__ import annotations

from typing import Any


async def test_performance_measurements_require_admin_console(env: Any) -> None:
    client, _server, auth = env
    response = await client.get("/api/admin/performance")
    assert response.status_code in {401, 403}
    response = await client.get("/api/admin/performance", headers=auth)
    assert response.status_code == 200
    value = response.json()
    assert value["scope"] == "process"
    assert value["window_size"] == 512
    assert "mcp_wait" in value["durations"]
    assert "gateway_schema" in value["caches"]
