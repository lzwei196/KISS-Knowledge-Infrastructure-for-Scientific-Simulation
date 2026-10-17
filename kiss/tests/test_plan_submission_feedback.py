"""Rejected API submissions keep useful feedback across the normal turn boundary."""
from __future__ import annotations

import copy

import pytest

from kiss_cli import api, flowgate, flowrun
from .test_flowgate import _cfg
from .test_plan_validation_diagnostics import planning, submit


def _turn(session, *, succeeded=True):
    session.provider_succeeded = succeeded
    return flowrun.Turn(session, False, "", True, None, "feedback-test",
                        provider_succeeded=succeeded,
                        draft_before=flowrun._plan_versions(session.project))


@pytest.mark.parametrize("succeeded", [True, False])
def test_rejected_pair_feedback_survives_final_or_interrupted_turn(planning, succeeded):
    ki, project, session, plan, inventory = planning
    turn = _turn(session, succeeded=succeeded)
    rejected = copy.deepcopy(plan)
    rejected.pop("schema_version")
    response = submit(ki, project, session, rejected, inventory)
    assert response.startswith("PLAN NOT WRITTEN")
    result = flowrun.after(project, turn, "The plan is written.")
    assert result.request is None and not result.continue_now
    assert result.retry_planning is succeeded
    assert "Latest rejected submission in this turn" in result.message
    assert "schema_version must be '1.0'" in result.message
    assert "missing required key 'schema_version'" in result.message
    if not succeeded:
        assert "interrupted" in result.message
    assert not (project / "runs/approval.json").exists()
    next_turn = flowrun.turn(project, [ki], _cfg(project), "api", "deepseek", None, "Continue the same case")
    assert "schema_version must be '1.0'" in next_turn.extra_prompt
    assert next_turn.session.plan_submission_errors == ()
    # No fresh submission means no fresh validation failure. Do not resurrect
    # the previous run's errors from the diagnostic log or saved prompt.
    next_turn.provider_succeeded = next_turn.session.provider_succeeded = True
    next_result = flowrun.after(project, next_turn, "Still thinking.")
    assert "schema_version must" not in next_result.message
    assert "Latest rejected submission" not in next_result.message


def test_only_latest_rejection_is_kept_and_success_clears_it(planning):
    ki, project, session, plan, inventory = planning
    first = copy.deepcopy(plan)
    first.pop("steps")
    assert submit(ki, project, session, first, inventory).startswith("PLAN NOT WRITTEN")
    assert any("'steps'" in error for error in session.plan_submission_errors)
    second = copy.deepcopy(plan)
    second.pop("schema_version")
    assert submit(ki, project, session, second, inventory).startswith("PLAN NOT WRITTEN")
    assert all("'steps'" not in error for error in session.plan_submission_errors)
    assert any("'schema_version'" in error for error in session.plan_submission_errors)
    assert submit(ki, project, session, plan, inventory).startswith("Plan files written")
    assert session.plan_submission_errors == ()
    reopened = flowgate.FlowSession.open(project, {ki.name: ki.root})
    assert reopened.plan_submission_errors == ()


def test_preserved_feedback_is_bounded_and_redacted(planning, monkeypatch):
    ki, project, session, plan, inventory = planning
    turn = _turn(session, succeeded=False)
    monkeypatch.setattr(session.flow.plan, "validate", lambda *_a, **_k:
                        ["bad token=synthetic-secret " + "x" * 3000] * 40)
    submit(ki, project, session, plan, inventory)
    assert len(session.plan_submission_errors) == 30
    assert all(len(error) <= 2012 for error in session.plan_submission_errors)
    result = flowrun.after(project, turn, "")
    assert "synthetic-secret" not in result.message
    assert "token=[redacted]" in result.message


def test_write_plan_advertises_complete_nested_documents_without_requiring_both_calls(planning):
    ki, _project, session, _plan, _inventory = planning
    schema = next(tool["input_schema"] for tool in api.tool_schemas(
        ki, project_mode=True, flow=session) if tool["name"] == "write_plan")
    assert not schema.get("required")  # one complete document per call remains supported
    for name, contract in (("plan", session.flow.plan.PLAN_SCHEMA),
                           ("data_inventory", session.flow.plan.INVENTORY_SCHEMA)):
        nested = schema["properties"][name]
        assert set(nested["required"]) == set(contract["required"])
        assert nested["properties"]["schema_version"] == {"type": "string", "enum": ["1.0"]}
        assert "never a patch or fragment" in nested["description"]
