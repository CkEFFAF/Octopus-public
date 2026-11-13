"""Admission and execution evidence for the example device-side queue."""

import hashlib
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


@pytest.fixture
def queue(tmp_path, monkeypatch):
    path = (
        Path(__file__).resolve().parents[3]
        / "docs/examples/workflow-graphs/gpu_innovation_queue.py"
    )
    spec = spec_from_file_location("gpu_innovation_queue", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DB", tmp_path / "queue.sqlite3")
    monkeypatch.setattr(module, "capacity", lambda: True)
    return module


def test_validation_claim_cannot_take_real_work_or_query_gpu(queue, monkeypatch):
    def forbidden():
        raise AssertionError("validation must not contact the GPU")

    monkeypatch.setattr(queue, "capacity", forbidden)
    assert queue.execute({"operation": "claim", "validation_only": True}) == {
        "claimed": False,
        "reason": "validation_only",
    }
    assert not queue.DB.exists()


def item(tmp_path, identity, dependencies=()):
    design = tmp_path / f"{identity}-design.md"
    review = tmp_path / f"{identity}-review.json"
    evidence = tmp_path / f"{identity}-evidence.txt"
    design.write_text(
        f"任务编号: {identity}\n设计版本: v1\n\n## 代码设计\ncode\n\n## 实施步骤\nsteps\n\n## 评估验收\nmetrics\n\n## 依赖/风险/资源\nresources\n",
        encoding="utf-8",
    )
    evidence.write_text("review receipt", encoding="utf-8")
    review.write_text(
        json.dumps(
            {
                "task_id": identity,
                "design_revision": "v1",
                "design_sha256": hashlib.sha256(design.read_bytes()).hexdigest(),
                "verdict": "approved",
                "reviewer_model": "test-model",
                "review_evidence_path": str(evidence),
            }
        ),
        encoding="utf-8",
    )
    return {
        "design_path": str(design),
        "design_revision": "v1",
        "design_review_path": str(review),
        "id": identity,
        "hypothesis": "h",
        "rationale": "r",
        "baseline": str(tmp_path / "baseline.json"),
        "metric": "m",
        "direction": "maximize",
        "threshold": 0.1,
        "candidate_version": "v",
        "argv": [sys.executable, "-c", "print(123)"],
        "cwd": str(tmp_path),
        "dependencies": list(dependencies),
    }


def test_approval_dependencies_execution_and_evidence(queue, tmp_path):
    queue.execute({"operation": "propose", "item": item(tmp_path, "a")})
    queue.execute({"operation": "propose", "item": item(tmp_path, "b", ["a"])})
    queue.execute({"operation": "approve", "id": "b", "revision": 0})
    assert not queue.execute({"operation": "claim"})["claimed"]
    with pytest.raises(ValueError):
        queue.execute({"operation": "propose", "item": item(tmp_path, "c", ["c"])})
    queue.execute({"operation": "approve", "id": "a", "revision": 0})
    claim = queue.execute({"operation": "claim"})
    run = queue.execute(
        {
            "operation": "run",
            "id": claim["item"]["id"],
            "revision": claim["item"]["revision"],
            "claim_token": claim["claim_token"],
        }
    )
    assert run["status"] == "ran"
    assert run["execution"]["process_started"] is True
    assert run["execution"]["returncode"] == 0
    assert Path(run["execution"]["log_path"]).read_text().strip() == "123"
    (tmp_path / "baseline.json").write_text(
        json.dumps({"metric": "m", "protocol": "p", "value": 1}), encoding="utf-8"
    )
    metric = tmp_path / "metric.json"
    metric.write_text(json.dumps({"metric": "m", "protocol": "p", "value": 2}), encoding="utf-8")
    report = tmp_path / "report.md"
    report.write_text("report", encoding="utf-8")
    finish = {
        "operation": "finish",
        "id": "a",
        "revision": run["revision"],
        "receipt": "fake",
        "report_path": str(report),
        "metric_path": str(metric),
    }
    with pytest.raises(ValueError):
        queue.execute(finish)
    finish["receipt"] = run["execution"]["log_path"]
    queue.execute(finish)
    assert queue.execute({"operation": "list"})["items"][0]["outcome"] == "improved"
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: queue.execute({"operation": "claim"}), range(8)))
    assert sum(result["claimed"] for result in results) == 1
    with pytest.raises(ValueError):
        queue.execute({"operation": "unknown", "id": "b", "revision": 0})


