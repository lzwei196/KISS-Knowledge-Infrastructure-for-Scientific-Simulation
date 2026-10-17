"""New reviews bind ordinary invocations without changing legacy receipt scope."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import api, flowrun, plan_review
from ki_tools_common.flow import plan as policy
from .test_flowgate import _cfg, _ki, _plan, _session


@pytest.fixture(autouse=True)
def keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))


def case(tmp_path):
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [
        ("task_received", None), ("kis_resolved", {"selected_kis": [ki.name]})])
    plan, inventory = _plan(ki)
    plan["steps"][0].update(inputs=[], outputs=[])
    inventory["items"] = []
    plan["scientific_choices"] = []
    return ki, project, fs, plan, inventory


@pytest.mark.parametrize("kind", ["check", "prepare", "model_run"])
@pytest.mark.parametrize("present,missing", [({}, "command, cwd"), ({"command": []}, "cwd"),
                                           ({"cwd": "."}, "command")])
def test_new_ordinary_review_requires_both_fields_without_guessing_from_notes(tmp_path, kind, present, missing):
    ki, project, _fs, plan, inventory = case(tmp_path)
    step = plan["steps"][0]
    step.update(kind=kind, note="Validate all inputs and run five checks", **present)
    before = copy.deepcopy((plan, inventory))
    errors = policy.validate(plan, inventory, [ki.name], {ki.name: ki.root},
                             project=project, for_review=True)
    assert len(errors) == 1 and f"requires explicit {missing} before review" in errors[0]
    assert "[]" in errors[0] and "'.'" in errors[0]
    assert policy.validate(plan, inventory, [ki.name], {ki.name: ki.root},
                           project=project, for_execution=True) == []
    assert (plan, inventory) == before


@pytest.mark.parametrize("arguments", [[], ["--input", "inputs/case.csv"]])
def test_explicit_literal_invocation_is_reviewable_and_binds_execution(tmp_path, arguments):
    ki, project, fs, plan, inventory = case(tmp_path)
    step = plan["steps"][0]
    step.update(command=arguments, cwd=".")
    assert fs.write_plan(plan, inventory) == []
    assert policy.step_invocation(step, project) == (arguments, project.resolve())
    policy.require_step_invocation(step, project, arguments, project)
    with pytest.raises(ValueError, match="arguments differ"):
        policy.require_step_invocation(step, project, [*arguments, "--unreviewed"], project)
    with pytest.raises(ValueError, match="working directory differs"):
        policy.require_step_invocation(step, project, arguments, project / "another")


@pytest.mark.parametrize("fields,message", [
    ({"command": None, "cwd": "."}, "argument array"),
    ({"command": "--input x", "cwd": "."}, "argument array"),
    ({"command": ["${UNREVIEWED}"], "cwd": "."}, "argument array"),
    ({"command": [], "cwd": None}, "literal project directory"),
    ({"command": [], "cwd": "../outside"}, "inside the project"),
])
def test_explicit_fields_still_use_existing_type_and_path_checks(tmp_path, fields, message):
    ki, project, _fs, plan, inventory = case(tmp_path)
    plan["steps"][0].update(fields)
    errors = policy.validate(plan, inventory, [ki.name], {ki.name: ki.root},
                             project=project, for_review=True)
    assert len(errors) == 1 and message in errors[0]


def test_api_submission_rejects_unbound_invocation_without_writing_review(tmp_path):
    ki, project, fs, plan, inventory = case(tmp_path)
    result = api.execute_tool("write_plan", {"plan": plan, "data_inventory": inventory},
                              ki, _cfg(project), project_mode=True, flow=fs)
    assert result.startswith("PLAN NOT WRITTEN") and "requires explicit command, cwd" in result
    assert not (project / "runs/plan.json").exists()
    assert not (project / "runs/approval.json").exists()


def test_cli_written_draft_is_rejected_at_host_turn_completion(tmp_path):
    _ki_obj, project, fs, plan, inventory = case(tmp_path)
    # CLI providers write both files; the host still reviews their structured
    # contents at turn completion before any approval card is issued.
    fs.flow.plan.write_artifacts(project, plan, inventory)
    turn = flowrun.Turn(fs, False, "", False, SimpleNamespace(provider="claude"), "fixture",
                        provider_succeeded=True)
    result = flowrun.after(project, turn, "Draft saved")
    assert result.request is None
    assert "requires explicit command, cwd" in (project / "runs/plan-validation.txt").read_text("utf-8")
    assert not (project / "runs/approval.json").exists()
    assert not (project / "runs/plan-review.json").exists()


def test_review_card_marks_existing_unsigned_tool_only_draft_not_ready(tmp_path):
    _ki_obj, project, fs, plan, inventory = case(tmp_path)
    fs.flow.plan.write_artifacts(project, plan, inventory)
    fs.move("plan_written", {"plan_valid": True})
    card = plan_review.issue(project, fs, plan, inventory, "fixture")
    assert any("requires explicit command, cwd" in e for e in card["plan_review"]["not_ready"])
    assert not (project / "runs/approval.json").exists()


@pytest.mark.parametrize("kind,step_id", [("download", "M:download"), ("check", "M:preflight")])
def test_host_owned_steps_keep_their_existing_contract(tmp_path, kind, step_id):
    ki, project, _fs, plan, inventory = case(tmp_path)
    plan["steps"][0].update(kind=kind, id=step_id, tool=None)
    assert policy.validate(plan, inventory, [ki.name], {ki.name: ki.root},
                           project=project, for_review=True) == []


def test_legacy_approved_execution_and_signed_receipt_still_work(tmp_path):
    ki, project, fs, plan, inventory = case(tmp_path)
    step = plan["steps"][0]
    assert policy.step_invocation(step, project) == (None, None)
    # Represents already persisted, approved tool-only scope. It deliberately
    # bypasses NEW submission, but retains the real approval and receipt signer.
    fs.flow.plan.write_artifacts(project, plan, inventory)
    fs.flow.approval.approve(project, by="auto")
    fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True})
    fs.move("approved", {"approval": "OK"})
    fs.move("execution_started", {"setup_verified": True})
    result = api.execute_tool("run_ki_tool", {
        "tool_path": "tools/run.py", "arguments": ["outputs/legacy.csv"], "plan_step_id": step["id"]},
        ki, _cfg(project), project_mode=True, flow=fs)
    assert result.startswith("exit_code=0")
    summary = json.loads(next(line.split("[RECEIPT] ", 1)[1] for line in result.splitlines() if "[RECEIPT] " in line))
    receipt_path = Path(summary["receipt"])
    signed_before = receipt_path.read_bytes()
    receipt = json.loads(signed_before)
    assert fs.flow.receipts.verify(project, receipt)
    assert policy.invocation_receipt_errors(step, project, receipt) == []
    assert fs.evidence()["receipts_verified"] is True
    assert receipt_path.read_bytes() == signed_before
