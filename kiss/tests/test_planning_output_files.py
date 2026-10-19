"""Future output folders are rejected before staging; filenames are not guessed."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import api, flowgate, flowrun, plan_review, planning_outputs
from .test_ordinary_invocation_review import case as review_case
from .test_flowgate import _cfg
from .test_plan_review_lifecycle import review_project, _click, _draft


def documents(path="outputs/new_run", *, cwd="outputs/new_run"):
    return ({"steps": [{"id": "run", "ki": "M", "tool": "engine.exe", "kind": "model_run",
            "command": [], "cwd": cwd, "inputs": [], "outputs": ["result"]}]},
            {"items": [{"id": "result", "local_paths": [path]}]})


def test_future_run_directory_currently_passes_shared_binding_but_is_caught_early(tmp_path):
    flow = flowgate.load()
    plan, inventory = documents()
    assert not (tmp_path / "outputs/new_run").exists()
    assert flow.declared_outputs.binding(tmp_path, plan["steps"][0], inventory)
    errors = planning_outputs.plan_errors(plan, inventory, tmp_path)
    assert len(errors) == 1
    assert "output 'result'" in errors[0] and "working directory" in errors[0]
    assert "exact filenames" in errors[0] and "several files" in errors[0]
    assert not (tmp_path / "outputs").exists()


@pytest.mark.parametrize("source", ["child", "cwd", "typed_cwd", "trailing", "existing", "reserved"])
def test_only_positive_directory_evidence_is_used(tmp_path, source):
    plan, inventory = documents(cwd=".")
    if source == "child":
        inventory["items"].append({"id": "staged", "local_paths": ["outputs/new_run/Trial.inp"]})
    elif source == "cwd":
        plan["steps"].append({"id": "later", "cwd": "outputs/new_run/child"})
    elif source == "typed_cwd":
        plan["steps"].append({"id": "reader", "project_data_tool": {"cwd": "outputs/new_run"}})
    elif source == "trailing":
        inventory["items"][0]["local_paths"] = ["outputs/new_run/"]
    elif source == "existing":
        (tmp_path / "outputs/new_run").mkdir(parents=True)
    else:
        inventory["items"][0]["local_paths"] = ["outputs"]
    assert len(planning_outputs.plan_errors(plan, inventory, tmp_path)) == 1


@pytest.mark.parametrize("filename", ["RESULT", "result.nc", "file with spaces", "run2", "run.table"])
@pytest.mark.parametrize("existing", [False, True])
def test_actual_and_future_extensionless_or_dotted_files_are_accepted(tmp_path, filename, existing):
    plan, inventory = documents("outputs/" + filename, cwd=".")
    plan["steps"].append({"id": "other", "cwd": "outputs/run"})
    inventory["items"].append({"id": "unrelated", "local_paths": ["outputs/run/input.dat"]})
    if existing:
        (tmp_path / "outputs").mkdir()
        (tmp_path / "outputs" / filename).write_text("real file")
    assert planning_outputs.plan_errors(plan, inventory, tmp_path) == []


def test_several_exact_files_can_share_one_output_item(tmp_path):
    plan, inventory = documents()
    inventory["items"][0]["local_paths"] = ["outputs/new_run/temp.out", "outputs/new_run/water.out"]
    assert planning_outputs.plan_errors(plan, inventory, tmp_path) == []


def test_project_root_cwd_does_not_classify_descendant_files_as_directories(tmp_path):
    plan, inventory = documents("outputs/result", cwd=".")
    assert planning_outputs.plan_errors(plan, inventory, tmp_path) == []


def test_normalized_absolute_cwd_and_relative_output_have_same_identity(tmp_path):
    plan, inventory = documents(cwd=str(tmp_path / "outputs/new_run"))
    assert planning_outputs.plan_errors(plan, inventory, tmp_path)


@pytest.mark.parametrize("typed", ["project_data_tool", "calibration", "stdout_artifact"])
def test_specialized_output_contracts_keep_their_existing_policy(tmp_path, typed):
    plan, inventory = documents()
    plan["steps"][0][typed] = {}
    assert planning_outputs.plan_errors(plan, inventory, tmp_path) == []


def test_input_directories_are_not_newly_forbidden(tmp_path):
    plan, inventory = documents("outputs/report.json", cwd=".")
    inventory["items"].append({"id": "input_directory", "local_paths": ["inputs/case/"]})
    plan["steps"][0]["inputs"] = ["input_directory"]
    assert planning_outputs.plan_errors(plan, inventory, tmp_path) == []


def configure(plan, inventory):
    plan["steps"][0].update(command=[], cwd="outputs/future_run", kind="check", outputs=["result"])
    inventory["items"] = [{"id": "result", "required_by": ["M"], "status": "missing",
        "acceptable_sources": ["generated"], "chosen_source": "generated", "local_paths": ["outputs/future_run"],
        "agent_resolvable": True, "needs_user": False, "output_validation": "json_report_v1"}]


def test_api_write_plan_returns_actionable_error_without_writing(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    ki, project, fs, plan, inventory = review_case(tmp_path)
    configure(plan, inventory)
    output = api.execute_tool("write_plan", {"plan": plan, "data_inventory": inventory},
        ki, _cfg(project), project_mode=True, flow=fs)
    assert output.startswith("PLAN NOT WRITTEN") and "individual output file" in output
    assert not (project / "runs/plan.json").exists()


def test_cli_direct_write_is_refused_at_turn_handoff(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    _ki, project, fs, plan, inventory = review_case(tmp_path)
    configure(plan, inventory)
    fs.flow.plan.write_artifacts(project, plan, inventory)
    turn = flowrun.Turn(fs, False, "", False, SimpleNamespace(provider="claude"), "fixture", provider_succeeded=True)
    result = flowrun.after(project, turn, "Draft saved")
    assert result.request is None
    assert "individual output file" in (project / "runs/plan-validation.txt").read_text("utf-8")
    assert not (project / "runs/approval.json").exists()


def test_directly_authored_directory_output_cannot_be_approved(review_project):
    env = review_project
    _draft(env)
    flow = flowgate.load()
    plan, inventory = flow.plan.read_artifacts(env.project)
    configure(plan, inventory)
    flow.plan.write_artifacts(env.project, plan, inventory)
    fs = flowgate.FlowSession.open(env.project, {"M": env.ki.root}, database_access_mode="off")
    card = plan_review.issue(env.project, fs, plan, inventory, "fixture")
    assert any("individual output file" in error for error in card["plan_review"]["not_ready"])
    result = _click(env, card)
    assert "individual output file" in result.replan_reason
    assert not (env.project / "runs/approval.json").exists()