def test_failed_run_and_scoped_successor(queue, tmp_path):
    first = item(tmp_path, "first")
    first.update(scope="specific-hypothesis", argv=[sys.executable, "-c", "raise SystemExit(2)"])
    queue.execute({"operation": "propose", "item": first})
    queue.execute(
        {"operation": "approve", "id": "first", "revision": 0, "allow_auto_descendants": True}
    )
    claim = queue.execute({"operation": "claim"})
    run = queue.execute(
        {
            "operation": "run",
            "id": claim["item"]["id"],
            "revision": claim["item"]["revision"],
            "claim_token": claim["claim_token"],
        }
    )
    assert run["status"] == "failed" and run["execution"]["returncode"] == 2
    report = tmp_path / "failure.md"
    report.write_text("failure", encoding="utf-8")
    result = queue.execute(
        {
            "operation": "report_failure",
            "id": "first",
            "revision": run["revision"],
            "receipt": run["execution"]["log_path"],
            "report_path": str(report),
        }
    )
    assert result["outcome"] == "incomparable"
    followup = item(tmp_path, "second")
    followup.update(previous="first", scope="specific-hypothesis")
    assert queue.execute({"operation": "propose", "item": followup})["status"] == "approved"
    pending = item(tmp_path, "manual")
    pending.update(previous="first", scope="specific-hypothesis")
    assert (
        queue.execute({"operation": "propose", "item": pending, "auto_approve": False})["status"]
        == "proposed"
    )
    novel = item(tmp_path, "novel")
    novel.update(previous="first", scope="other")
    assert queue.execute({"operation": "propose", "item": novel})["status"] == "proposed"
    assert "failure.md" in (tmp_path / "REPORTS.md").read_text(encoding="utf-8")


def test_claim_fences_run_and_summary_is_bounded(queue, tmp_path, monkeypatch):
    oversized = item(tmp_path, "oversized")
    oversized["rationale"] = "细节" * 2000
    with pytest.raises(ValueError, match="8192"):
        queue.execute({"operation": "propose", "item": oversized})
    assert not queue.execute({"operation": "list"})["items"]
    queue.execute({"operation": "propose", "item": item(tmp_path, "first")})
    queue.execute({"operation": "approve", "id": "first", "revision": 0})
    claim = queue.execute({"operation": "claim"})
    candidate = claim["item"]
    attempt = {
        "operation": "run",
        "id": candidate["id"],
        "revision": candidate["revision"],
        "claim_token": claim["claim_token"],
    }
    with pytest.raises(ValueError):
        queue.execute({**attempt, "claim_token": "wrong"})
    monkeypatch.setattr(queue, "capacity", lambda: False)
    assert not queue.execute(attempt)["claimed"]
    assert queue.execute({"operation": "list"})["items"][0]["status"] == "claimed"
    monkeypatch.setattr(queue, "capacity", lambda: True)
    assert queue.execute(attempt)["status"] == "ran"
    with pytest.raises(ValueError):
        queue.execute(attempt)
    for index in range(30):
        queue.execute({"operation": "propose", "item": item(tmp_path, f"item-{index}")})
    summary = queue.execute({"operation": "summary"})
    assert summary["total"] == 31 and len(summary["items"]) <= 20
    assert "claim_token" not in json.dumps(summary)


