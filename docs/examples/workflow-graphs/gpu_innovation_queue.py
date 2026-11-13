"""Transactional device-side queue for approved research proposals.

Input is a JSON object in OCTOPUS_WORKFLOW_INPUT (or stdin for operators).
The wrapper records real process results; comparable metric files determine outcome.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

DB = Path(
    os.environ.get("GPU_INNOVATION_QUEUE", "/home/wjh/workspace/gpu-innovation/queue.sqlite3")
)


def require_text(obj, key):
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def inspect_design(item, *, approved=False, frozen=False):
    """Check device files and recorded review evidence; this does not authenticate its author."""
    design_path = Path(require_text(item, "design_path"))
    review_path = Path(require_text(item, "design_review_path"))
    version = require_text(item, "design_revision")
    identity = require_text(item, "id")
    if not design_path.is_absolute() or not review_path.is_absolute():
        raise ValueError("design and review paths must be absolute device paths")
    try:
        design_bytes = design_path.read_bytes()
        review_bytes = review_path.read_bytes()
        design = design_bytes.decode("utf-8")
        review = json.loads(review_bytes)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"design or review file unavailable or invalid: {exc}") from exc
    if not isinstance(review, dict):
        raise ValueError("review receipt must be a JSON object")
    design_hash = hashlib.sha256(design_bytes).hexdigest()
    review_hash = hashlib.sha256(review_bytes).hexdigest()
    for label, value in (("任务编号", identity), ("设计版本", version)):
        if not re.search(rf"(?m)^\s*{label}\s*[:：]\s*{re.escape(value)}\s*$", design):
            raise ValueError(f"design must identify {label} as {value}")
    for heading in ("代码设计", "实施步骤", "评估验收", "依赖/风险/资源"):
        match = re.search(rf"(?m)^##\s+{re.escape(heading)}\s*$", design)
        if not match:
            raise ValueError(f"design missing section: {heading}")
        section = re.split(r"(?m)^##\s+", design[match.end() :], maxsplit=1)[0]
        if not section.strip():
            raise ValueError(f"design section is empty: {heading}")
    if (
        review.get("task_id") != identity
        or review.get("design_revision") != version
        or review.get("design_sha256") != design_hash
    ):
        raise ValueError("review does not match task, version or design hash")
    verdict = review.get("verdict")
    if verdict not in ("pending", "approved", "rejected"):
        raise ValueError("review verdict must be pending, approved or rejected")
    evidence_hash = None
    if verdict == "approved":
        require_text(review, "reviewer_model")
        evidence = Path(require_text(review, "review_evidence_path"))
        if not evidence.is_absolute():
            raise ValueError("review evidence path must be an absolute device path")
        try:
            evidence_bytes = evidence.read_bytes()
        except OSError as exc:
            raise ValueError(f"review evidence unavailable: {exc}") from exc
        if not evidence_bytes:
            raise ValueError("review evidence must not be empty")
        evidence_hash = hashlib.sha256(evidence_bytes).hexdigest()
    if approved and verdict != "approved":
        raise ValueError("design review must be approved before execution")
    hashes = {
        "design_sha256": design_hash,
        "design_review_sha256": review_hash,
        "review_evidence_sha256": evidence_hash,
    }
    if frozen and any(item.get(key) != value for key, value in hashes.items()):
        raise ValueError("design, review or evidence changed; review and approval required")
    return verdict, hashes


def review_status(row):
    try:
        verdict, _ = inspect_design(
            row,
            approved=row.get("status") in ("approved", "claimed", "running"),
            frozen=row.get("status") in ("approved", "claimed", "running"),
        )
        return verdict
    except ValueError:
        return "needs_review"


def capacity():
    """Only admit an apparently idle GPU0; unknown observations mean wait."""
    try:
        gpus = (
            subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=index,uuid,memory.used",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            .stdout.strip()
            .splitlines()
        )
        entries = [line.split(",") for line in gpus]
        if len(entries) < 2 or any(len(parts) != 3 for parts in entries):
            return False
        gpu0 = next((parts for parts in entries if parts[0].strip() == "0"), None)
        if gpu0 is None or int(gpu0[2].strip()) != 0:
            return False
        processes = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=gpu_uuid,pid", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        return not any(
            line.split(",")[0].strip() == gpu0[1].strip() for line in processes.splitlines()
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def write_indexes(rows):
    queue_lines = ["# Experiment queue", ""]
    report_lines = ["# Experiment reports", ""]
    for row in sorted(rows.values(), key=lambda value: value["id"]):
        queue_lines.append(
            f"- {row['id']}: {row['status']} (revision {row['revision']}; design {row.get('design_revision', 'missing')}; review {review_status(row)})"
        )
        for label, key in (("design", "design_path"), ("review", "design_review_path")):
            if row.get(key):
                link = quote(str(row[key]).replace("\\", "/"), safe="/:")
                queue_lines.append(f"  - [{label}]({link})")
        if row.get("report_path"):
            report_link = quote(str(row["report_path"]).replace("\\", "/"), safe="/:")
            report_lines.append(
                f"- [{row['id']}]({report_link}) ({row.get('outcome', 'unassessed')})"
            )
        else:
            report_lines.append(f"- {row['id']}: no report")
        for label, key in (("design", "design_path"), ("review", "design_review_path")):
            if row.get(key):
                link = quote(str(row[key]).replace("\\", "/"), safe="/:")
                report_lines.append(f"  - [{label}]({link})")
    for name, lines in (("QUEUE.md", queue_lines), ("REPORTS.md", report_lines)):
        target = DB.parent / name
        temporary = target.with_name(name + ".tmp")
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(temporary, target)


def refresh(db):
    rows = {
        r[0]: {"id": r[0], "revision": r[1], "status": r[2], **json.loads(r[3])}
        for r in db.execute("SELECT id,revision,status,payload FROM items")
    }
    write_indexes(rows)


def claim_record(data):
    identity = require_text(data, "id")
    token = require_text(data, "claim_token")
    with closing(sqlite3.connect(DB, timeout=30)) as db:
        row = db.execute(
            "SELECT revision,status,payload FROM items WHERE id=?", (identity,)
        ).fetchone()
    if row is None:
        raise ValueError("unknown claim")
    revision, status, encoded = row
    payload = json.loads(encoded)
    if (
        status != "claimed"
        or revision != data.get("revision")
        or not secrets.compare_digest(str(payload.get("claim_token", "")), token)
    ):
        raise ValueError("claim identity, revision or token conflict")
    return {"id": identity, "revision": revision, "status": status, **payload}


def preparation_receipt_path(identity, revision):
    digest = hashlib.sha256(identity.encode()).hexdigest()
    return DB.parent / "preparation" / f"{digest}-{revision}.json"


def admission_rejection(item, status, reason):
    path = preparation_receipt_path(item["id"], item["revision"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "task_id": item["id"],
                "revision": item["revision"],
                "status": status,
                "reason": reason,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {
        "claimed": False,
        "status": status,
        "id": item["id"],
        "revision": item["revision"],
        "receipt": str(path),
    }


def check_manifest(preparation):
    path = Path(require_text(preparation, "implementation_manifest_path"))
    expected = require_text(preparation, "implementation_manifest_sha256")
    if not path.is_absolute():
        raise ValueError("implementation manifest path must be absolute")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected:
        raise ValueError("implementation manifest changed")
    manifest = json.loads(content)
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, list) or not files:
        raise ValueError("implementation manifest requires files")
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("invalid implementation manifest file")
        target = Path(require_text(entry, "path"))
        if not target.is_absolute() or hashlib.sha256(
            target.read_bytes()
        ).hexdigest() != require_text(entry, "sha256"):
            raise ValueError("implementation file missing or changed")
    return expected


def run_prepared(data):
    item = claim_record(data)
    if data.get("validation_only") is True:
        return admission_rejection(item, "review_required", "validation mode cannot run experiments")
    try:
        inspect_design(item, approved=True, frozen=True)
    except ValueError as exc:
        return admission_rejection(item, "review_required", f"design review invalid: {exc}")
    preparation = data.get("preparation")
    if (
        not isinstance(preparation, dict)
        or preparation.get("prepared") is not True
        or preparation.get("id") != item["id"]
        or preparation.get("revision") != item["revision"]
    ):
        return admission_rejection(
            item, "preparation_failed", "preparation did not confirm the claimed task and revision"
        )
    try:
        manifest_hash = check_manifest(preparation)
    except (OSError, ValueError, TypeError) as exc:
        return admission_rejection(
            item, "preparation_failed", f"invalid implementation manifest: {exc}"
        )
    wrapper = data.get("code_review_output")
    review = wrapper.get("result") if isinstance(wrapper, dict) else None
    evidence = wrapper.get("evidence") if isinstance(wrapper, dict) else None
    reviewer_model = data.get("reviewer_model")
    if (
        not isinstance(review, dict)
        or not isinstance(evidence, dict)
        or not isinstance(reviewer_model, str)
        or not reviewer_model.strip()
        or not isinstance(evidence.get("delivery_id"), str)
        or not evidence["delivery_id"].strip()
        or not isinstance(evidence.get("thread_id"), str)
        or not evidence["thread_id"].strip()
        or review.get("approved") is not True
        or review.get("task_id") != item["id"]
        or review.get("revision") != item["revision"]
        or review.get("design_sha256") != item["design_sha256"]
        or review.get("implementation_manifest_sha256") != manifest_hash
    ):
        return admission_rejection(
            item,
            "review_required",
            "code review missing, rejected, or does not match the claimed task and reviewed files",
        )
    evidence_path = preparation_receipt_path(item["id"], item["revision"]).with_suffix(
        ".review.json"
    )
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(
            {"reviewer_model": reviewer_model, "wrapper": wrapper},
            ensure_ascii=False,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    while True:
        item = claim_record(data)
        try:
            inspect_design(item, approved=True, frozen=True)
            if check_manifest(preparation) != manifest_hash:
                raise ValueError("implementation manifest changed")
        except (OSError, ValueError, TypeError) as exc:
            return admission_rejection(
                item, "review_required", f"reviewed implementation changed: {exc}"
            )
        result = execute(
            {
                "operation": "run",
                "id": item["id"],
                "revision": item["revision"],
                "claim_token": data["claim_token"],
                "implementation_manifest": preparation,
            }
        )
        if (
            result.get("reason") != "capacity_unavailable"
            or data.get("wait_for_capacity") is not True
        ):
            result["code_review_evidence_path"] = str(evidence_path)
            return result
        time.sleep(60)


def archive(data):
    identity = require_text(data, "id")
    analysis = data.get("analysis")
    if not isinstance(analysis, dict) or analysis.get("ready") is not True:
        return {"status": "manual_review", "id": identity}
    with closing(sqlite3.connect(DB, timeout=30)) as db:
        row = db.execute(
            "SELECT revision,status,payload FROM items WHERE id=?", (identity,)
        ).fetchone()
    if row is None or row[0] != data.get("revision"):
        raise ValueError("archive identity or revision conflict")
    revision, status, encoded = row
    payload = json.loads(encoded)
    request = {
        "id": identity,
        "revision": revision,
        "receipt": analysis.get("receipt"),
        "report_path": analysis.get("report_path"),
    }
    if status == "ran":
        request.update(operation="finish", metric_path=analysis.get("metric_path"))
    elif status == "failed" and isinstance(payload.get("execution"), dict):
        request["operation"] = "report_failure"
    elif status == "claimed":
        item = claim_record(data)
        path = preparation_receipt_path(identity, revision)
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"status": "manual_review", "id": identity}
        if (
            not isinstance(receipt, dict)
            or receipt.get("task_id") != item["id"]
            or receipt.get("revision") != revision
            or receipt.get("status") not in ("preparation_failed", "review_required")
            or analysis.get("receipt") != str(path)
        ):
            return {"status": "manual_review", "id": identity}
        request["operation"] = "fail"
    else:
        return {"status": "manual_review", "id": identity}
    try:
        return execute(request)
    except (ValueError, OSError):
        return {"status": "manual_review", "id": identity}


def execute(data):
    operation = require_text(data, "operation")
    if operation == "claim" and data.get("validation_only") is True:
        return {"claimed": False, "reason": "validation_only"}
    if operation == "run_prepared":
        return run_prepared(data)
    if operation == "archive":
        return archive(data)
    DB.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DB, timeout=30, isolation_level=None)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(
            "CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        db.execute("BEGIN IMMEDIATE")
        rows = {
            r[0]: {"id": r[0], "revision": r[1], "status": r[2], **json.loads(r[3])}
            for r in db.execute("SELECT id,revision,status,payload FROM items")
        }
        write_indexes(rows)
        if operation in ("list", "summary"):
            refresh(db)
            db.commit()
            visible = [
                {k: v for k, v in row.items() if k != "claim_token"} for row in rows.values()
            ]
            for row in visible:
                row["design_review_status"] = review_status(row)
            if operation == "summary":
                active = [
                    row
                    for row in visible
                    if row["status"] in ("approved", "claimed", "running", "unknown", "ran")
                ]
                recent = [row for row in visible if row not in active][-10:]
                selected = (active + recent)[:8]
                summary = {
                    "total": len(visible),
                    "truncated": len(active) + len(recent) > len(selected),
                    "items": [
                        {
                            key: str(row.get(key, ""))[:60]
                            if key not in ("revision", "priority")
                            else row.get(key)
                            for key in (
                                "id",
                                "status",
                                "revision",
                                "priority",
                                "previous",
                                "hypothesis",
                                "outcome",
                                "report_path",
                                "scope",
                                "design_path",
                                "design_revision",
                                "design_review_path",
                                "design_review_status",
                            )
                        }
                        for row in selected
                    ],
                    "queue_path": str(DB.parent / "QUEUE.md"),
                    "reports_path": str(DB.parent / "REPORTS.md"),
                }
                if any(
                    len(str(row.get(key, ""))) > 60
                    for row in selected
                    for key in (
                        "id",
                        "previous",
                        "hypothesis",
                        "report_path",
                        "scope",
                        "design_path",
                        "design_revision",
                        "design_review_path",
                    )
                ):
                    summary["truncated"] = True
                summary["details_operation"] = "list"
                while (
                    summary["items"]
                    and len(json.dumps(summary, ensure_ascii=False).encode("utf-8")) > 8192
                ):
                    summary["items"].pop()
                    summary["truncated"] = True
                return summary
            offset = data.get("offset", 0)
            if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
                raise ValueError("offset must be nonnegative")
            return {
                "items": visible[offset : offset + 10],
                "total": len(visible),
                "next_offset": offset + 10 if offset + 10 < len(visible) else None,
            }
        if operation == "propose":
            item = data.get("item")
            if not isinstance(item, dict):
                raise ValueError("item is required")
            if len(json.dumps(item, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 8192:
                raise ValueError("proposal exceeds 8192 UTF-8 bytes; store details in a file")
            identity = require_text(item, "id")
            if len(identity) > 80 or any(
                c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
                for c in identity
            ):
                raise ValueError("id must be at most 80 letters, digits, underscores or hyphens")
            if identity in rows:
                raise ValueError("item already exists")
            for key in (
                "hypothesis",
                "rationale",
                "baseline",
                "metric",
                "direction",
                "candidate_version",
            ):
                require_text(item, key)
            if item["direction"] not in ("maximize", "minimize"):
                raise ValueError("direction must be maximize or minimize")
            threshold = item.get("threshold")
            if (
                isinstance(threshold, bool)
                or not isinstance(threshold, (int, float))
                or not math.isfinite(threshold)
                or threshold < 0
            ):
                raise ValueError("a finite nonnegative threshold is required")
            dependencies = item.get("dependencies", [])
            if (
                not isinstance(dependencies, list)
                or len(dependencies) != len(set(dependencies))
                or any(not isinstance(v, str) or v not in rows for v in dependencies)
            ):
                raise ValueError("dependencies must be unique existing item IDs")
            previous = item.get("previous")
            if previous is not None and previous not in rows:
                raise ValueError("previous must identify an existing item")
            argv = item.get("argv")
            if (
                not isinstance(argv, list)
                or not argv
                or any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in argv)
            ):
                raise ValueError("argv must be a nonempty list of strings")
            require_text(item, "cwd")
            priority = item.get("priority", 0)
            if (
                isinstance(priority, bool)
                or not isinstance(priority, int)
                or not -1000000 <= priority <= 1000000
            ):
                raise ValueError("priority must be an integer between -1000000 and 1000000")
            verdict, design_hashes = inspect_design(item)
            payload = {
                k: v
                for k, v in item.items()
                if k
                not in (
                    "id",
                    "status",
                    "revision",
                    "allow_auto_descendants",
                    "design_sha256",
                    "design_review_sha256",
                    "review_evidence_sha256",
                )
            }
            parent = rows.get(previous) if previous else None
            auto = bool(
                parent
                and parent["status"] in ("succeeded", "failed")
                and parent.get("allow_auto_descendants") is True
                and item.get("scope")
                and item.get("scope") == parent.get("scope")
                and verdict == "approved"
                and data.get("auto_approve") is not False
            )
            if auto:
                payload["allow_auto_descendants"] = True
                payload.update(design_hashes)
            initial_status = "approved" if auto else "proposed"
            db.execute(
                "INSERT INTO items VALUES (?,0,?,?)",
                (identity, initial_status, json.dumps(payload, ensure_ascii=False)),
            )
            refresh(db)
            db.commit()
            return {"id": identity, "revision": 0, "status": initial_status}
        if operation == "capacity":
            refresh(db)
            db.commit()
            return {"available": capacity()}
        if operation in ("claim", "run"):
            if operation == "claim":
                if not capacity():
                    refresh(db)
                    db.commit()
                    return {"claimed": False, "reason": "capacity_unavailable"}
                eligible = [
                    v
                    for v in rows.values()
                    if v["status"] == "approved"
                    and all(rows[d]["status"] == "succeeded" for d in v.get("dependencies", []))
                ]
                if not eligible or any(
                    v["status"] in ("claimed", "running", "unknown", "ran") for v in rows.values()
                ):
                    refresh(db)
                    db.commit()
                    return {"claimed": False}
                blocked = []
                item = None
                for candidate in sorted(eligible, key=lambda v: (-v.get("priority", 0), v["id"])):
                    try:
                        inspect_design(candidate, approved=True, frozen=True)
                    except ValueError as exc:
                        blocked.append({"id": candidate["id"], "reason": str(exc)[:300]})
                        continue
                    item = candidate
                    break
                if item is None:
                    refresh(db)
                    db.commit()
                    return {
                        "claimed": False,
                        "reason": "design_review_required",
                        "blocked": blocked[:8],
                    }
                token = secrets.token_urlsafe(24)
                payload = {k: v for k, v in item.items() if k not in ("id", "status", "revision")}
                payload["claim_token"] = token
                db.execute(
                    "UPDATE items SET status='claimed', revision=revision+1, payload=? WHERE id=? AND revision=? AND status='approved'",
                    (json.dumps(payload, ensure_ascii=False), item["id"], item["revision"]),
                )
                refresh(db)
                db.commit()
                item = {**item, "status": "claimed", "revision": item["revision"] + 1}
                return {"claimed": True, "item": item, "claim_token": token}
            identity = require_text(data, "id")
            token = require_text(data, "claim_token")
            item = rows.get(identity)
            if (
                not item
                or item["status"] != "claimed"
                or item["revision"] != data.get("revision")
                or not secrets.compare_digest(str(item.get("claim_token", "")), token)
            ):
                raise ValueError("claim identity, revision or token conflict")
            inspect_design(item, approved=True, frozen=True)
            if not capacity():
                refresh(db)
                db.commit()
                return {"claimed": False, "reason": "capacity_unavailable"}
            refresh(db)
            db.commit()
            log_dir = DB.parent / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            # Never interpret an item ID as a filesystem path.
            log_path = log_dir / (hashlib.sha256(item["id"].encode()).hexdigest() + ".log")
            started = time.time()
            env = dict(os.environ, CUDA_VISIBLE_DEVICES="0")
            # Keep the same claim if capacity changes before launch.
            if not capacity():
                return {"claimed": False, "reason": "capacity_unavailable"}
            with closing(sqlite3.connect(DB, timeout=30, isolation_level=None)) as admission:
                admission.execute("BEGIN IMMEDIATE")
                inspect_design(item, approved=True, frozen=True)
                if data.get("implementation_manifest") is not None:
                    try:
                        check_manifest(data["implementation_manifest"])
                    except (OSError, ValueError, TypeError) as exc:
                        return admission_rejection(
                            item, "review_required", f"reviewed implementation changed: {exc}"
                        )
                changed = admission.execute(
                    "UPDATE items SET status='running',revision=revision+1 WHERE id=? AND status='claimed' AND revision=?",
                    (identity, item["revision"]),
                )
                if changed.rowcount != 1:
                    raise ValueError("claim already admitted")
                refresh(admission)
                admission.commit()
            item["revision"] += 1
            status_path = DB.parent / "STATUS.md"
            launch_error = None
            with log_path.open("xb") as log:
                try:
                    proc = subprocess.Popen(
                        item["argv"], cwd=item["cwd"], env=env, stdout=log, stderr=subprocess.STDOUT
                    )
                except OSError as exc:
                    launch_error = f"{type(exc).__name__}: {exc}"
                    log.write((launch_error + "\n").encode("utf-8", errors="replace"))
                    returncode = None
                else:
                    while True:
                        with log_path.open("rb") as reader:
                            reader.seek(0, 2)
                            reader.seek(max(0, reader.tell() - 16384))
                            tail = reader.read().decode("utf-8", errors="replace").splitlines()
                        progress = [
                            line
                            for line in tail
                            if "epoch" in line.lower() or "eval:" in line.lower()
                        ][-8:]
                        status_path.write_text(
                            f"# Running experiment\n\n{item['id']} (PID {proc.pid}); live log: {log_path}\n\n```\n"
                            + "\n".join(progress)
                            + "\n```\n",
                            encoding="utf-8",
                        )
                        try:
                            returncode = proc.wait(timeout=60)
                            break
                        except subprocess.TimeoutExpired:
                            pass
            status_detail = (
                f"launch failed: {launch_error}" if launch_error else f"exit {returncode}"
            )
            status_path.write_text(
                f"# Last experiment\n\n{item['id']}: {status_detail}; log: {log_path}\n",
                encoding="utf-8",
            )
            with closing(sqlite3.connect(DB, timeout=30, isolation_level=None)) as update:
                update.execute("BEGIN IMMEDIATE")
                payload = {k: v for k, v in item.items() if k not in ("id", "status", "revision")}
                payload["execution"] = {
                    "argv_sha256": hashlib.sha256(
                        json.dumps(item["argv"], ensure_ascii=False).encode()
                    ).hexdigest(),
                    "started": started,
                    "finished": time.time(),
                    "returncode": returncode,
                    "process_started": launch_error is None,
                    "log_path": str(log_path),
                }
                if launch_error is not None:
                    payload["execution"]["launch_error"] = launch_error
                status = "ran" if returncode == 0 else "failed"
                changed = update.execute(
                    "UPDATE items SET revision=revision+1,status=?,payload=? WHERE id=? AND revision=? AND status='running'",
                    (status, json.dumps(payload, ensure_ascii=False), item["id"], item["revision"]),
                )
                if changed.rowcount != 1:
                    raise ValueError("execution state changed during run")
                refresh(update)
                update.commit()
            return {
                "claimed": True,
                "id": item["id"],
                "revision": item["revision"] + 1,
                "status": status,
                "execution": payload["execution"],
            }
        identity = require_text(data, "id")
        item = rows.get(identity)
        if item is None:
            raise ValueError("unknown item")
        revision = data.get("revision")
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision != item["revision"]
        ):
            raise ValueError("revision conflict")
        transitions = {
            "approve": ("proposed", "approved"),
            "unknown": ("claimed", "unknown"),
            "finish": ("ran", "succeeded"),
            "report_failure": ("failed", "failed"),
            "fail": ("claimed", "failed"),
        }
        if operation == "revise" and item["status"] == "proposed":
            transitions["revise"] = ("proposed", "proposed")
        if operation == "reopen" and item["status"] in ("approved", "claimed"):
            if item["status"] == "claimed" and not secrets.compare_digest(
                str(item.get("claim_token", "")), require_text(data, "claim_token")
            ):
                raise ValueError("claim token required to reopen")
            transitions["reopen"] = (item["status"], "proposed")
        if operation == "unknown" and item["status"] == "running":
            transitions["unknown"] = ("running", "unknown")
        if operation == "fail" and item["status"] in ("running", "unknown"):
            if data.get("confirmed_stopped") is not True:
                raise ValueError(
                    "reconcile the actual device Job and explicitly confirm it stopped"
                )
            for key in ("receipt", "report_path"):
                if not Path(require_text(data, key)).is_file():
                    raise ValueError("reconciliation requires existing receipt and report files")
            transitions["fail"] = (item["status"], "failed")
        if operation not in transitions or item["status"] != transitions[operation][0]:
            raise ValueError("invalid transition")
        payload = {k: v for k, v in item.items() if k not in ("id", "status", "revision")}
        if operation == "revise":
            for key in ("design_path", "design_revision", "design_review_path"):
                payload[key] = require_text(data, key)
            inspect_design({"id": identity, **payload})
        if operation == "reopen":
            for key in (
                "claim_token",
                "design_sha256",
                "design_review_sha256",
                "review_evidence_sha256",
            ):
                payload.pop(key, None)
        if operation == "approve":
            _, hashes = inspect_design(item, approved=True)
            payload.update(hashes)
        if operation == "approve" and data.get("allow_auto_descendants") is True:
            require_text(payload, "scope")
            payload["allow_auto_descendants"] = True
        if operation in ("finish", "fail", "report_failure"):
            for key in ("receipt", "report_path"):
                payload[key] = require_text(data, key)
                if not Path(payload[key]).is_file():
                    raise ValueError("receipt and report must be existing device files")
            if operation in ("finish", "report_failure"):
                execution = payload.get("execution", {})
                if payload["receipt"] != execution.get("log_path"):
                    raise ValueError("receipt must reference this execution log")
                if (
                    not Path(payload["receipt"]).is_file()
                    or not Path(payload["report_path"]).is_file()
                ):
                    raise ValueError("receipt and report must be existing device files")
                if operation == "finish":
                    if execution.get("returncode") != 0:
                        raise ValueError("execution was not successful")
                    metric_path = require_text(data, "metric_path")
                    payload["metric_path"] = metric_path
                    try:
                        candidate = json.loads(Path(metric_path).read_text(encoding="utf-8"))
                        baseline = json.loads(Path(payload["baseline"]).read_text(encoding="utf-8"))
                        value, base = candidate["value"], baseline["value"]
                        if any(
                            isinstance(n, bool)
                            or not isinstance(n, (int, float))
                            or not math.isfinite(n)
                            for n in (value, base)
                        ):
                            raise ValueError("invalid metric")
                        if (
                            candidate["metric"] != payload["metric"]
                            or baseline["metric"] != payload["metric"]
                            or candidate["protocol"] != baseline["protocol"]
                        ):
                            raise ValueError("incomparable metric protocol")
                        threshold = payload.get("threshold")
                        if (
                            isinstance(threshold, bool)
                            or not isinstance(threshold, (int, float))
                            or not math.isfinite(threshold)
                            or threshold < 0
                        ):
                            raise ValueError("invalid threshold")
                        delta = value - base if payload["direction"] == "maximize" else base - value
                        payload["outcome"] = "improved" if delta > threshold else "no_improvement"
                        payload["metric_value"], payload["baseline_value"], payload["delta"] = (
                            value,
                            base,
                            delta,
                        )
                    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                        payload["outcome"] = "incomparable"
                else:
                    payload["outcome"] = "incomparable"
        status = transitions[operation][1]
        db.execute(
            "UPDATE items SET revision=revision+1,status=?,payload=? WHERE id=? AND revision=?",
            (status, json.dumps(payload, ensure_ascii=False), identity, revision),
        )
        refresh(db)
        db.commit()
        return {
            "id": identity,
            "revision": revision + 1,
            "status": status,
            "outcome": payload.get("outcome"),
        }


if __name__ == "__main__":
    try:
        request = json.loads(os.environ.get("OCTOPUS_WORKFLOW_INPUT") or sys.stdin.read())
        print(json.dumps(execute(request), ensure_ascii=False, allow_nan=False))
    except (ValueError, sqlite3.Error, OSError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
