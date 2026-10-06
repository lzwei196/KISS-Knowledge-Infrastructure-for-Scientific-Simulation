"""Required executable checks cannot be skipped after a model step succeeds.

Synthetic signed receipt fixtures only; these tests do not run any model/tool.
"""
from __future__ import annotations

import hashlib

import pytest

from ki_tools_common.flow import receipts


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry"))
    project = tmp_path / "project"
    project.mkdir()
    tools = {}
    for name in ("model", "check"):
        tools[name] = project / f"{name}.py"
        tools[name].write_text("# synthetic receipt fixture; never executed\n", encoding="utf-8")
    plan = {"selected_kis": ["M"], "steps": [
        {"id": "preflight", "ki": "M", "kind": "check", "tool": None,
         "inputs": [], "outputs": []},
        {"id": "model", "ki": "M", "kind": "run", "tool": str(tools["model"])},
        {"id": "check", "ki": "M", "kind": "check", "tool": str(tools["check"]),
         "outputs": ["check_report"]},
    ]}
    approval = {"signature": {"value": "current"}}
    return project, plan, approval, tools


def record(case, step, *, status="passed", approval="current", typed=False):
    project, _plan, _approval, tools = case
    output = project / "outputs" / f"{step}.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text('{"fixture": true}\n', encoding="utf-8")
    extra = {"project_data_tool": _plan["steps"][-1]["project_data_tool"]} if typed else {}
    return receipts.record_run(
        project, ki="M", executable=str(tools[step]), command=[str(tools[step])],
        cwd=str(project), started_at=1 if step == "model" else 3,
        finished_at=2 if step == "model" else 4, exit_code=1 if status == "failed" else 0,
        inputs=[], outputs=[output], approval_sha256=approval, plan_step_id=step,
        validation={"status": status, "checks": []},
        execution_status="failed" if status == "failed" else "succeeded",
        process_started=True, **extra)


@pytest.mark.parametrize("typed", [False, True], ids=["ki-tool", "project-data-tool"])
@pytest.mark.parametrize("status,check_approval", [
    ("passed", "current"), ("failed", "current"), ("warning", "current"), ("passed", "old"),
])
def test_executable_check_is_required_and_must_pass_under_current_approval(case, typed, status, check_approval):
    project, plan, approval, tools = case
    if typed:
        plan["steps"][-1]["project_data_tool"] = {
            "version": 1, "purpose": "check",
            "source_sha256": hashlib.sha256(tools["check"].read_bytes()).hexdigest(),
            "arguments": [], "cwd": ".", "timeout_seconds": 120,
        }
    model_receipt = record(case, "model")
    before = model_receipt.read_bytes()
    proof = receipts.evidence(project, plan, approval)
    assert proof["executable_steps"] == ["check", "model"]
    assert proof["steps_missing"] == ["check"]
    assert proof["steps_passed"] == ["model"]
    assert proof["validation"] == "incomplete" and not proof["receipts_verified"]
    record(case, "check", status=status, approval=check_approval, typed=typed)
    proof = receipts.evidence(project, plan, approval)
    passed = status == "passed" and check_approval == "current"
    assert proof["receipts_verified"] is passed
    assert proof["steps_missing"] == ([] if passed else ["check"])
    assert proof["validation"] == ("passed" if passed else "failed" if status == "failed" else "incomplete")
    assert "preflight" not in proof["executable_steps"]
    assert model_receipt.read_bytes() == before


def test_null_host_preflight_does_not_require_a_run_receipt(case):
    project, plan, approval, _tools = case
    plan["steps"].pop()
    record(case, "model")
    proof = receipts.evidence(project, plan, approval)
    assert proof["executable_steps"] == ["model"]
    assert proof["steps_missing"] == []
    assert proof["validation"] == "passed" and proof["receipts_verified"]
