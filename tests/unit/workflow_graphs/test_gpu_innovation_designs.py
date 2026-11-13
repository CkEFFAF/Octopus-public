"""Design admission uses real helper transitions and fake model receipts, never GPU jobs."""

import copy
import hashlib
import json
import runpy
import sqlite3
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[3] / "docs/examples/workflow-graphs"
SCOPE = "3dssg-existing-approved-backlog"


def module(name):
    spec = spec_from_file_location(name, EXAMPLES / (name + ".py"))
    result = module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def setup(tmp_path, monkeypatch):
    queue = module("gpu_innovation_queue")
    monkeypatch.setattr(queue, "DB", tmp_path / "ledger" / "queue.sqlite3")

    def no_gpu():
        raise AssertionError("design admission must not query or start GPU work")

    monkeypatch.setattr(queue, "capacity", no_gpu)
    monkeypatch.setattr(queue.subprocess, "Popen", no_gpu)
    return module("gpu_innovation_designs"), queue


def proposal(tmp_path, identity="T018", version="v1", **changes):
    design = tmp_path / identity / version / "DESIGN.md"
    design.parent.mkdir(parents=True, exist_ok=True)
    design.write_text(
        f"任务编号: {identity}\n设计版本: {version}\n"
        "## 代码设计\nfile/class/dataflow\n## 实施步骤\nordered steps\n"
        "## 评估验收\nmatched baseline\n## 依赖/风险/资源\nGPU0 only when idle\n",
        encoding="utf-8",
    )
    return {
        "id": identity,
        "design_path": str(design),
        "design_revision": version,
        "hypothesis": "a falsifiable hypothesis",
        "rationale": "observed evidence",
        "argv": ["never-run"],
        "cwd": str(tmp_path),
        "baseline": str(tmp_path / "baseline.json"),
        "metric": "m",
        "direction": "maximize",
        "threshold": 0.2,
        "candidate_version": "isolated-work-copy",
        "scope": SCOPE,
        "dependencies": [],
        "approved": True,
        **changes,
    }


def request(tmp_path, items, *, verdict="approved", scopes=None, delivery="actual-graph-delivery"):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"items": items}), encoding="utf-8")
    return {
        "manifest_path": str(manifest),
        "reviewer_model": "configured-advanced-model",
        "authorized_scopes": [SCOPE] if scopes is None else scopes,
        "review_output": {
            "evidence": {"delivery_id": delivery, "thread_id": "actual-child-thread"},
            "result": {
                "reviews": [
                    {
                        "task_id": item["id"],
                        "design_revision": item["design_revision"],
                        "design_sha256": hashlib.sha256(
                            Path(item["design_path"]).read_bytes()
                        ).hexdigest(),
                        "verdict": verdict,
                        "comments": ["reviewed against original task table"],
                    }
                    for item in items
                ]
            },
        },
    }


def test_approved_design_persists_real_wrapper_freezes_hashes_and_indexes(setup, tmp_path):
    designs, queue = setup
    data = request(tmp_path, [proposal(tmp_path)])
    output = designs.execute(data, queue=queue)
    assert output["ok"] and output["items"][0]["status"] == "approved"
    row = designs.ledger(queue)["T018"]
    verdict, hashes = queue.inspect_design(row, approved=True, frozen=True)
    assert verdict == "approved" and hashes["design_sha256"] == row["design_sha256"]
    receipt = json.loads(Path(row["design_review_path"]).read_bytes())
    evidence = json.loads(Path(receipt["review_evidence_path"]).read_bytes())
    assert evidence == {
        "reviewer_model": data["reviewer_model"],
        "wrapper": data["review_output"],
        "validation_only": False,
    }
    index = Path(output["designs_path"]).read_text("utf-8")
    assert "T018" in index and "v1" in index and "DESIGN.md" in index and "REVIEW-" in index
    again = designs.execute(data, queue=queue)
    assert again == output and designs.ledger(queue)["T018"]["revision"] == row["revision"]


def test_budget_validation_cannot_become_advanced_approval(setup, tmp_path):
    designs, queue = setup
    data = {**request(tmp_path, [proposal(tmp_path)]), "validation_only": True}
    result = designs.execute(data, queue=queue)
    assert result["ok"] and result["items"][0]["status"] == "proposed"
    assert result["items"][0]["review"] == "pending"
    row = designs.ledger(queue)["T018"]
    receipt = json.loads(Path(row["design_review_path"]).read_bytes())
    assert receipt["verdict"] == "pending" and receipt["validation_only"] is True
    with pytest.raises(ValueError, match="approved"):
        queue.execute({"operation": "approve", "id": "T018", "revision": row["revision"]})


