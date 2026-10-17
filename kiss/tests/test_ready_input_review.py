"""Reject false ready-input claims at review, before unchanged receipt capture.

All files and signing state are isolated fixtures; no provider or model runs.
"""
from __future__ import annotations

import copy

import pytest

from kiss_cli import api, flowgate
from ki_tools_common.flow import plan as policy, receipts
from .test_flowgate import _cfg, _ki, _plan, _session
from .test_plan_review_lifecycle import review_project, _draft, _click


@pytest.fixture
def local_plan(tmp_path):
    ki = _ki(tmp_path)
    project, session = _session(tmp_path, ki, [
        ("task_received", None), ("kis_resolved", {"selected_kis": [ki.name]})])
    plan, inventory = _plan(ki)
    plan["steps"][0]["outputs"] = []
    plan["steps"][0].update(command=["outputs/q.csv"], cwd=".")
    inventory["items"][0].update(status="ready", chosen_source="existing_local",
                                 local_paths=["inputs/case.dat"])
    return ki, project, session, plan, inventory


def validate(case, **mode):
    ki, project, _session_obj, plan, inventory = case
    return policy.validate(plan, inventory, [ki.name], {ki.name: ki.root}, project=project, **mode)


def test_ready_candidates_are_all_required_not_alternatives(local_plan, tmp_path):
    ki, project, session, plan, inventory = local_plan
    shared = tmp_path / "shared/runtime.exe"
    shared.parent.mkdir()
    shared.write_bytes(b"fixture, never executed")
    inventory["items"][0]["local_paths"] = [str(shared), "binaries/missing.exe"]
    before = copy.deepcopy((plan, inventory))
    errors = validate(local_plan, for_review=True)
    assert len(errors) == 1
    assert "step 'M:run'" in errors[0] and "ready input 'forcing'" in errors[0]
    assert "binaries/missing.exe" in errors[0]
    assert "not alternatives" in errors[0] and "preflight does not choose" in errors[0]
    assert (plan, inventory) == before
    assert shared.read_bytes() == b"fixture, never executed"
    result = api.execute_tool("write_plan", {"plan": plan, "data_inventory": inventory},
                              ki, _cfg(project), project_mode=True, flow=session)
    assert result.startswith("PLAN NOT WRITTEN") and "binaries/missing.exe" in result
    assert not (project / "runs/approval.json").exists()


@pytest.mark.parametrize("spelling", ["relative", "project_token", "shared_file", "shared_directory"])
def test_actual_local_and_shared_paths_remain_reviewable(local_plan, tmp_path, spelling):
    _ki_obj, project, _session_obj, _plan_obj, inventory = local_plan
    path = (tmp_path / "shared/data" if spelling.startswith("shared") else project / "inputs/case.dat")
    if spelling == "shared_directory":
        path.mkdir(parents=True)
        (path / "reference.dat").write_bytes(b"real fixture input")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"real fixture input")
    raw = ("inputs/case.dat" if spelling == "relative" else
           "${PROJECT}/inputs/case.dat" if spelling == "project_token" else str(path))
    inventory["items"][0]["local_paths"] = [raw]
    assert validate(local_plan, for_review=True) == []


@pytest.mark.parametrize("status", ["missing", "resolved"])
@pytest.mark.parametrize("delivery", [None, "served", "subset", "manual"])
def test_pending_and_acquisition_paths_are_not_readiness_claims(local_plan, status, delivery):
    _ki_obj, project, _session_obj, plan, inventory = local_plan
    inventory["items"][0].update(status=status, delivery=delivery)
    assert policy.ready_input_review_errors(plan, inventory, project) == []


@pytest.mark.parametrize("claim", [{"dataset_id": "source_a", "delivery": "served"},
                                  {"decision": "preflight chooses"},
                                  {"chosen_source": "KI default", "agent_resolvable": True}])
