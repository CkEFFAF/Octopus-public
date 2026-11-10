"""Graph Agent nodes use the actual server delivery and conversation history path."""

import asyncio

from tests.support.app import octop_client
from tests.support.auth import auth_header, bootstrap_admin, create_agent, seed_openai_provider
from tests.support.fakes import FakeHarnessAgent


async def test_agent_graph_uses_canonical_delivery_and_retains_separate_child_history(tmp_path):
    home = tmp_path / "graph-home"
    fake = FakeHarnessAgent(
        chunks=[{"type": "token", "content": "Analyze the supplied evidence: verified"}]
    )
    async with octop_client(home, fake_agent=fake) as (client, server):
        await bootstrap_admin(client, home)
        auth = await auth_header(client)
        await seed_openai_provider(client, auth)
        agent = await create_agent(client, auth, name="Graph expert")
        definition = {
            "name": "Analyze a result",
            "agent_id": agent,
            "nodes": [
                {"id": "entry", "kind": "entry", "label": "Start"},
                {
                    "id": "analyze",
                    "kind": "agent",
                    "label": "Analyze",
                    "prompt": "Analyze the supplied evidence.",
                    "context": {
                        "before": {"session": "new", "history": "empty"},
                        "after": {"session": "restore", "context": "keep"},
                    },
                },
                {"id": "end", "kind": "end", "label": "End"},
            ],
            "edges": [
                {"id": "a", "source": "entry", "target": "analyze"},
                {"id": "b", "source": "analyze", "target": "end"},
            ],
        }
        response = await client.put(
            "/api/workflow-graphs",
            headers=auth,
            json={"graph_id": "analysis", "revision": 0, "definition": definition},
        )
        assert response.status_code == 200, response.text
        assert (
            await client.post(
                "/api/workflow-graphs/analysis/publish", headers=auth, json={"revision": 1}
            )
        ).status_code == 200
        response = await client.post(
            "/api/workflow-graphs/analysis/start", headers=auth, json={"request_id": "once"}
        )
        assert response.status_code == 200, response.text
        run = response.json()
        service = server.app_runtime.workflow_graphs
        for _ in range(8):
            await service.tick()
            if service.runner.tasks:
                await asyncio.wait_for(asyncio.gather(*list(service.runner.tasks.values())), 10)
            await asyncio.sleep(0)
        result = (await client.get(f"/api/workflow-graphs/runs/{run['id']}", headers=auth)).json()
        assert result["status"] == "succeeded", result
        rows = service.store.activations(1, run["id"])
        detail = (
            await client.get(f"/api/workflow-graphs/activations/{rows[1]['id']}", headers=auth)
        ).json()
        assert "Analyze the supplied evidence" in detail["output"]["text"]
        child = detail["before"]["thread_id"]
        parent = detail["after"]["conversation"]["thread_id"]
        assert child != parent
        assert detail["after"]["conversation"]["recipe"]["history"] == "empty"
        with server.services.repos.db.connect() as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM thread_messages WHERE thread_id=?", (child,)
                ).fetchone()[0]
                >= 2
            )
        attempts = server.services.repos.cron_attempt_repo.listing(1, agent, "graph-" + run["id"])[
            "items"
        ]
        assert len(attempts) == 1 and attempts[0]["status"] == "completed"