@pytest.mark.parametrize(
    ("changes", "verdict", "scopes"),
    [
        ({"approved": False}, "approved", [SCOPE]),
        ({"approved": "true"}, "approved", [SCOPE]),
        ({"approved": True}, "pending", [SCOPE]),
        ({"approved": True}, "rejected", [SCOPE]),
        ({"scope": "unapproved-new-direction"}, "approved", [SCOPE]),
        ({"blockers": ["T007 probe failed"]}, "approved", [SCOPE]),
        ({}, "approved", []),
    ],
)
def test_only_actual_approved_review_and_explicit_scope_authorization_enable_execution(
    setup, tmp_path, changes, verdict, scopes
):
    designs, queue = setup
    data = request(tmp_path, [proposal(tmp_path, **changes)], verdict=verdict, scopes=scopes)
    output = designs.execute(data, queue=queue)
    assert output["ok"] and designs.ledger(queue)["T018"]["status"] == "proposed"


def test_missing_scope_configuration_defaults_to_proposed(setup, tmp_path):
    designs, queue = setup
    data = request(tmp_path, [proposal(tmp_path)])
    del data["authorized_scopes"]
    assert designs.execute(data, queue=queue)["items"][0]["status"] == "proposed"


def test_inherited_authorization_cannot_override_manifest_approved_false(setup, tmp_path):
    designs, queue = setup
    parent = proposal(tmp_path, identity="T014", allow_auto_descendants=True)
    assert designs.execute(request(tmp_path, [parent]), queue=queue)["ok"]
    with sqlite3.connect(queue.DB) as db:
        db.execute("UPDATE items SET status='failed' WHERE id='T014'")
    child = proposal(tmp_path, previous="T014", approved=False)
    output = designs.execute(request(tmp_path, [child]), queue=queue)
    assert output["ok"] and designs.ledger(queue)["T018"]["status"] == "proposed"


def test_design_sha_mismatch_is_visible_and_does_not_register(setup, tmp_path):
    designs, queue = setup
    item = proposal(tmp_path)
    data = request(tmp_path, [item])
    Path(item["design_path"]).write_text("changed after review", encoding="utf-8")
    output = designs.execute(data, queue=queue)
    assert not output["ok"] and output["items"][0]["status"] == "needs_review"
    assert designs.ledger(queue) == {}
    assert "needs_review" in Path(output["designs_path"]).read_text("utf-8")


def test_existing_unexecuted_item_reopens_revises_and_approves_with_cas(
    setup, tmp_path, monkeypatch
):
    designs, queue = setup
    first = proposal(tmp_path)
    assert designs.execute(request(tmp_path, [first]), queue=queue)["ok"]
    prior = designs.ledger(queue)["T018"]
    old_receipt = Path(prior["design_review_path"]).read_bytes()
    new = proposal(tmp_path, version="v2")
    original = queue.execute
    operations = []

    def traced(data):
        operations.append(copy.deepcopy(data))
        return original(data)

    monkeypatch.setattr(queue, "execute", traced)
    assert designs.execute(request(tmp_path, [new], delivery="review-v2"), queue=queue)["ok"]
    writes = [data for data in operations if data["operation"] != "list"]
    assert [data["operation"] for data in writes] == ["reopen", "revise", "approve"]
    assert [data["revision"] for data in writes] == [1, 2, 3]
    assert designs.ledger(queue)["T018"]["design_revision"] == "v2"
    assert Path(prior["design_review_path"]).read_bytes() == old_receipt


@pytest.mark.parametrize("status", ["claimed", "running", "unknown", "ran", "failed", "succeeded"])
def test_existing_claimed_or_executed_id_is_preserved(setup, tmp_path, status):
    designs, queue = setup
    first = proposal(tmp_path)
    data = request(tmp_path, [first])
    designs.execute(data, queue=queue)
    with sqlite3.connect(queue.DB) as db:
        db.execute("UPDATE items SET status=? WHERE id='T018'", (status,))
    before = designs.ledger(queue)["T018"]
    output = designs.execute(request(tmp_path, [proposal(tmp_path, version="v2")]), queue=queue)
    assert not output["ok"] and output["items"][0]["status"] == "needs_review"
    assert designs.ledger(queue)["T018"] == before


def test_changed_execution_command_cannot_overwrite_existing_proposal(setup, tmp_path):
    designs, queue = setup
    first = proposal(tmp_path)
    designs.execute(request(tmp_path, [first]), queue=queue)
    before = designs.ledger(queue)["T018"]
    new = proposal(tmp_path, version="v2", argv=["different-command"])
    output = designs.execute(request(tmp_path, [new]), queue=queue)
    assert not output["ok"] and "argv" in output["items"][0]["reason"]
    assert designs.ledger(queue)["T018"] == before


