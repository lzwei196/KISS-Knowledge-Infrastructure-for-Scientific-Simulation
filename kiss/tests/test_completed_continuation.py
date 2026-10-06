"""A completed data phase can lead to new work without granting another run."""
import json
from pathlib import Path

import pytest

from kiss_cli import api, flowrun
from .test_flowrun import _ki, _project, _cfg, _drive_planning, _approve


def test_completed_question_stays_closed_then_explicit_replan_needs_new_review(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry"))
    project = _project(tmp_path)
    ki = _ki(tmp_path, "M")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    planning = _drive_planning(tmp_path, ki, project)
    review = flowrun.after(project, planning, "Plan ready.", setup_ok=True)
    _approve(project, ki, review)
    execution = flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None, "go")
    step = execution.session.plan["steps"][0]["id"]
    api.execute_tool("run_ki_tool", {"tool_path": "tools/run.py",
                     "arguments": ["outputs/q.csv"], "plan_step_id": step},
                     ki, _cfg(project), project_mode=True, flow=execution.session)
    flowrun.after(project, execution, "Done.", setup_ok=True)
    assert execution.session.state.value == "COMPLETED"
    original_output = (project / "outputs/q.csv").read_bytes()
    original_receipts = {str(p): p.read_bytes() for p in (project / ".geoforge/receipts").rglob("*.json")}

    readonly = flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None, "What happened?")
    assert not readonly.execute and readonly.session.state.value == "COMPLETED"
    assert "request_replan" in readonly.extra_prompt
    assert "run_ki_tool" not in readonly.session.api_tools()
    flowrun.after(project, readonly, "The approved phase is complete.", setup_ok=True)
    assert readonly.session.state.value == "COMPLETED"

    continuation = flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None,
                                "Continue with the next site phase")
    api.execute_tool("request_replan", {"reason": "User requested the next site phase"}, ki,
                     _cfg(project), project_mode=True, flow=continuation.session)
    pj, inventory = continuation.session.plan, continuation.session.inventory
    pj["goal"] = "Run the next site phase"
    pj["steps"][0]["id"] = "M:next_phase"
    api.execute_tool("write_plan", {"plan": pj, "data_inventory": inventory}, ki,
                     _cfg(project), project_mode=True, flow=continuation.session)
    next_review = flowrun.after(project, continuation, "Next phase plan ready.", setup_ok=True)
    assert next_review.request and not next_review.continue_now
    assert continuation.session.state.value == "WAITING_FOR_USER"
    assert not (project / "runs/approval.json").exists()
    assert (project / "outputs/q.csv").read_bytes() == original_output
    assert all(Path(p).read_bytes() == content
               for p, content in original_receipts.items())
    assert json.loads((project / "runs/plan.json").read_text())["goal"] == "Run the next site phase"


@pytest.mark.parametrize("first_failed", [False, True])
def test_second_approved_phase_finishes_while_retaining_exact_prior_results(tmp_path, monkeypatch, first_failed):
    """A new successful phase can retain both passed data and failed-run history."""
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry"))
    project = _project(tmp_path)
    ki = _ki(tmp_path, "M")
    tool = ki.root / "tools/run.py"
    next_tool = ki.root / "tools/next.py"
    next_tool.write_bytes(tool.read_bytes())
    if first_failed:
        tool.write_text(tool.read_text() + "\nraise SystemExit(1)\n")
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    planning = _drive_planning(tmp_path, ki, project)
    if not first_failed:
        planning.session.plan["steps"][0]["kind"] = "prepare"
        assert planning.session.write_plan(planning.session.plan, planning.session.inventory) == []
    review = flowrun.after(project, planning, "Plan ready.", setup_ok=True)
    _approve(project, ki, review)
    execution = flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None, "go")
    api.execute_tool("run_ki_tool", {"tool_path": "tools/run.py",
                     "arguments": ["outputs/prior/result.csv"],
                     "plan_step_id": execution.session.plan["steps"][0]["id"]},
                     ki, _cfg(project), project_mode=True, flow=execution.session)
    if not first_failed:
        flowrun.after(project, execution, "Data phase done.", setup_ok=True)
        assert execution.session.state.value == "COMPLETED"
    # An executing agent may revise a failed attempt before closing its turn.
    # This is the same explicit replan route; no state or receipt is fabricated.
    original_output = (project / "outputs/prior/result.csv").read_bytes()
    receipt_dir = project / ".geoforge/receipts/model-runs"
    original_receipts = {path: path.read_bytes() for path in receipt_dir.glob("*.json")}
    original_approval = json.loads((project / "runs/approval.json").read_text())
    continuation = flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None,
                                "Continue with the next phase")
    api.execute_tool("request_replan", {"reason": "Next phase, preserving prior evidence"}, ki,
                     _cfg(project), project_mode=True, flow=continuation.session)
    pj, inventory = continuation.session.plan, continuation.session.inventory
    pj["goal"] = "Run the next phase"
    pj["steps"][0].update(id="M:next_phase", kind="run", tool=str(next_tool))
    api.execute_tool("write_plan", {"plan": pj, "data_inventory": inventory}, ki,
                     _cfg(project), project_mode=True, flow=continuation.session)
    next_review = flowrun.after(project, continuation, "Next phase plan ready.", setup_ok=True)
    _approve(project, ki, next_review)
    next_turn = flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None, "go")
    before_run = next_turn.session.evidence()
    assert before_run["steps_missing"] == ["M:next_phase"]
    assert not before_run["receipts_verified"] and before_run["runs_bound"] == 0
    api.execute_tool("run_ki_tool", {"tool_path": "tools/next.py", "arguments": ["outputs/next/result.csv"],
                     "plan_step_id": "M:next_phase"}, ki, _cfg(project), project_mode=True,
                     flow=next_turn.session)
    result = flowrun.after(project, next_turn, "Next phase done.", setup_ok=True)
    assert next_turn.session.state.value == "COMPLETED", result.message
    evidence = next_turn.session.evidence()
    assert evidence["receipts_verified"] and evidence["validation"] == "passed"
    assert evidence["steps_passed"] == ["M:next_phase"] and evidence["runs_bound"] == 1
    assert evidence["unreceipted_artifacts"] == []
    historical, = evidence["historical_outputs"]
    assert historical["path"] == "outputs/prior/result.csv"
    assert historical["validation"] == ("failed" if first_failed else "passed")
    assert historical["approval_sha256"] == original_approval["signature"]["value"]
    assert historical["satisfies_current_step"] is False
    assert (project / "outputs/prior/result.csv").read_bytes() == original_output
    assert all(path.read_bytes() == content for path, content in original_receipts.items())