def test_interrupted_running_item_requires_explicit_receipt_reconciliation(queue, tmp_path):
    import sqlite3

    queue.execute({"operation": "propose", "item": item(tmp_path, "interrupted")})
    queue.execute({"operation": "approve", "id": "interrupted", "revision": 0})
    claim = queue.execute({"operation": "claim"})
    with sqlite3.connect(queue.DB) as db:
        db.execute("UPDATE items SET status='running' WHERE id='interrupted'")
    marked = queue.execute(
        {"operation": "unknown", "id": "interrupted", "revision": claim["item"]["revision"]}
    )
    request = {"operation": "fail", "id": "interrupted", "revision": marked["revision"]}
    with pytest.raises(ValueError, match="confirm"):
        queue.execute(request)
    receipt = tmp_path / "job-receipt.json"
    report = tmp_path / "reconciliation.md"
    receipt.write_text('{"status":"cancelled"}', encoding="utf-8")
    report.write_text("Original Job verified stopped", encoding="utf-8")
    result = queue.execute(
        {**request, "confirmed_stopped": True, "receipt": str(receipt), "report_path": str(report)}
    )
    assert result["status"] == "failed"


def test_report_index_encodes_native_links(queue, tmp_path):
    queue.write_indexes(
        {
            "T1": {
                "id": "T1",
                "revision": 1,
                "status": "succeeded",
                "report_path": "/tmp/report (v1).md",
            }
        }
    )
    assert "[T1](/tmp/report%20%28v1%29.md)" in (tmp_path / "REPORTS.md").read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("failure", ["missing_executable", "missing_cwd"])
def test_launch_failure_records_real_error_and_allows_reporting(queue, tmp_path, failure):
    proposal = item(tmp_path, "launch-failure")
    if failure == "missing_executable":
        proposal["argv"] = [str(tmp_path / "missing-executable")]
    else:
        proposal["cwd"] = str(tmp_path / "missing-directory")
    queue.execute({"operation": "propose", "item": proposal})
    queue.execute({"operation": "approve", "id": "launch-failure", "revision": 0})
    claim = queue.execute({"operation": "claim"})
    result = queue.execute(
        {
            "operation": "run",
            "id": claim["item"]["id"],
            "revision": claim["item"]["revision"],
            "claim_token": claim["claim_token"],
        }
    )
    assert result["claimed"] is True
    assert result["status"] == "failed"
    execution = result["execution"]
    assert execution["process_started"] is False
    assert execution["returncode"] is None
    assert execution["launch_error"].startswith(("FileNotFoundError:", "NotADirectoryError:"))
    assert execution["launch_error"] in Path(execution["log_path"]).read_text(encoding="utf-8")
    report = tmp_path / "launch-failure.md"
    report.write_text("Launch failed", encoding="utf-8")
    recorded = queue.execute(
        {
            "operation": "report_failure",
            "id": "launch-failure",
            "revision": result["revision"],
            "receipt": execution["log_path"],
            "report_path": str(report),
        }
    )
    assert recorded["status"] == "failed"
    assert recorded["outcome"] == "incomparable"
    stored = queue.execute({"operation": "list"})["items"][0]
    assert stored["execution"] == execution
    assert "metric_value" not in stored


def test_design_gate_requires_review_and_frozen_files(queue, tmp_path):
    missing = item(tmp_path, "missing")
    Path(missing["design_path"]).unlink()
    with pytest.raises(ValueError, match="design or review file unavailable"):
        queue.execute({"operation": "propose", "item": missing})
    proposed = item(tmp_path, "reviewed")
    review_path = Path(proposed["design_review_path"])
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["verdict"] = "pending"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    queue.execute({"operation": "propose", "item": proposed})
    with pytest.raises(ValueError, match="review must be approved"):
        queue.execute({"operation": "approve", "id": "reviewed", "revision": 0})
    review["verdict"] = "approved"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    queue.execute({"operation": "approve", "id": "reviewed", "revision": 0})
    Path(proposed["design_path"]).write_text("changed", encoding="utf-8")
    result = queue.execute({"operation": "claim"})
    assert not result["claimed"] and result["reason"] == "design_review_required"
    assert (
        queue.execute({"operation": "list"})["items"][0]["design_review_status"] == "needs_review"
    )


