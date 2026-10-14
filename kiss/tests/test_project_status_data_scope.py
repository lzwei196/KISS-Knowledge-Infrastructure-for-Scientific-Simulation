"""Signed execution proof cannot announce independent scientific validation."""
import copy

import pytest

from kiss_cli import project_status


DATA_RUN = {"run_id": "reader", "execution_scope": "project_data_tool", "model_executed": False,
            "validation": "passed", "plan_step_id": "read", "step_kind": "prepare"}
MODEL_RUN = {"run_id": "model", "validation": "passed", "plan_step_id": "model"}


def progress(*, runs=None, state="COMPLETED", approval="OK", verified=True, validation="passed",
             steps=None, request=None, errors=None, proof_extra=None, preflights=None):
    proof={"runs": copy.deepcopy([DATA_RUN] if runs is None else runs),
           "receipts_verified": verified, "validation": validation, **(proof_extra or {})}
    original=copy.deepcopy(proof)
    result=project_status._progress(
        {"status":"complete", "science_complete":True, "execution_complete":True,
         "scientific_validation":"passed", "data_preparation_complete":True,
         "completion_scope":"agent-claimed", "summary":"Everything finished"},
        state=state, stage="results", selected=["M"], plan={"goal":"Inspect observed data", "steps":steps or []},
        request=request, proof=proof, approval=approval, acquisition={}, activity={"state":"idle"},
        errors=errors or [], observed_at=1, now=2,
        acquisition_progress={"counts":{"automatic_pending":0,"manual_waiting":0}},
        data_acquired=False, preflights=preflights)
    assert proof==original  # presentation cannot rewrite evidence or Flow
    return result


def test_completed_data_only_plan_has_explicit_scope_and_no_science_completion():
    result=progress()
    assert result["flow_state"] == "COMPLETED" and result["status"] == "complete"
    assert result["completion_scope"] == "data_preparation"
    assert result["data_preparation_complete"] is True and result["science_complete"] is False
    assert result["execution_complete"] is True
    assert result["scientific_validation"] == "not_established"
    assert result["summary"] == (
        "Data preparation completed with current approved execution evidence. "
        "Independent scientific validation is not established.")


def test_step_kinds_cannot_classify_ordinary_ki_execution_as_data_or_science():
    runs = [{"run_id": name, "plan_step_id": name, "validation": "passed"}
            for name in ("weather", "site", "inspect")]
    steps = [{"id": "weather", "kind": "prepare"}, {"id": "site", "kind": "prepare"},
             {"id": "inspect", "kind": "check"}]
    result = progress(runs=runs, steps=steps)
    assert not result["data_preparation_complete"] and not result["science_complete"]
    assert result["completion_scope"] == "approved_execution"
    result = progress(runs=runs + [MODEL_RUN], steps=steps + [{"id": "model", "kind": "run"}])
    assert result["execution_complete"] and not result["science_complete"]
    assert not result["data_preparation_complete"]


@pytest.mark.parametrize("runs", [[MODEL_RUN], [DATA_RUN,MODEL_RUN]])
def test_ordinary_and_mixed_completed_plans_establish_only_approved_execution(runs):
    result=progress(runs=runs)
    assert result["science_complete"] is False and result["status"] == "complete"
    assert result["execution_complete"] is True
    assert result["completion_scope"] == "approved_execution"
    assert result["scientific_validation"] == "not_established"
    assert result["data_preparation_complete"] is False
    assert result["summary"] == ("Approved execution completed with current evidence. "
                                 "Independent scientific validation is not established.")


@pytest.mark.parametrize("scope,model_executed", [
    ("project_data_tool", None), ("data_ki", True), ("ki_check_stdout_artifact", False),
    ("native_reference", True), (None, False),
])
def test_only_explicit_host_data_scope_is_data_preparation(scope, model_executed):
    result = progress(runs=[{**MODEL_RUN, "execution_scope": scope, "model_executed": model_executed}])
    assert result["completion_scope"] == "approved_execution"
    assert result["execution_complete"] and not result["science_complete"]
    assert not result["data_preparation_complete"]


@pytest.mark.parametrize("kind", ["check", "prepare", "run", "calibrate"])
def test_native_reference_name_and_approved_role_do_not_upgrade_host_evidence(kind):
    result = progress(runs=[MODEL_RUN], steps=[{
        "id": "model", "kind": kind, "tool": "native/reference.exe",
        "description": "Native reference executed and scientifically validated",
        "execution_role": "native_reference", "scientific_validation": "passed",
    }])
    assert result["completion_scope"] == "approved_execution"
    assert result["scientific_validation"] == "not_established"
    assert not result["science_complete"]


@pytest.mark.parametrize("approval", ["DRIFT","MISSING","FORGED"])
def test_data_completion_requires_current_approval_even_with_old_passing_proof(approval):
    result=progress(approval=approval)
    assert result["flow_state"] == "COMPLETED"
    assert result["status"] == "waiting_for_user"
    assert result["completion_scope"] is None
    assert result["science_complete"] is False and result["data_preparation_complete"] is False
    assert result["execution_complete"] is False


@pytest.mark.parametrize("state", ["EXECUTING","VERIFYING"])
def test_passing_reader_receipt_does_not_advance_flow_or_claim_phase_completion(state):
    result=progress(state=state)
    assert result["flow_state"] == state and result["status"] == "idle"
    assert result["completion_scope"] is None
    assert result["science_complete"] is False and result["data_preparation_complete"] is False
    assert result["execution_complete"] is False


@pytest.mark.parametrize("kwargs", [{"verified":False}, {"validation":"failed"}])
def test_recorded_completed_state_without_current_passing_proof_is_not_completion(kwargs):
    result=progress(**kwargs)
    assert result["status"] == "failed" and result["flow_state"] == "COMPLETED"
    assert result["science_complete"] is False and result["data_preparation_complete"] is False
    assert result["execution_complete"] is False
    assert result["completion_scope"] is None


@pytest.mark.parametrize("kwargs,status", [
    ({"request": {"kind": "decision", "title": "Review changed plan"}}, "waiting_for_user"),
    ({"errors": ["Unreadable evidence"]}, "failed"),
    ({"proof_extra": {"plan_errors": ["Invalid step"]}}, "failed"),
    ({"proof_extra": {"stale_steps": ["read"]}}, "failed"),
    ({"preflights": [{"name": "M", "state": "stale", "can_run": False}]}, "failed"),
])
def test_pending_or_failed_current_evidence_suppresses_all_completion_flags(kwargs, status):
    result = progress(**kwargs)
    assert result["status"] == status
    assert not result["execution_complete"]
    assert not result["science_complete"]
    assert not result["data_preparation_complete"]
    assert result["completion_scope"] is None
    assert result["scientific_validation"] == "not_established"
