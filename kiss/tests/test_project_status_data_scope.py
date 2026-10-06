"""Data-reader completion cannot announce completion of a scientific model run."""
import copy

import pytest

from kiss_cli import project_status


DATA_RUN = {"run_id": "reader", "execution_scope": "project_data_tool", "model_executed": False,
            "validation": "passed", "plan_step_id": "read", "step_kind": "prepare"}
MODEL_RUN = {"run_id": "model", "validation": "passed", "plan_step_id": "model"}


def progress(*, runs=None, state="COMPLETED", approval="OK", verified=True, validation="passed", steps=None):
    proof={"runs": copy.deepcopy([DATA_RUN] if runs is None else runs),
           "receipts_verified": verified, "validation": validation}
    original=copy.deepcopy(proof)
    result=project_status._progress(
        {"status":"complete", "science_complete":True, "data_preparation_complete":True,
         "completion_scope":"agent-claimed", "summary":"Everything finished"},
        state=state, stage="results", selected=["M"], plan={"goal":"Inspect observed data", "steps":steps or []},
        request=None, proof=proof, approval=approval, acquisition={}, activity={"state":"idle"},
        errors=[], observed_at=1, now=2,
        acquisition_progress={"counts":{"automatic_pending":0,"manual_waiting":0}}, data_acquired=False)
    assert proof==original  # presentation cannot rewrite evidence or Flow
    return result


def test_completed_data_only_plan_has_explicit_scope_and_no_science_completion():
    result=progress()
    assert result["flow_state"] == "COMPLETED" and result["status"] == "complete"
    assert result["completion_scope"] == "data_preparation"
    assert result["data_preparation_complete"] is True and result["science_complete"] is False
    assert result["summary"] == (
        "This phase completed data preparation with current approved evidence. "
        "This alone does not establish completion of the full scientific workflow.")


def test_completed_bundled_weather_and_site_steps_are_preparation_only():
    runs = [{"run_id": name, "plan_step_id": name, "validation": "passed"}
            for name in ("weather", "site", "inspect")]
    steps = [{"id": "weather", "kind": "prepare"}, {"id": "site", "kind": "prepare"},
             {"id": "inspect", "kind": "check"}]
    result = progress(runs=runs, steps=steps)
    assert result["data_preparation_complete"] and not result["science_complete"]
    assert result["completion_scope"] == "data_preparation"
    result = progress(runs=runs + [MODEL_RUN], steps=steps + [{"id": "model", "kind": "run"}])
    assert result["science_complete"] and not result["data_preparation_complete"]


@pytest.mark.parametrize("runs", [[MODEL_RUN], [DATA_RUN,MODEL_RUN]])
def test_native_and_mixed_completed_plans_keep_existing_science_semantics(runs):
    result=progress(runs=runs)
    assert result["science_complete"] is True and result["status"] == "complete"
    assert result["data_preparation_complete"] is False
    assert result["summary"] == "Flow completed with current approved execution evidence."


@pytest.mark.parametrize("approval", ["DRIFT","MISSING","FORGED"])
def test_data_completion_requires_current_approval_even_with_old_passing_proof(approval):
    result=progress(approval=approval)
    assert result["flow_state"] == "COMPLETED"
    assert result["status"] == "waiting_for_user"
    assert result["completion_scope"] is None
    assert result["science_complete"] is False and result["data_preparation_complete"] is False


@pytest.mark.parametrize("state", ["EXECUTING","VERIFYING"])
def test_passing_reader_receipt_does_not_advance_flow_or_claim_phase_completion(state):
    result=progress(state=state)
    assert result["flow_state"] == state and result["status"] == "idle"
    assert result["completion_scope"] is None
    assert result["science_complete"] is False and result["data_preparation_complete"] is False


@pytest.mark.parametrize("kwargs", [{"verified":False}, {"validation":"failed"}])
def test_recorded_completed_state_without_current_passing_proof_is_not_completion(kwargs):
    result=progress(**kwargs)
    assert result["status"] == "failed" and result["flow_state"] == "COMPLETED"
    assert result["science_complete"] is False and result["data_preparation_complete"] is False
    assert result["completion_scope"] is None