def test_design_mutation_after_claim_blocks_run_and_can_reopen(queue, tmp_path):
    proposal = item(tmp_path, "claim-test")
    queue.execute({"operation": "propose", "item": proposal})
    queue.execute({"operation": "approve", "id": "claim-test", "revision": 0})
    claim = queue.execute({"operation": "claim"})
    review = Path(proposal["design_review_path"])
    review.write_text(review.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="changed; review and approval required"):
        queue.execute(
            {
                "operation": "run",
                "id": "claim-test",
                "revision": claim["item"]["revision"],
                "claim_token": claim["claim_token"],
            }
        )
    reopened = queue.execute(
        {
            "operation": "reopen",
            "id": "claim-test",
            "revision": claim["item"]["revision"],
            "claim_token": claim["claim_token"],
        }
    )
    assert reopened["status"] == "proposed"
    queue.execute({"operation": "approve", "id": "claim-test", "revision": reopened["revision"]})
    assert queue.execute({"operation": "claim"})["claimed"]


def test_review_evidence_change_blocks_claim_and_legacy_is_preserved(queue, tmp_path):
    proposal = item(tmp_path, "evidence")
    queue.execute({"operation": "propose", "item": proposal})
    queue.execute({"operation": "approve", "id": "evidence", "revision": 0})
    receipt = json.loads(Path(proposal["design_review_path"]).read_text(encoding="utf-8"))
    Path(receipt["review_evidence_path"]).write_text("changed", encoding="utf-8")
    with sqlite3.connect(queue.DB) as db:
        db.execute(
            "INSERT INTO items VALUES (?, ?, ?, ?)",
            ("legacy", 0, "approved", json.dumps({"priority": 1})),
        )
    result = queue.execute({"operation": "claim"})
    assert not result["claimed"]
    assert {item["id"] for item in result["blocked"]} == {"evidence", "legacy"}
    rows = {item["id"]: item for item in queue.execute({"operation": "list"})["items"]}
    assert rows["legacy"]["status"] == "approved"
    assert rows["legacy"]["design_review_status"] == "needs_review"
    assert rows["evidence"]["design_review_status"] == "needs_review"


def test_revise_proposed_design_requires_current_revision(queue, tmp_path):
    proposal = item(tmp_path, "revise")
    queue.execute({"operation": "propose", "item": proposal})
    queue.execute({"operation": "approve", "id": "revise", "revision": 0})
    reopened = queue.execute({"operation": "reopen", "id": "revise", "revision": 1})
    design = Path(proposal["design_path"])
    design.write_text(
        design.read_text(encoding="utf-8").replace("设计版本: v1", "设计版本: v2"), encoding="utf-8"
    )
    review_path = Path(proposal["design_review_path"])
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review.update(
        design_revision="v2", design_sha256=hashlib.sha256(design.read_bytes()).hexdigest()
    )
    review_path.write_text(json.dumps(review), encoding="utf-8")
    revision = {
        "operation": "revise",
        "id": "revise",
        "revision": reopened["revision"],
        "design_path": str(design),
        "design_revision": "v2",
        "design_review_path": str(review_path),
    }
    with pytest.raises(ValueError, match="revision conflict"):
        queue.execute({**revision, "revision": 0})
    result = queue.execute(revision)
    queue.execute({"operation": "approve", "id": "revise", "revision": result["revision"]})
    assert queue.execute({"operation": "claim"})["item"]["design_revision"] == "v2"


