"""Real tool exits do not turn untracked bookkeeping into scientific evidence."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from kiss_cli import api, flowgate
from .test_calibration_flow_binding import _approve, case as calibration_case
from .test_flowgate import _cfg, _ki, _plan, _session


def _approved_run(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry.json"))
    ki = _ki(tmp_path, extra_files={"tools/run.py": "import argparse, pathlib\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--output-dir', required=True)\n"
        "args = parser.parse_args()\n"
        "out = pathlib.Path(args.output_dir)\n"
        "out.mkdir(parents=True, exist_ok=False)\n"
        "(out / 'q.csv').write_text('t,q\\n1,0.5\\n2,1.2\\n3,0.8\\n')\n"
        "print('fixture process completed')\n"})
    project, fs = _session(tmp_path, ki, [
        ("task_received", None), ("kis_resolved", {"selected_kis": ["M"]})])
    plan, inventory = _plan(ki)
    fs.write_plan(plan, inventory)
    fs.flow.approval.approve(project, by="auto")
    fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True})
    fs.move("approved", {"approval": "OK"})
    fs.move("execution_started", {"setup_verified": True})
    return ki, project, fs


@pytest.mark.parametrize("destination,expected", [
    ("runs/reference", "failed"),
    ("outputs/reference", "passed"),
    ("artifacts/reference", "passed"),
])
def test_output_location_feedback_matches_real_signed_receipt(tmp_path, monkeypatch, destination, expected):
    ki, project, fs = _approved_run(tmp_path, monkeypatch)
    approval_before = (project / "runs" / "approval.json").read_bytes()
    text = api.execute_tool(
        "run_ki_tool", {
            "tool_path": "tools/run.py", "arguments": ["--output-dir", destination],
            "plan_step_id": "M:run",
        }, ki, _cfg(project), project_mode=True, flow=fs,
    )
    assert text.startswith("exit_code=0")
    assert (project / destination / "q.csv").read_text().startswith("t,q\n")
    summary = json.loads(text.splitlines()[1].removeprefix("[RECEIPT] "))
    assert summary["validation"] == expected
    receipt = json.loads(Path(summary["receipt"]).read_text(encoding="utf-8"))
    assert fs.flow.receipts.verify(project, receipt)
    assert receipt["exit_code"] == 0
    assert receipt["validation"]["status"] == expected
    assert "output_hint" not in receipt  # advice must not change the signed format
    assert (project / "runs" / "approval.json").read_bytes() == approval_before
    assert fs.evidence()["validation"] == expected
    if expected == "failed":
        assert summary["outputs"] == [] and receipt["outputs"] == []
        assert "output_affirmed_nonempty" in summary["failed_checks"]
        hint = summary["output_hint"]
        assert "inputs/, outputs/, artifacts/, runs/logs/" in hint
        assert "runs/<name> directory is bookkeeping" in hint
        assert "Process success alone is insufficient" in hint
        assert "fresh outputs/<run>/ or artifacts/" in hint
        assert "approved plan" in hint
        assert "request_replan" in hint
    else:
        assert summary["outputs"] == [f"{destination}/q.csv"]
        assert "output_hint" not in summary


def test_run_schema_explains_destinations_and_wrapper_arguments(tmp_path, monkeypatch):
    ki, _project, fs = _approved_run(tmp_path, monkeypatch)
    tool = next(tool for tool in api.tool_schemas(ki, project_mode=True, flow=fs)
                if tool["name"] == "run_ki_tool")
    description = tool["description"]
    assert "wrapper's documented flags" in description
    assert "do not guess argument names" in description
    assert "fresh outputs/<run>/ or artifacts/" in description
    assert "approved plan" in description
    assert "runs/<name>" in description and "not captured" in description
    assert "runs/logs/" in description


def test_empty_typed_calibration_keeps_host_owned_destination(calibration_case, monkeypatch, tmp_path):
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry.json"))
    fs, plan, _inventory, adapter = _approve(calibration_case)
    approval_before = (fs.project / "runs" / "approval.json").read_bytes()
    before = flowgate._snapshot(
        fs.project, subs=("inputs", "outputs", "artifacts", "runs/logs", "calibration/runs"))
    # Simulate the native engine's failed return without invoking an optimizer.
    result = {"approved_binding": plan["steps"][0]["calibration"],
              "report": {"status": "failed", "reason": "fixture: no native output"}}
    summary = fs.record_tool_run(
        ki="M", ki_root=fs.ki_roots["M"],
        command=["geoforge-calibration", "--adapter", str(adapter / "tools" / "calib_run.py")],
        cwd=fs.project, started_at=time.time(), finished_at=time.time(), exit_code=1,
        before=before, plan_step_id="M:calibrate", calibration_result=result,
        input_arguments=[str(adapter / "tools" / "calib_run.py"), str(adapter / "calibration.yaml")],
    )
    assert summary["validation"] == "failed" and summary["outputs"] == []
    hint = summary["output_hint"]
    assert "inputs/, outputs/, artifacts/, runs/logs/, calibration/runs/" in hint
    assert "retain the host-owned calibration/runs/ destination" in hint
    assert "run_calibration with the approved binding" in hint
    assert "fresh outputs/<run>" not in hint
    assert "request_replan" in hint
    receipt = json.loads(Path(summary["receipt"]).read_text(encoding="utf-8"))
    assert fs.flow.receipts.verify(fs.project, receipt)
    assert receipt["outputs"] == [] and receipt["validation"]["status"] == "failed"
    assert "output_hint" not in receipt
    assert (fs.project / "runs" / "approval.json").read_bytes() == approval_before
