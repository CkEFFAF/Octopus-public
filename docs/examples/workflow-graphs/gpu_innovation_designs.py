"""Freeze reviewed device design files and register a bounded batch with the queue.

Graph must bind review_output from the completed review node, reviewer_model and
authorized_scopes from fixed configuration. Files and hashes do not authenticate
the caller or prove that an arbitrary supplied model name was actually invoked.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from urllib.parse import quote


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True).encode("utf-8")


def immutable_json(path, value):
    content = encoded(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(content)
    except FileExistsError:
        if path.read_bytes() != content:
            raise ValueError("refusing to overwrite an existing design review file") from None


def load_queue():
    spec = spec_from_file_location(
        "gpu_design_queue", Path(__file__).with_name("gpu_innovation_queue.py")
    )
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ledger(queue):
    rows = {}
    offset = 0
    while True:
        page = queue.execute({"operation": "list", "offset": offset})
        rows.update((row["id"], row) for row in page["items"])
        offset = page["next_offset"]
        if offset is None:
            return rows


def text(value):
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def link(path, label):
    return f"[{label}]({quote(str(path).replace(chr(92), '/'), safe='/:')})" if path else "未登记"


def write_index(queue, items, results):
    rows = ledger(queue)
    rows.update((item["id"], {**rows.get(item["id"], {}), **item}) for item in items)
    outcome = {row["id"]: row for row in results}
    lines = [
        "# 实验设计索引",
        "",
        "执行状态以 TASK_QUEUE 和执行账本为准；设计链接不是启动许可。",
        "",
        "| 任务 | 设计版本 | 代码设计与实施步骤 | 高级评审 | 状态 |",
        "|---|---|---|---|---|",
    ]
    for identity, row in sorted(rows.items()):
        status = outcome.get(identity, {}).get("status", row.get("status", "needs_review"))
        reason = outcome.get(identity, {}).get("reason", "")
        lines.append(
            f"| {text(identity)} | {text(row.get('design_revision', ''))} | "
            f"{link(row.get('design_path'), '设计与步骤')} | "
            f"{link(row.get('design_review_path'), '评审')} | {text(status)} {text(reason)} |"
        )
    target = queue.DB.parent / "DESIGNS.md"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=target.parent,
        prefix="DESIGNS-",
        suffix=".tmp",
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        stream.write("\n".join(lines) + "\n")
    try:
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def register(queue, item, review, may_approve):
    identity = item["id"]
    old = ledger(queue).get(identity)
    if old is None:
        current = queue.execute({"operation": "propose", "item": item, "auto_approve": False})
    else:
        if old["status"] not in ("proposed", "approved"):
            raise ValueError(
                "existing item is claimed, executed or uncertain; use a new authorized task"
            )
        if old.get("design_revision") == item["design_revision"]:
            prior_review = json.loads(Path(old["design_review_path"]).read_bytes())
            if prior_review.get("design_sha256") != review["design_sha256"]:
                raise ValueError("design contents changed without a new design_revision")
        references = ("design_path", "design_revision", "design_review_path")
        ignored = {"allow_auto_descendants", *references}
        for key, value in item.items():
            if key not in ignored and old.get(key) != value:
                raise ValueError(f"existing proposal differs in {key}; cannot overwrite it")
        changed = any(old.get(key) != item[key] for key in references)
        current = old
        if old["status"] == "approved" and (changed or not may_approve):
            current = queue.execute(
                {"operation": "reopen", "id": identity, "revision": current["revision"]}
            )
        if changed:
            current = queue.execute(
                {
                    "operation": "revise",
                    "id": identity,
                    "revision": current["revision"],
                    **{key: item[key] for key in references},
                }
            )
    if may_approve and current["status"] == "proposed":
        current = queue.execute(
            {
                "operation": "approve",
                "id": identity,
                "revision": current["revision"],
                "allow_auto_descendants": item.get("allow_auto_descendants") is True,
            }
        )
    return {"id": identity, "status": current["status"], "review": review["verdict"]}


def execute(data, *, queue=None):
    queue = queue or load_queue()
    manifest_path = Path(queue.require_text(data, "manifest_path"))
    if not manifest_path.is_absolute():
        raise ValueError("manifest_path must be an absolute device path")
    manifest_bytes = manifest_path.read_bytes()
    if len(manifest_bytes) > 131072:
        raise ValueError("design manifest exceeds 128 KiB")
    manifest = json.loads(manifest_bytes)
    items = manifest.get("items") if isinstance(manifest, dict) else None
    if not isinstance(items, list) or len(items) > 10:
        raise ValueError("manifest must contain 0 to 10 proposal items")
    identities = [queue.require_text(item, "id") for item in items if isinstance(item, dict)]
    if len(identities) != len(items) or len(set(identities)) != len(items):
        raise ValueError("manifest items require unique task IDs")
    wrapper = data.get("review_output")
    result = wrapper.get("result") if isinstance(wrapper, dict) else None
    evidence = wrapper.get("evidence", wrapper) if isinstance(wrapper, dict) else None
    if not isinstance(result, dict) or not isinstance(evidence, dict):
        raise ValueError("completed review output and engine evidence are required")
    for key in ("delivery_id", "thread_id"):
        queue.require_text(evidence, key)
    reviewer = queue.require_text(data, "reviewer_model")
    reviews = result.get("reviews")
    if not isinstance(reviews, list) or len(reviews) > 10:
        raise ValueError("review result must contain at most 10 reviews")
    by_id = {}
    for review in reviews:
        if not isinstance(review, dict):
            raise ValueError("review entries must be objects")
        identity = queue.require_text(review, "task_id")
        if identity in by_id:
            raise ValueError("review task IDs must be unique")
        by_id[identity] = review
    scopes = data.get("authorized_scopes", [])
    if not isinstance(scopes, list) or any(
        not isinstance(scope, str) or not scope for scope in scopes
    ):
        raise ValueError("authorized_scopes must be a fixed list of scope names")
    validation_only = data.get("validation_only") is True
    record = {"reviewer_model": reviewer, "wrapper": wrapper, "validation_only": validation_only}
    digest = hashlib.sha256(encoded(record)).hexdigest()
    evidence_path = queue.DB.parent / "design-reviews" / (digest + ".json")
    immutable_json(evidence_path, record)
    results, indexed = [], []
    for source in items:
        item = {key: value for key, value in source.items() if key not in ("approved", "blockers")}
        identity = item["id"]
        try:
            design = Path(queue.require_text(item, "design_path"))
            version = queue.require_text(item, "design_revision")
            if not design.is_absolute():
                raise ValueError("design_path must be an absolute device path")
            design_hash = hashlib.sha256(design.read_bytes()).hexdigest()
            review = by_id.get(identity)
            if (
                not review
                or review.get("design_revision") != version
                or review.get("design_sha256") != design_hash
                or review.get("verdict") not in ("pending", "approved", "rejected")
            ):
                raise ValueError(
                    "review missing or does not match the actual design version and SHA256"
                )
            receipt = {
                "task_id": identity,
                "design_revision": version,
                "design_sha256": design_hash,
                "verdict": "pending" if validation_only else review["verdict"],
                "reviewer_model": reviewer,
                "review_evidence_path": str(evidence_path),
                "comments": review.get("comments", []),
                "validation_only": validation_only,
            }
            receipt_path = design.parent / (
                "REVIEW-" + hashlib.sha256(encoded(receipt)).hexdigest()[:24] + ".json"
            )
            immutable_json(receipt_path, receipt)
            item["design_review_path"] = str(receipt_path)
            may_approve = (
                not validation_only
                and source.get("approved") is True
                and not source.get("blockers")
                and item.get("scope") in scopes
                and review["verdict"] == "approved"
            )
            results.append(register(queue, item, receipt, may_approve))
        except (ValueError, OSError, sqlite3.Error, TypeError) as exc:
            results.append({"id": identity, "status": "needs_review", "reason": str(exc)[:120]})
        indexed.append(item)
    index_path = write_index(queue, indexed, results)
    output = {
        "ok": all(row["status"] != "needs_review" for row in results),
        "designs_path": str(index_path),
        "items": results,
    }
    if len(encoded(output)) > 8192:
        output["items"] = [{"id": str(row["id"])[:80], "status": row["status"]} for row in results]
        output["details_in_index"] = True
    if len(encoded(output)) > 8192:
        raise ValueError("design registration output exceeds 8 KiB; inspect DESIGNS.md")
    return output


if __name__ == "__main__":
    try:
        request = json.loads(os.environ.get("OCTOPUS_WORKFLOW_INPUT") or sys.stdin.read())
        response = execute(request)
        print(encoded(response).decode("utf-8"))
        sys.exit(0 if response["ok"] else 1)
    except (ValueError, OSError, sqlite3.Error, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