def wrapper_inputs(queue, tmp_path):
    proposal = item(tmp_path, "wrapped")
    queue.execute({"operation": "propose", "item": proposal})
    queue.execute({"operation": "approve", "id": "wrapped", "revision": 0})
    claim = queue.execute({"operation": "claim"})
    code = tmp_path / "code.py"
    code.write_text("print('tested')", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "files": [
                    {"path": str(code), "sha256": hashlib.sha256(code.read_bytes()).hexdigest()}
                ]
            }
        ),
        encoding="utf-8",
    )
    preparation = {
        "prepared": True,
        "id": "wrapped",
        "revision": claim["item"]["revision"],
        "implementation_manifest_path": str(manifest),
        "implementation_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
    }
    review = {
        "evidence": {"delivery_id": "delivery", "thread_id": "thread"},
        "result": {
            "approved": True,
            "task_id": "wrapped",
            "revision": preparation["revision"],
            "design_sha256": claim["item"]["design_sha256"],
            "implementation_manifest_sha256": preparation["implementation_manifest_sha256"],
        },
    }
    return {
        "operation": "run_prepared",
        "id": "wrapped",
        "revision": preparation["revision"],
        "claim_token": claim["claim_token"],
        "preparation": preparation,
        "code_review_output": review,
        "reviewer_model": "review-model",
    }, code


def test_run_prepared_rejects_bad_preparation_and_archive_needs_real_report(queue, tmp_path):
    request, _ = wrapper_inputs(queue, tmp_path)
    result = queue.execute({**request, "preparation": {"prepared": False}})
    assert result["status"] == "preparation_failed" and Path(result["receipt"]).is_file()
    assert (
        queue.execute(
            {
                "operation": "archive",
                "id": "wrapped",
                "revision": request["revision"],
                "claim_token": request["claim_token"],
                "analysis": {"ready": False},
            }
        )["status"]
        == "manual_review"
    )
    report = tmp_path / "failure.md"
    report.write_text("reviewed failure", encoding="utf-8")
    archived = queue.execute(
        {
            "operation": "archive",
            "id": "wrapped",
            "revision": request["revision"],
            "claim_token": request["claim_token"],
            "analysis": {"ready": True, "receipt": result["receipt"], "report_path": str(report)},
        }
    )
    assert archived["status"] == "failed"


def test_run_prepared_checks_review_and_actual_code_files(queue, tmp_path):
    request, code = wrapper_inputs(queue, tmp_path)
    bad_review = {**request["code_review_output"], "evidence": {}}
    assert (
        queue.execute({**request, "code_review_output": bad_review})["status"] == "review_required"
    )
    code.write_text("changed after review", encoding="utf-8")
    assert queue.execute(request)["status"] == "preparation_failed"
    assert queue.execute({"operation": "list"})["items"][0]["status"] == "claimed"


def test_run_prepared_waits_and_archives_real_exit(queue, tmp_path, monkeypatch):
    request, _ = wrapper_inputs(queue, tmp_path)
    checks = iter([False, True, True])
    monkeypatch.setattr(queue, "capacity", lambda: next(checks))
    monkeypatch.setattr(queue.time, "sleep", lambda _: None)
    result = queue.execute({**request, "wait_for_capacity": True})
    assert result["status"] == "ran" and result["execution"]["returncode"] == 0
    baseline = tmp_path / "baseline.json"
    metric = tmp_path / "metric.json"
    report = tmp_path / "report.md"
    baseline.write_text(json.dumps({"metric": "m", "protocol": "p", "value": 1}), encoding="utf-8")
    metric.write_text(json.dumps({"metric": "m", "protocol": "p", "value": 2}), encoding="utf-8")
    report.write_text("analysis", encoding="utf-8")
    archived = queue.execute(
        {
            "operation": "archive",
            "id": "wrapped",
            "revision": result["revision"],
            "analysis": {
                "ready": True,
                "receipt": result["execution"]["log_path"],
                "report_path": str(report),
                "metric_path": str(metric),
            },
        }
    )
    assert archived["status"] == "succeeded" and archived["outcome"] == "improved"


def test_validation_run_cannot_launch_a_previously_claimed_experiment(queue, tmp_path, monkeypatch):
    data, _ = wrapper_inputs(queue, tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("validation must not start a process")

    monkeypatch.setattr(queue.subprocess, "Popen", forbidden)
    result = queue.execute({**data, "operation": "run_prepared", "validation_only": True})
    assert result["status"] == "review_required"
    assert Path(result["receipt"]).is_file()
    current = queue.execute({"operation": "list"})["items"][0]
    assert current["status"] == "claimed" and current["revision"] == data["revision"]
