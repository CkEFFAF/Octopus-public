"""Owner-scoped organization selection shared by browsing and enqueueing."""

from __future__ import annotations

import json
import time
from typing import Any


def selection(
    owner: int,
    age: str = "all",
    status: str = "all",
    agent: str | None = None,
    *,
    batch: str | None = None,
) -> tuple[str, list[Any]]:
    job_join = "LEFT JOIN thread_metadata_jobs j ON j.id=x.latest_id "
    values: list[Any] = [owner]
    if batch is not None:
        job_join = (
            "JOIN thread_metadata_jobs j ON j.thread_id=t.thread_id "
            "AND j.owner_user_id=? AND j.request_json=? "
        )
        values.extend([owner, json.dumps({"batch_id": batch}, separators=(",", ":"))])
    sql = (
        "WITH last_jobs AS (SELECT thread_id,MAX(id) AS latest_id,"
        "MAX(CASE WHEN status='ready' THEN updated_at ELSE 0 END) AS succeeded_at "
        "FROM thread_metadata_jobs WHERE owner_user_id=? AND kind IN ('auto','brief') GROUP BY thread_id),"
        "records AS (SELECT t.thread_id,t.agent_id,t.user_id,t.title,a.name AS agent_name,"
        "CASE WHEN COALESCE(x.succeeded_at,0)>COALESCE(m.generated_at,0) THEN x.succeeded_at "
        "ELSE COALESCE(m.generated_at,0) END AS last_success_at,"
        "COALESCE(j.status,CASE WHEN m.generated_at>0 THEN 'ready' ELSE 'never' END) AS status,"
        "COALESCE(j.updated_at,0) AS last_attempt_at,COALESCE(j.error_code,'') AS error_code,"
        "COALESCE(j.result_json,'{}') AS result_json,j.job_id "
        ",COALESCE(c.status,CASE WHEN m.generated_at>0 THEN 'ready' ELSE 'never' END) AS latest_status "
        "FROM threads t JOIN agents a ON a.agent_id=t.agent_id "
        "LEFT JOIN thread_metadata m ON m.thread_id=t.thread_id "
        "LEFT JOIN last_jobs x ON x.thread_id=t.thread_id "
        "LEFT JOIN thread_metadata_jobs c ON c.id=x.latest_id "
        + job_join
        + "WHERE t.user_id=? AND t.channel_type!='cron_internal' AND (a.user_id=? OR a.is_shared=1)) "
        "SELECT * FROM records WHERE 1=1"
    )
    values.extend([owner, owner])
    if agent is not None:
        sql += " AND agent_id=?"
        values.append(agent)
    if status == "active":
        sql += " AND status IN ('queued','retry','running')"
    elif status != "all":
        sql += " AND status=?"
        values.append(status)
    now = time.time()
    if age == "never":
        sql += " AND last_success_at<=0"
    elif age != "all":
        sql += " AND last_success_at>0"
        bounds = {"d1": (0, 1), "d3": (1, 3), "d5": (3, 5), "d7": (5, 7), "older": (7, None)}
        lower, upper = bounds[age]
        sql += " AND last_success_at<=?"
        values.append(now - lower * 86400)
        if upper is not None:
            sql += " AND last_success_at>?"
            values.append(now - upper * 86400)
    return sql, values


def list_page(
    db: Any,
    owner: int,
    *,
    age: str,
    status: str,
    agent: str | None,
    offset: int,
    limit: int,
    batch: str | None = None,
) -> dict[str, Any]:
    sql, values = selection(owner, age, status, agent, batch=batch)
    with db.connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM ({sql}) selected", values).fetchone()[0]
        rows = conn.execute(
            sql + " ORDER BY last_attempt_at DESC,thread_id LIMIT ? OFFSET ?",
            [*values, limit, offset],
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item.pop("user_id")
        item["diagnostic"] = json.loads(item.pop("result_json")).get("diagnostic", {})
        items.append(item)
    return {"items": items, "total": total, "offset": offset, "limit": limit}