def test_free_text_or_dataset_fields_do_not_excuse_a_false_ready_claim(local_plan, claim):
    _ki_obj, project, _session_obj, plan, inventory = local_plan
    inventory["items"][0].update(claim)
    assert policy.ready_input_review_errors(plan, inventory, project)


@pytest.mark.parametrize("producer_kind", ["run", "download"])
def test_earlier_producer_can_make_an_input_after_review(local_plan, producer_kind):
    ki, project, _session_obj, plan, inventory = local_plan
    producer = {"id": "make", "ki": ki.name, "kind": producer_kind, "status": "planned",
                "tool": str(ki.root / "tools/run.py") if producer_kind == "run" else None,
                "inputs": [], "outputs": ["forcing"]}
    plan["steps"].insert(0, producer)
    assert policy.ready_input_review_errors(plan, inventory, project) == []


@pytest.mark.parametrize("producer", ["later", "same_step", "skipped", "failed", "no_tool"])
def test_unusable_producer_does_not_hide_missing_ready_inputs(local_plan, producer):
    ki, project, _session_obj, plan, inventory = local_plan
    step = {"id": "make", "ki": ki.name, "kind": "run", "status": "planned",
            "tool": str(ki.root / "tools/run.py"), "inputs": [], "outputs": ["forcing"]}
    if producer == "same_step":
        plan["steps"][0]["outputs"] = ["forcing"]
    elif producer == "later":
        plan["steps"].append(step)
    else:
        if producer == "no_tool":
            step["tool"] = None
        else:
            step["status"] = producer
        plan["steps"].insert(0, step)
    assert policy.ready_input_review_errors(plan, inventory, project)


def test_unused_ready_and_unconsumed_outputs_do_not_block_review(local_plan):
    _ki_obj, project, _session_obj, plan, inventory = local_plan
    plan["steps"][0].update(inputs=[], outputs=["forcing"])
    assert policy.ready_input_review_errors(plan, inventory, project) == []


@pytest.mark.parametrize("raw", ["", "*.dat", "${UNKNOWN}/data", ".geoforge/private.dat"])
def test_ready_paths_use_existing_receipt_path_rules(local_plan, raw):
    _ki_obj, project, _session_obj, plan, inventory = local_plan
    inventory["items"][0]["local_paths"] = [raw]
    assert policy.ready_input_review_errors(plan, inventory, project)


def test_review_context_is_required_for_a_consumed_ready_claim(local_plan):
    _ki_obj, _project, _session_obj, plan, inventory = local_plan
    assert "project context is required" in policy.ready_input_review_errors(plan, inventory, None)[0]


def test_old_execution_validation_and_receipt_semantics_stay_unchanged(local_plan):
    _ki_obj, project, _session_obj, plan, inventory = local_plan
    assert validate(local_plan) == []
    assert validate(local_plan, for_execution=True) == []
    assert validate(local_plan, for_execution=True, for_review=True)
    with pytest.raises(ValueError, match="Approved input 'forcing' is missing"):
        receipts.capture_inputs(project, plan["steps"][0], inventory, [], project)


@pytest.mark.parametrize("legacy_missing", [False, True])
def test_approval_rechecks_ready_input_paths(review_project, monkeypatch, legacy_missing):
    env = review_project
    source = env.project / "input.dat"
    if not legacy_missing:
        source.write_bytes(b"actual input")
    def revise(plan, inventory):
        plan["steps"][0]["inputs"] = ["physical"]
        inventory["items"].append({"id": "physical", "status": "ready", "local_paths": ["input.dat"],
                                   "required_by": ["M"], "agent_resolvable": False, "needs_user": False})
    if legacy_missing:
        with monkeypatch.context() as old:
            old.setattr(flowgate.load().plan, "ready_input_review_errors", lambda *_: [])
            card = _draft(env, revise=revise)
    else:
        card = _draft(env, revise=revise)
        source.unlink()
    result = _click(env, card)
    assert "ready input 'physical'" in result.replan_reason
    assert not (env.project / "runs/approval.json").exists()
