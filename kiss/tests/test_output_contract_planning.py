"""JSON role mistakes are repaired before approval, with unchanged run validators."""
from __future__ import annotations

import copy
import json

import pytest

from kiss_cli import api, flowrun, plan_review
from ki_tools_common.flow import declared_outputs, plan as plan_policy

from .test_declared_output_validation import case, invoke
from .test_flowgate import _cfg, _ki, _plan, _session
from .test_plan_review_lifecycle import review_project, _draft, _click


@pytest.fixture
def planning(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry.json"))
    ki = _ki(tmp_path)
    project, session = _session(tmp_path, ki, [
        ("task_received", None), ("kis_resolved", {"selected_kis": [ki.name]})])
    plan, inventory = _plan(ki)
    plan["steps"][0].update(kind="check", inputs=[], outputs=["parsed"])
    inventory["items"] = [{"id": "parsed", "status": "missing", "required_by": ["M"],
                           "local_paths": ["outputs/read/parsed.json"], "needs_user": False,
                           "agent_resolvable": True}]
    return ki, project, session, plan, inventory


def test_api_rejects_ambiguous_json_before_write_then_accepts_deliberate_report(planning):
    ki, project, session, plan, inventory = planning
    original = copy.deepcopy((plan, inventory))
    result = api.execute_tool("write_plan", {"plan": plan, "data_inventory": inventory},
                              ki, _cfg(project), project_mode=True, flow=session)
    assert result.startswith("PLAN NOT WRITTEN")
    assert "'parsed': JSON output needs an explicit validation role before review" in result
    assert "output_validation:'json_report_v1'" in result
    assert "output_role:'scientific_result'" in result
    assert "supplies no numeric model evidence" in result
    assert not (project / "runs/plan.json").exists()
    assert not (project / "runs/approval.json").exists()
    assert (plan, inventory) == original

    inventory["items"][0]["output_validation"] = "json_report_v1"
    result = api.execute_tool("write_plan", {"plan": plan, "data_inventory": inventory},
                              ki, _cfg(project), project_mode=True, flow=session)
    assert result.startswith("Plan files written")
    saved = json.loads((project / "runs/data-inventory.json").read_text(encoding="utf-8"))
    assert saved == inventory
    assert not (project / "runs/approval.json").exists()


@pytest.mark.parametrize("suffix", [".json", ".JSON"])
def test_legacy_approved_json_default_is_unchanged_but_new_review_requires_intent(planning, suffix):
    ki, project, _session_obj, plan, inventory = planning
    inventory["items"][0]["local_paths"] = ["outputs/read/parsed" + suffix]
    before = declared_outputs.binding(project, plan["steps"][0], inventory)
    assert before["outputs"][0]["validation"] == "scientific"
    for mode in ({}, {"for_execution": True}):
        assert plan_policy.validate(plan, inventory, ["M"], {"M": ki.root}, project=project, **mode) == []
    assert plan_policy.validate(plan, inventory, ["M"], {"M": ki.root}, project=project, for_review=True)
    assert declared_outputs.binding(project, plan["steps"][0], inventory) == before


def test_explicit_scientific_intent_preserves_numeric_validator_and_cannot_grant_report_pass(planning):
    ki, project, _session_obj, plan, inventory = planning
    inventory["items"][0]["output_role"] = "scientific_result"
    assert plan_policy.validate(plan, inventory, ["M"], {"M": ki.root}, project=project, for_review=True) == []
    output = project / inventory["items"][0]["local_paths"][0]
    output.parent.mkdir(parents=True)
    output.write_text('{"result":"no numeric model evidence"}', encoding="utf-8")
    result, binding = declared_outputs.validate(project, ki.root, plan["steps"][0], inventory,
                                               [output], run_facts={"errored": False}, physical=False)
    assert binding["outputs"][0]["validation"] == "scientific"
    assert result["status"] != "passed"
    assert any(not c["ok"] and c["check"].startswith("numeric_content:") for c in result["checks"])


@pytest.mark.parametrize("role", ["report", None, {"scientific_result": True}, False])
def test_unknown_role_has_actionable_review_error(planning, role):
    ki, project, _session_obj, plan, inventory = planning
    inventory["items"][0]["output_role"] = role
    errors = plan_policy.validate(plan, inventory, ["M"], {"M": ki.root}, project=project, for_review=True)
    assert any("output_role supports only 'scientific_result'" in error for error in errors)


def test_role_and_report_cannot_conflict(planning):
    ki, project, _session_obj, plan, inventory = planning
    inventory["items"][0].update(output_role="scientific_result", output_validation="json_report_v1")
    errors = plan_policy.validate(plan, inventory, ["M"], {"M": ki.root}, project=project, for_review=True)
    assert any("not both" in error for error in errors)


@pytest.mark.parametrize("special", ["project_data_tool", "stdout_artifact", "calibration", "input", "download"])
def test_specialized_outputs_and_inputs_do_not_get_ordinary_json_rules(planning, special):
    _ki_obj, _project, _session_obj, plan, inventory = planning
    step = plan["steps"][0]
    if special == "input":
        step.update(inputs=step["outputs"], outputs=[])
    elif special == "download":
        step.update(kind="download", tool=None)
    else:
        step[special] = {"version": 1}
    assert plan_policy.output_contract_review_errors(plan, inventory) == []
    inventory["items"][0]["output_role"] = "scientific_result"
    assert any("only to ordinary KI-produced" in error for error in
               plan_policy.output_contract_review_errors(plan, inventory))


@pytest.mark.parametrize("special", ["project_data_tool", "stdout_artifact", "calibration", "download"])
def test_mixed_json_producers_cannot_skip_review_by_sharing_an_inventory_id(planning, special):
    _ki_obj, _project, _session_obj, plan, inventory = planning
    second = {**plan["steps"][0], "id": "other-producer"}
    if special == "download":
        second.update(kind="download", tool=None)
    else:
        second[special] = {"version": 1}
    plan["steps"].append(second)
    errors = plan_policy.output_contract_review_errors(plan, inventory)
    assert any("mixes ordinary KI and specialized/download producers" in error for error in errors)
    assert any("separate inventory IDs" in error for error in errors)


def test_numeric_outputs_still_required_for_physical_steps(planning):
    ki, project, _session_obj, plan, inventory = planning
    plan["steps"][0]["kind"] = "model_run"
    inventory["items"][0]["output_validation"] = "json_report_v1"
    errors = plan_policy.validate(plan, inventory, ["M"], {"M": ki.root}, project=project, for_review=True)
    assert any("needs at least one declared scientific result" in error for error in errors)
    inventory["items"].append({"id": "native", "status": "missing", "local_paths": ["outputs/run/native.csv"]})
    plan["steps"][0]["outputs"].append("native")
    assert plan_policy.validate(plan, inventory, ["M"], {"M": ki.root}, project=project, for_review=True) == []


@pytest.mark.parametrize("provider_kind,provider_name", [("api", "deepseek"), ("cli", "claude"),
                                                         ("cli", "codex"), ("cli", "kimi")])
def test_api_and_cli_planning_turns_receive_same_output_contract(planning, monkeypatch, provider_kind, provider_name):
    ki, project, session, plan, inventory = planning
    session.flow.plan.write_artifacts(project, plan, inventory)
    monkeypatch.setattr(flowrun, "wrapper_commands", lambda: {"run_tool": "fixture-run"})
    monkeypatch.setattr(flowrun, "_planning_worktree", lambda _project: None)
    turn = flowrun.turn(project, [ki], _cfg(project), provider_kind, provider_name, None,
                        "Inspect results", database_access_mode="off")
    text = turn.extra_prompt
    assert "[ORDINARY KI OUTPUT VALIDATION]" in text
    assert "output_validation?:'json_report_v1'" in text
    assert "output_role?:'scientific_result'" in text
    assert "a .json extension does not choose the role" in text.lower()
    assert "supplies no numeric model evidence" in text
    assert "project_data_tool, stdout_artifact or calibration" in text
    assert "record exact future local_paths and status:'missing'" in text
    assert "Record planned target paths in the rationale, not as existing local_paths" not in text


def test_new_review_diagnostics_do_not_invalidate_current_signed_evidence(case):
    c = case
    receipt = invoke(c)[0]
    before = declared_outputs.binding(c.project, c.step, c.inventory)
    assert c.fs.evidence()["receipts_verified"]
    proposed = copy.deepcopy(c.inventory)
    proposed["items"][-1].pop("output_validation")
    errors = plan_policy.output_contract_review_errors({"steps": [c.step]}, proposed)
    assert errors
    assert declared_outputs.binding(c.project, c.step, c.inventory) == before
    assert declared_outputs.receipt_errors(c.project, c.step, c.inventory, receipt) == []
    assert c.fs.evidence()["receipts_verified"]


def test_direct_review_card_explains_missing_role_before_user_click(planning):
    _ki_obj, project, session, plan, inventory = planning
    session.flow.plan.write_artifacts(project, plan, inventory)
    session.move("plan_written", {"plan_valid": True})
    card = plan_review.issue(project, session, plan, inventory, "Old draft handed off for review")
    assert any("JSON output needs an explicit validation role" in error for error in
               card["plan_review"]["not_ready"])
    assert not (project / "runs/approval.json").exists()


def test_pending_preupgrade_card_cannot_approve_ambiguous_json(review_project, monkeypatch):
    env = review_project

    def ambiguous(plan, inventory):
        plan["steps"][0].update(kind="check", inputs=[], outputs=["parsed"])
        inventory["items"] = [{"id": "parsed", "status": "missing", "required_by": ["M"],
                               "local_paths": ["outputs/read/parsed.json"], "needs_user": False,
                               "agent_resolvable": True}]

    # Reproduce a real persisted card issued before this review-only rule existed.
    with monkeypatch.context() as old_host:
        old_host.setattr(plan_policy, "output_contract_review_errors", lambda *_args: [])
        card = _draft(env, revise=ambiguous)
    result = _click(env, card)
    assert "JSON output needs an explicit validation role" in result.replan_reason
    assert not (env.project / "runs/approval.json").exists()
    assert flowrun.current_state(env.project) == "PLANNING"
