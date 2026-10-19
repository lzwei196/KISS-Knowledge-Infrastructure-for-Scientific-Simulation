"""Exact binding-shape feedback; no adapter or model execution."""
from __future__ import annotations

import copy
import json

import pytest

from kiss_cli import api, flowgate, project_data_tools
from .test_flowgate import _cfg
from .test_project_data_tools import case
from .test_project_data_output_contracts import typed_case
from .test_project_data_formats import WEATHER_CONTRACT

flowgate.load()
from ki_tools_common.flow import project_tools


@pytest.fixture(autouse=True)
def keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))


def authored_step(project, version=1):
    authored = project_data_tools.write(project, "M", "reader", "# not executed\n", "reader",
        **({"output_formats": [copy.deepcopy(WEATHER_CONTRACT)]} if version == 2 else {}))
    step = copy.deepcopy(authored["step_template"])
    if version == 1:
        step["outputs"] = ["inspection"]
    return authored, step


@pytest.mark.parametrize("version", [1, 2])
def test_writer_binding_and_step_template_remain_exact_and_copyable(tmp_path, version):
    authored, step = authored_step(tmp_path, version)
    expected = project_tools.FIELDS | ({"output_formats"} if version == 2 else set())
    assert set(authored["project_data_tool"]) == expected
    assert step["project_data_tool"] == authored["project_data_tool"]
    before = copy.deepcopy(step)
    assert project_tools.step_errors(step, tmp_path) == []
    assert step == before
    assert authored["executed"] is False
    assert not (tmp_path / "outputs").exists()


@pytest.mark.parametrize("missing", sorted(project_tools.FIELDS))
def test_missing_field_is_named_without_changing_rejected_binding(tmp_path, missing):
    _, step = authored_step(tmp_path)
    del step["project_data_tool"][missing]
    before = copy.deepcopy(step)
    error, = project_tools.step_errors(step, tmp_path)
    assert f"missing fields=['{missing}']" in error
    assert "unexpected fields=[]" in error
    assert "expected version: integer 1 or 2" in error
    assert f"actual version={'<missing>' if missing == 'version' else '1 (int)'}" in error
    assert step == before


@pytest.mark.parametrize("extra", ["args", "outputs", "inputs", "tool", "status", "output_formats"])
def test_unexpected_fields_are_named_without_echoing_their_values(tmp_path, extra):
    _, step = authored_step(tmp_path)
    step["project_data_tool"][extra] = {"sensitive_payload": "never-echo-this-value"}
    error, = project_tools.step_errors(step, tmp_path)
    assert f"unexpected fields=['{extra}']" in error
    assert "missing fields=[]" in error
    assert "never-echo" not in error and "sensitive_payload" not in error


def test_v2_missing_contract_and_arguments_alias_have_precise_differences(tmp_path):
    _, step = authored_step(tmp_path, 2)
    binding = step["project_data_tool"]
    binding["args"] = binding.pop("arguments")
    binding.pop("output_formats")
    error, = project_tools.step_errors(step, tmp_path)
    assert "actual version=2 (int)" in error
    assert "missing fields=['arguments', 'output_formats']" in error
    assert "unexpected fields=['args']" in error


@pytest.mark.parametrize("version,label", [
    (True, "True (bool)"), (2.0, "2.0 (float)"), (0, "0 (int)"), (3, "3 (int)"),
    ("2", "'2' (str)"), (None, "<NoneType>"), ([2], "<list>"),
    ({"secret": "never-echo"}, "<dict>"), ("private-version-value", "<str>"),
])
def test_unsupported_versions_remain_rejected_with_safe_actual_type(tmp_path, version, label):
    _, step = authored_step(tmp_path, 2 if version == 2 else 1)
    step["project_data_tool"]["version"] = version
    error, = project_tools.step_errors(step, tmp_path)
    assert f"actual version={label}" in error
    assert "expected version: integer 1 or 2" in error
    assert "never-echo" not in error and "private-version-value" not in error


def test_field_diagnostics_are_bounded_and_handle_nonstring_keys(tmp_path):
    _, step = authored_step(tmp_path)
    binding = step["project_data_tool"]
    binding.update({f"extra_{i:03}": "never-echo" for i in range(100)})
    binding[7] = "never-echo"
    binding["bad\nfield" + "x" * 10000] = "never-echo"
    error, = project_tools.step_errors(step, tmp_path)
    assert "(82 more)" in error
    assert len(error) < 1200
    assert "never-echo" not in error and "\n" not in error
    for key in tuple(binding):
        if isinstance(key, str) and key.startswith("extra_"):
            del binding[key]
    error, = project_tools.step_errors(step, tmp_path)
    assert "<invalid int field name>" in error
    assert "<invalid str field name>" in error


@pytest.mark.parametrize("version", [1, 2])
def test_valid_binding_still_passes_real_plan_submission(tmp_path, version):
    ki, project, session, plan, inventory, _ = (typed_case(tmp_path) if version == 2 else case(tmp_path))
    response = api.execute_tool("write_plan", {"plan": plan, "data_inventory": inventory},
        ki, _cfg(project), project_mode=True, flow=session)
    assert response.startswith("Plan files written"), response
    assert json.loads((project / "runs/plan.json").read_text())["steps"][0]["project_data_tool"] == plan["steps"][0]["project_data_tool"]
    assert not (project / "runs/approval.json").exists()
    assert not (project / "outputs").exists()


@pytest.mark.parametrize("defect", ["args_alias", "nested_outputs", "missing_cwd", "whole_response"])
def test_real_api_rejection_keeps_exact_diff_for_retry_without_persisting_plan(tmp_path, defect):
    ki, project, session, plan, inventory, authored = case(tmp_path)
    binding = plan["steps"][0]["project_data_tool"]
    if defect == "args_alias":
        binding["args"] = binding.pop("arguments")
        expected = ("missing fields=['arguments']", "unexpected fields=['args']")
    elif defect == "nested_outputs":
        binding["outputs"] = ["never-echo-this-value"]
        expected = ("missing fields=[]", "unexpected fields=['outputs']")
    elif defect == "missing_cwd":
        binding.pop("cwd")
        expected = ("missing fields=['cwd']", "unexpected fields=[]")
    else:
        plan["steps"][0]["project_data_tool"] = copy.deepcopy(authored)
        expected = ("actual version=<missing>", "'step_template'", "'project_data_tool'")
    response = api.execute_tool("write_plan", {"plan": plan, "data_inventory": inventory},
        ki, _cfg(project), project_mode=True, flow=session)
    assert response.startswith("PLAN NOT WRITTEN"), response
    assert "step 'M:read'" in response
    for fragment in expected:
        assert fragment in response
        assert any(fragment in error for error in session.plan_submission_errors)
    diagnostic = (project / flowgate.PLAN_VALIDATION_LOG).read_text(encoding="utf-8")
    assert "never-echo-this-value" not in response + diagnostic
    assert not (project / "runs/plan.json").exists()
    assert not (project / "runs/approval.json").exists()
    assert session.state.value == "PLANNING"


def test_api_describes_correct_binding_copy_boundaries(tmp_path):
    ki, _, session, _, _, _ = case(tmp_path)
    description = next(tool["description"] for tool in api.tool_schemas(
        ki, project_mode=True, flow=session) if tool["name"] == "write_project_data_tool")
    assert "returned step_template" in description
    assert "inputs and outputs are step fields, not binding fields" in description
    assert "use arguments, not args" in description
