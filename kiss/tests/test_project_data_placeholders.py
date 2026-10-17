"""Reject literal template paths before approval, and at legacy dispatch boundaries."""
import copy
import json
from pathlib import Path

import pytest

from kiss_cli import api, execution, flowgate, flowrun, project_data_tools
from .test_flowgate import _cfg
from .test_project_data_tools import case


@pytest.fixture(autouse=True)
def isolated_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "signing-keys"))


def placeholder_case(tmp_path, field, value):
    c = case(tmp_path)
    binding = c[3]["steps"][0]["project_data_tool"]
    if field == "arguments":
        binding[field] = [value, "outputs/inspection.json"]
    else:
        binding[field] = value
        # Even a physically existing literal placeholder directory must be
        # refused; a generic missing-cwd error would not close this gap.
        (c[1] / value).mkdir(parents=True)
    return c


INVALID_BINDINGS = [
    ("arguments", "${KI_ROOT}/test_cases/badlake/inputs"),
    ("arguments", "${PROJECT}/inputs/raw.csv"),
    ("arguments", "--dest=${PROJECT}/outputs/inspection.json"),
    ("arguments", "${OTHER}/raw.csv"),
    ("cwd", "${PROJECT}"),
    ("cwd", "literal-${KI_ROOT}"),
]


@pytest.mark.parametrize("field,value", INVALID_BINDINGS)
def test_api_submission_refuses_placeholder_invocation_without_writing_plan(tmp_path, field, value):
    ki, project, fs, plan, inventory, _authored = placeholder_case(tmp_path, field, value)
    before = copy.deepcopy(plan)
    result = api.execute_tool("write_plan", {"plan": plan, "data_inventory": inventory},
                              ki, _cfg(project), project_mode=True, flow=fs)
    assert result.startswith("PLAN NOT WRITTEN")
    assert "unresolved placeholders" in result and field in result
    assert "literal absolute or cwd-relative paths" in result
    assert plan == before  # validation cannot silently rewrite reviewed arguments
    assert not (project / "runs/plan.json").exists()
    assert not (project / "runs/approval.json").exists()


@pytest.mark.parametrize("field,value", [INVALID_BINDINGS[0], INVALID_BINDINGS[4]])
def test_cli_saved_draft_refuses_placeholder_before_approval_card(tmp_path, field, value):
    ki, project, _fs, plan, inventory, _authored = placeholder_case(tmp_path, field, value)
    turn = flowrun.turn(project, [ki], _cfg(project), "cli", "codex", None, "Inspect local data")
    assert turn.planning_worktree is not None
    turn.session.flow.plan.write_artifacts(turn.planning_worktree, plan, inventory)
    turn.provider_succeeded = True
    result = flowrun.after(project, turn, "Saved the two draft files.")
    assert result.request is None and "unresolved placeholders" in result.message
    assert turn.session.state.value == "PLANNING"
    assert not (project / "runs/approval.json").exists()


@pytest.mark.parametrize("route", ["api", "common_dispatch"])
@pytest.mark.parametrize("field,value", [INVALID_BINDINGS[1], INVALID_BINDINGS[4]])
def test_old_signed_plan_is_refused_before_any_adapter_launch(tmp_path, monkeypatch, route, field, value):
    ki, project, fs, plan, inventory, authored = placeholder_case(tmp_path, field, value)
    # Reproduce a genuinely signed pre-fix plan, rather than patching the
    # current submission validator or bypassing approval at execution.
    fs.flow.plan.write_artifacts(project, plan, inventory)
    fs.flow.approval.approve(project, by="auto")
    fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True})
    fs.move("approved", {"approval": "OK"})
    fs.move("execution_started", {"setup_verified": True})
    assert fs.approval_status() == "OK"
    before = (project / "runs/plan.json").read_bytes()
    monkeypatch.setattr(project_data_tools, "worker_request",
                        lambda *a, **kw: pytest.fail("invalid adapter reached worker preparation"))
    binding = plan["steps"][0]["project_data_tool"]
    with pytest.raises((api.ToolError, flowgate.FlowDenied), match="unresolved placeholders"):
        if route == "api":
            api.execute_tool("run_project_data_tool", {
                "ki": ki.name, "tool_path": authored["tool"], "plan_step_id": "M:read"},
                ki, _cfg(project), project_mode=True, flow=fs)
        else:
            execution.execute_ki_tool(
                flow=fs, cfg=_cfg(project), project=project, ki=ki.name, ki_root=ki.root,
                tool=Path(authored["tool"]), arguments=binding["arguments"],
                cwd=project / binding["cwd"], plan_step_id="M:read", python_tool=True,
                timeout=binding["timeout_seconds"], project_data_tool=True)
    assert (project / "runs/plan.json").read_bytes() == before
    assert not (project / "outputs/inspection.json").exists()
    assert not list((project / ".geoforge/receipts/model-runs").glob("*.json"))


@pytest.mark.parametrize("absolute", [False, True])
def test_literal_arguments_prose_and_shipped_tool_environment_are_unchanged(tmp_path, absolute):
    ki, project, fs, plan, inventory, authored = case(tmp_path)
    binding = plan["steps"][0]["project_data_tool"]
    if absolute:
        binding["arguments"] = [str(project / value) for value in binding["arguments"]]
    plan["steps"][0]["note"] = "Use concrete paths; ${PROJECT} and ${KI_ROOT} here are prose examples."
    environment_step = {
        "id": "M:run", "ki": ki.name, "tool": str(ki.root / "tools/run.py"), "kind": "run",
        "inputs": ["forcing"], "outputs": ["q"], "status": "planned",
        "command": [], "cwd": ".",
        "env": {"MODEL_OUTPUT": "${PROJECT}/outputs/model.csv", "MODEL_KI_ROOT": "${KI_ROOT}", "TZ": "UTC0"},
    }
    plan["steps"].append(environment_step)
    before = copy.deepcopy(plan)
    result = api.execute_tool("write_plan", {"plan": plan, "data_inventory": inventory},
                              ki, _cfg(project), project_mode=True, flow=fs)
    assert result.startswith("Plan files written")
    assert plan == before
    assert json.loads((project / "runs/plan.json").read_text(encoding="utf-8")) == before
    assert fs.flow.plan.step_environment(environment_step, project, ki.root) == {
        "MODEL_OUTPUT": str(project / "outputs/model.csv"), "MODEL_KI_ROOT": str(ki.root), "TZ": "UTC0"}
    fs.flow.approval.approve(project, by="auto")
    fs.reload_artifacts()
    _, actual, cwd, timeout = project_data_tools.invocation(fs, ki.name, Path(authored["tool"]), "M:read", {})
    assert actual == binding["arguments"] and cwd == project and timeout == 120
    with pytest.raises(flowgate.FlowDenied, match="differs from the approved plan"):
        project_data_tools.invocation(fs, ki.name, Path(authored["tool"]), "M:read",
                                      {"arguments": ["inputs/different.csv", "outputs/inspection.json"]})
