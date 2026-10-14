"""New reviews cannot display invocation fields a typed executor ignores."""
from __future__ import annotations

import copy

import pytest

from kiss_cli import api
from ki_tools_common.flow import plan as policy
from .test_calibration_flow_binding import case as calibration_case
from .test_flowgate import _cfg, _ki, _plan, _session
from .test_project_data_tools import case as data_case


@pytest.fixture(autouse=True)
def keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))


@pytest.mark.parametrize("ignored", [
    {"command": ["--input", "inputs/raw.csv", "--output", "outputs/inspection.json"]},
    {"cwd": "."},
    {"command": [], "cwd": "."},
    {"command": None},
])
def test_project_data_ignored_fields_are_rejected_before_review(tmp_path, ignored):
    ki, project, session, plan, inventory, _authored = data_case(tmp_path)
    step = plan["steps"][0]
    step["project_data_tool"]["arguments"] = []
    step.update(ignored)
    before = copy.deepcopy((plan, inventory))
    # Historical typed execution still uses only its typed binding.
    assert policy.step_invocation(step, project) == (None, None)
    assert policy.validate(plan, inventory, [ki.name], {ki.name: ki.root},
                           project=project, for_execution=True) == []
    errors = policy.validate(plan, inventory, [ki.name], {ki.name: ki.root},
                             project=project, for_review=True)
    assert len(errors) == 1
    assert "step 'M:read'" in errors[0] and "ignores top-level" in errors[0]
    assert "project_data_tool.arguments" in errors[0] and "project_data_tool.cwd" in errors[0]
    assert (plan, inventory) == before
    result = api.execute_tool("write_plan", {"plan": plan, "data_inventory": inventory},
                              ki, _cfg(project), project_mode=True, flow=session)
    assert result.startswith("PLAN NOT WRITTEN") and "ignores top-level" in result
    assert not (project / "runs/plan.json").exists()
    assert not (project / "runs/approval.json").exists()


@pytest.mark.parametrize("arguments", [[], ["inputs/raw.csv", "outputs/inspection.json"]])
def test_project_data_actual_binding_remains_reviewable(tmp_path, arguments):
    ki, project, _session_obj, plan, inventory, _authored = data_case(tmp_path)
    plan["steps"][0]["project_data_tool"]["arguments"] = arguments
    assert policy.validate(plan, inventory, [ki.name], {ki.name: ki.root},
                           project=project, for_review=True) == []


@pytest.mark.parametrize("ignored", [{"command": ["--budget", "99"]}, {"cwd": "."},
                                    {"command": [], "cwd": None}])
def test_calibration_uses_only_its_typed_settings(calibration_case, ignored):
    session, plan, inventory, _adapter = calibration_case
    assert session.write_plan(plan, inventory) == []
    step = plan["steps"][0]
    assert policy.validate(plan, inventory, ["M"], session.ki_roots,
                           project=session.project, for_review=True) == []
    step.update(ignored)
    assert policy.validate(plan, inventory, ["M"], session.ki_roots,
                           project=session.project, for_execution=True) == []
    errors = policy.validate(plan, inventory, ["M"], session.ki_roots,
                             project=session.project, for_review=True)
    assert len(errors) == 1
    assert "step 'M:calibrate'" in errors[0] and "calibration ignores top-level" in errors[0]
    assert "typed calibration settings" in errors[0]
    assert "calibration.arguments" not in errors[0] and "calibration.cwd" not in errors[0]


def test_ordinary_tool_command_and_cwd_are_still_reviewed(tmp_path):
    ki = _ki(tmp_path)
    project, _session_obj = _session(tmp_path, ki)
    plan, inventory = _plan(ki)
    plan["steps"][0].update(inputs=[], outputs=[], command=["outputs/science.csv"], cwd=".")
    assert policy.validate(plan, inventory, [ki.name], {ki.name: ki.root},
                           project=project, for_review=True) == []
    assert policy.step_invocation(plan["steps"][0], project) == (["outputs/science.csv"], project)