def test_partial_failure_keeps_already_registered_item_and_all_index_entries(setup, tmp_path):
    designs, queue = setup
    items = [proposal(tmp_path, identity="T018"), proposal(tmp_path, identity="T019")]
    data = request(tmp_path, items)
    data["review_output"]["result"]["reviews"][1]["design_sha256"] = "0" * 64
    output = designs.execute(data, queue=queue)
    assert not output["ok"] and designs.ledger(queue)["T018"]["status"] == "approved"
    assert "T019" not in designs.ledger(queue)
    index = Path(output["designs_path"]).read_text("utf-8")
    assert "T018" in index and "T019" in index and "needs_review" in index


@pytest.mark.parametrize("key", ["delivery_id", "thread_id"])
def test_missing_engine_evidence_fails_before_queue_mutation(setup, tmp_path, key):
    designs, queue = setup
    data = request(tmp_path, [proposal(tmp_path)])
    del data["review_output"]["evidence"][key]
    with pytest.raises(ValueError, match=key):
        designs.execute(data, queue=queue)
    assert not queue.DB.exists()


def test_ten_item_output_is_bounded_and_receipts_do_not_collide(setup, tmp_path):
    designs, queue = setup
    items = [proposal(tmp_path, identity=f"T{index:03d}") for index in range(30, 40)]
    output = designs.execute(request(tmp_path, items), queue=queue)
    assert output["ok"] and len(output["items"]) == 10
    assert len(designs.encoded(output)) <= 8192
    assert len({row["design_review_path"] for row in designs.ledger(queue).values()}) == 10


def test_same_design_revision_cannot_silently_replace_previously_reviewed_contents(setup, tmp_path):
    designs, queue = setup
    item = proposal(tmp_path)
    designs.execute(request(tmp_path, [item]), queue=queue)
    before = designs.ledger(queue)["T018"]
    with Path(item["design_path"]).open("a", encoding="utf-8") as stream:
        stream.write("\nchanged scientific method\n")
    output = designs.execute(request(tmp_path, [item], delivery="new-review"), queue=queue)
    assert not output["ok"] and "new design_revision" in output["items"][0]["reason"]
    assert designs.ledger(queue)["T018"]["revision"] == before["revision"]


def test_concurrent_claim_wins_over_design_reopen_cas(setup, tmp_path, monkeypatch):
    designs, queue = setup
    designs.execute(request(tmp_path, [proposal(tmp_path)]), queue=queue)
    original = queue.execute

    def race(data):
        if data["operation"] == "reopen":
            with sqlite3.connect(queue.DB) as db:
                db.execute("UPDATE items SET revision=revision+1,status='claimed' WHERE id='T018'")
        return original(data)

    monkeypatch.setattr(queue, "execute", race)
    data = request(tmp_path, [proposal(tmp_path, version="v2")], delivery="new-review")
    output = designs.execute(data, queue=queue)
    assert not output["ok"] and "revision conflict" in output["items"][0]["reason"]
    row = designs.ledger(queue)["T018"]
    assert row["status"] == "claimed" and row["design_revision"] == "v1"


def test_cli_partial_failure_exits_nonzero_with_json_and_preserves_registered_item(
    setup, tmp_path, monkeypatch, capsys
):
    designs, queue = setup
    items = [proposal(tmp_path, identity="T018"), proposal(tmp_path, identity="T019")]
    data = request(tmp_path, items)
    data["review_output"]["result"]["reviews"][1]["design_sha256"] = "wrong"
    monkeypatch.setenv("GPU_INNOVATION_QUEUE", str(queue.DB))
    monkeypatch.setenv("OCTOPUS_WORKFLOW_INPUT", json.dumps(data))
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(EXAMPLES / "gpu_innovation_designs.py"), run_name="__main__")
    assert stopped.value.code == 1
    captured = capsys.readouterr()
    assert not captured.err and json.loads(captured.out)["ok"] is False
    assert designs.ledger(queue)["T018"]["status"] == "approved"


def test_empty_design_batch_refreshes_index_without_creating_or_approving_experiments(
    setup, tmp_path
):
    designs, queue = setup
    output = designs.execute(request(tmp_path, []), queue=queue)
    assert output["ok"] and output["items"] == []
    assert designs.ledger(queue) == {}
    assert Path(output["designs_path"]).is_file()
