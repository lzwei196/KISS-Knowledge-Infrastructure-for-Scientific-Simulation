"""Regression for CRHM's accepted prose-only staging/check/promotion steps."""
import copy
import json

import pytest

from kiss_cli import api
from .test_flowgate import _cfg, _ki, _plan, _session


@pytest.fixture(autouse=True)
def isolated_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "signing-keys"))


def case(tmp_path):
    ki = _ki(tmp_path, "CRHM")
    project, flow = _session(tmp_path, ki, [
        ("task_received", None), ("kis_resolved", {"selected_kis": ["CRHM"]})])
    plan, inventory = _plan(ki)
    return ki, project, flow, plan, inventory


def test_actual_nine_step_shape_cannot_hide_adapters_in_null_check_notes(tmp_path):
    ki, project, flow, plan, inventory = case(tmp_path)
    template = plan["steps"][0]
    names = ["preflight", "prepare_reference_run_dir", "run_badlake", "run_badlake_repeat",
             "parse_native_output", "raw_field_check", "plot_badlake", "water_balance", "promote_results"]
    unbound = {"prepare_reference_run_dir", "raw_field_check", "promote_results"}
    plan["steps"] = []
    for name in names:
        step = copy.deepcopy(template)
        step.update(id=f"CRHM:{name}", outputs=[])
        if name == "preflight" or name in unbound:
            step.update(kind="check", tool=None)
            step["note"] = ("PROPOSED PROJECT-LOCAL REPAIR, executed by GeoForge at the approval boundary. "
                            "Adapter: project_tools/CRHM-8d246061/refcase_stage_then_check.py, source_sha256 abc.")
        if name == "preflight":
            step.update(inputs=[], note="Host-managed installation preflight")
        plan["steps"].append(step)
    result = api.execute_tool("write_plan", {"plan": plan, "data_inventory": inventory},
                              ki, _cfg(project), project_mode=True, flow=flow)
    assert result.startswith("PLAN NOT WRITTEN")
    for name in unbound:
        assert f"CRHM:{name}" in result
    assert "step 'CRHM:preflight'" not in result
    assert "hash-bound project_data_tool" in result and "never run the scientific model" in result
    assert not (project / "runs/plan.json").exists()
    records = [json.loads(line) for line in (project / ".geoforge/plan-validation.jsonl").read_text(encoding="utf-8").splitlines()]
    assert records[-1]["result"] == "rejected" and records[-1]["error_count"] == 3
    # The new submission rule does not retroactively change execution validation.
    errors = flow.flow.plan.validate(plan, inventory, [ki.name], {ki.name: ki.root},
                                     project=project, for_execution=True)
    assert not any("GeoForge does not execute custom checks" in error for error in errors)


@pytest.mark.parametrize("step_id", ["preflight", "CRHM:preflight"])
def test_canonical_host_preflight_remains_reviewable(tmp_path, step_id):
    ki, _project, flow, plan, inventory = case(tmp_path)
    plan["steps"] = [{"id": step_id, "ki": ki.name, "kind": "check", "tool": None,
                      "inputs": [], "outputs": [], "status": "planned"}]
    assert flow.write_plan(plan, inventory) == []


def test_preflight_label_does_not_authorize_scientific_inputs(tmp_path):
    _ki_obj, _project, flow, plan, inventory = case(tmp_path)
    plan["steps"][0].update(id="CRHM:preflight", kind="check", tool=None, outputs=[])
    assert any("has no tool" in error for error in flow.write_plan(plan, inventory))


def test_hash_bound_project_check_and_real_ki_check_are_accepted(tmp_path):
    ki, project, flow, plan, inventory = case(tmp_path)
    authored = json.loads(api.execute_tool("write_project_data_tool", {
        "ki": ki.name, "name": "inspect_reference", "source": "print('inspection only')\n", "purpose": "check"},
        ki, _cfg(project), project_mode=True, flow=flow))
    step = plan["steps"][0]
    step.update(id="CRHM:raw_field_check", kind="check", tool=authored["tool"],
                project_data_tool=authored["project_data_tool"], outputs=["inspection_report"])
    assert flow.write_plan(plan, inventory) == []
    assert not (project / "outputs").exists()  # authoring/review does not execute source
    step.pop("project_data_tool")
    step.update(tool=str(ki.root / "tools/run.py"), id="CRHM:ki_check")
    assert flow.write_plan(plan, inventory) == []


def test_project_data_binding_cannot_be_used_for_a_model_run(tmp_path):
    ki, project, flow, plan, inventory = case(tmp_path)
    authored = json.loads(api.execute_tool("write_project_data_tool", {
        "ki": ki.name, "name": "inspect_reference", "source": "print('inspection only')\n", "purpose": "check"},
        ki, _cfg(project), project_mode=True, flow=flow))
    plan["steps"][0].update(kind="model_run", tool=authored["tool"], project_data_tool=authored["project_data_tool"])
    assert any("never model execution" in error for error in flow.write_plan(plan, inventory))


def test_live_crhm_external_binary_environment_is_rejected_at_submission(tmp_path):
    ki, project, flow, plan, inventory = case(tmp_path)
    plan["steps"][0]["env"] = {"CRHM_BIN": str(tmp_path / "shared-bin/crhm.exe"), "TZ": "UTC0"}
    result = api.execute_tool("write_plan", {"plan": plan, "data_inventory": inventory},
                              ki, _cfg(project), project_mode=True, flow=flow)
    assert result.startswith("PLAN NOT WRITTEN")
    assert "env path for 'CRHM_BIN' is outside the project and KI" in result
    assert not (project / "runs/plan.json").exists()
    del plan["steps"][0]["env"]["CRHM_BIN"]
    assert flow.write_plan(plan, inventory) == []
    assert json.loads((project / "runs/plan.json").read_text())["steps"][0]["env"] == {"TZ": "UTC0"}
