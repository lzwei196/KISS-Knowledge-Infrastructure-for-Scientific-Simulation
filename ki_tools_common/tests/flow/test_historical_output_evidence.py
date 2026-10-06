"""Retaining prior run files must neither block a new phase nor pass its steps."""
import json
from pathlib import Path

import pytest

from ki_tools_common.flow import receipts


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    root = tmp_path / "project"
    root.mkdir()
    return root


def record(project, *, approval="old", step="prior", status="passed", relative="outputs/prior.csv", at=1):
    output = project / relative
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.exists():
        output.write_text("date,value\n2022-01-01,1\n", encoding="utf-8")
    executable = project / "fixture-tool.py"
    executable.write_text("# synthetic receipt fixture; not a model\n", encoding="utf-8")
    receipt = receipts.record_run(
        project, ki="M", executable=str(executable), command=[str(executable)], cwd=str(project),
        started_at=at, finished_at=at+1, exit_code=1 if status == "failed" else 0,
        inputs=[], outputs=[output], approval_sha256=approval, plan_step_id=step,
        validation={"status": status, "checks": []},
        execution_status="failed" if status == "failed" else "succeeded", process_started=True)
    return receipt, output


def evidence(project):
    return receipts.evidence(project, {"selected_kis": ["M"], "steps": [
        {"id": "next", "kind": "run", "tool": None}]}, {"signature": {"value": "new"}})


@pytest.mark.parametrize("status", ["passed", "warning", "failed"])
def test_prior_history_never_satisfies_new_step_and_keeps_original_identity(project, status):
    path, output = record(project, status=status)
    before = path.read_bytes()
    proof = evidence(project)
    assert proof["validation"] == "incomplete" and not proof["receipts_verified"]
    assert proof["steps_missing"] == ["next"] and proof["steps_passed"] == []
    assert proof["runs_bound"] == 0 and proof["runs"] == []
    assert proof["unreceipted_artifacts"] == []
    entry, = proof["historical_outputs"]
    assert entry["approval_sha256"] == "old" and entry["validation"] == status
    assert entry["classification"] == {"failed": "failed_attempt", "warning": "validation_warning",
                                       "passed": "passed_run"}[status]
    assert entry["satisfies_current_step"] is False
    assert entry["sha256"] == receipts.sha256_file(output)
    assert entry["bytes"] == output.stat().st_size
    assert (project / entry["receipt_path"]).read_bytes() == before


@pytest.mark.parametrize("status", ["passed", "warning", "failed"])
def test_fresh_passing_run_can_finish_with_intact_prior_history(project, status):
    record(project, status=status)
    record(project, approval="new", step="next", relative="outputs/next.csv", at=10)
    proof = evidence(project)
    assert proof["receipts_verified"] and proof["validation"] == "passed"
    assert proof["steps_passed"] == ["next"] and proof["steps_missing"] == []
    assert proof["runs_bound"] == 1 and len(proof["runs"]) == 1
    assert proof["historical_outputs"][0]["validation"] == status


@pytest.mark.parametrize("tamper", ["same_size_bytes", "signature", "recorded_size", "unstarted", "missing_hash"])
def test_drift_or_untrusted_history_is_not_exempt(project, tamper):
    path, output = record(project)
    if tamper == "same_size_bytes":
        original = output.read_bytes()
        changed = original.replace(b"2022-01-01,1", b"2022-01-01,9")
        assert changed != original and len(changed) == len(original)
        output.write_bytes(changed)
    else:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if tamper == "signature":
            doc["signature"]["value"] = "0" * 64
        else:
            if tamper == "recorded_size":
                doc["outputs"][0]["bytes"] += 1
            elif tamper == "unstarted":
                doc["binary_actually_ran"] = False
            else:
                doc["outputs"][0]["sha256"] = None
            receipts.sign(project, doc)
        path.write_text(json.dumps(doc), encoding="utf-8")
    record(project, approval="new", step="next", relative="outputs/next.csv", at=10)
    proof = evidence(project)
    assert proof["historical_outputs"] == []
    assert proof["unreceipted_artifacts"] == ["outputs/prior.csv"]
    assert not proof["receipts_verified"]


def test_current_failed_attempt_cannot_hide_behind_prior_success(project):
    record(project)
    record(project, approval="new", step="next", status="failed", at=10)
    proof = evidence(project)
    assert proof["historical_outputs"] == []
    assert proof["unreceipted_artifacts"] == ["outputs/prior.csv"]
    assert proof["validation"] == "failed" and not proof["receipts_verified"]


def test_current_warning_still_requires_resolution(project):
    record(project)
    record(project, approval="new", step="next", status="warning", at=10)
    proof = evidence(project)
    assert proof["historical_outputs"] == []
    assert proof["unreceipted_artifacts"] == ["outputs/prior.csv"]
    assert proof["steps_missing"] == ["next"]
    assert proof["validation"] == "incomplete" and not proof["receipts_verified"]


def test_latest_historical_writer_keeps_failed_status(project):
    record(project)
    record(project, approval="other-old", status="failed", at=10)
    proof = evidence(project)
    entry, = proof["historical_outputs"]
    assert entry["approval_sha256"] == "other-old"
    assert entry["validation"] == "failed" and entry["classification"] == "failed_attempt"
    assert proof["steps_missing"] == ["next"]


def test_new_stray_file_does_not_inherit_old_directory_history(project):
    record(project)
    (project / "outputs/stray.csv").write_text("date,value\n2022-01-01,2\n", encoding="utf-8")
    record(project, approval="new", step="next", relative="outputs/next.csv", at=10)
    proof = evidence(project)
    assert proof["unreceipted_artifacts"] == ["outputs/stray.csv"]
    assert not proof["receipts_verified"]


def test_unverified_malformed_receipt_cannot_break_history_scan(project):
    record(project)
    path = project / receipts.RECEIPT_DIR / receipts.RUNS_SUB / "bad.json"
    path.write_text(json.dumps({"validation": "not an object", "outputs": {}}), encoding="utf-8")
    proof = evidence(project)
    assert len(proof["historical_outputs"]) == 1
    assert any(row["why"] == "signature" for row in proof["rejected_receipts"])
