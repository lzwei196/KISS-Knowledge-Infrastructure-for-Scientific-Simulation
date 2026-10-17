"""Every resolved adapter output needs fresh, valid evidence, not a subset."""
import copy
import json
import os
from pathlib import Path

import pytest

from kiss_cli import project_data_tools
from .test_project_data_output_contracts import typed_case, execute, evidence
from .test_plan_review_lifecycle import review_project, _draft, _click


SOURCE = '''from pathlib import Path
out = Path('outputs'); out.mkdir(parents=True, exist_ok=True)
for source, destination in [('weather.txt','weather.csv'), ('agro.txt','agro.yaml')]:
    (out / destination).write_bytes((Path('inputs') / source).read_bytes())
(out / 'soil.json').write_text('{"SMW":0.13,"SMFCF":0.31}')
'''


@pytest.fixture(autouse=True)
def keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "signing-keys"))


def declared_case(tmp_path, *, missing=True, source=SOURCE):
    c = typed_case(tmp_path, source=source)
    step = c[3]["steps"][0]
    step["outputs"] = ["weather", "agro", "soil"] + (["run_config"] if missing else [])
    paths = {"weather": "outputs/weather.csv", "agro": "outputs/agro.yaml",
             "soil": "outputs/soil.json", "run_config": "outputs/run_config.json"}
    c[4]["items"] = [item for item in c[4]["items"] if item["id"] == "forcing"]
    c[4]["items"].extend({"id": ident, "required_by": ["M"], "status": "missing",
        "acceptable_sources": ["generated"], "chosen_source": "generated",
        "local_paths": [paths[ident]], "agent_resolvable": True, "needs_user": False}
        for ident in step["outputs"])
    return c


def test_four_declared_three_produced_records_failed_receipt(tmp_path):
    c = declared_case(tmp_path)
    result, path, receipt = execute(c)
    assert result.startswith("exit_code=0"), result
    assert len(receipt["outputs"]) == 3
    assert receipt["validation"]["status"] == "failed", receipt["validation"]
    assert any(not row["ok"] and "run_config" in row.get("detail", "")
               for row in receipt["validation"]["checks"])
    assert all(row["ok"] for row in receipt["validation"]["typed_outputs"]["outputs"])
    assert c[2].flow.receipts.verify(c[1], receipt)
    assert evidence(c)["steps_passed"] == []
    assert not (c[1] / "outputs/run_config.json").exists()
    assert path.is_file()  # Keep the partial failed attempt as evidence.


def test_three_declared_three_produced_keeps_typed_and_generic_checks(tmp_path):
    c = declared_case(tmp_path, missing=False)
    _, _, receipt = execute(c)
    assert receipt["validation"]["status"] == "passed", receipt["validation"]
    assert len(receipt["outputs"]) == 3
    assert evidence(c)["steps_passed"] == ["M:read"]
    assert receipt["model_executed"] is False
    assert receipt["validation"]["scientific_validation"] == "not_performed"
    assert receipt["validation"]["model_ready"] is False


def test_existing_unchanged_fourth_file_is_not_this_attempts_output(tmp_path):
    c = declared_case(tmp_path)
    out = c[1] / "outputs"
    out.mkdir()
    (out / "run_config.json").write_text('{"old":true}')
    _, _, receipt = execute(c)
    assert receipt["validation"]["status"] == "failed"
    assert any(not row["ok"] and "run_config" in row.get("detail", "")
               for row in receipt["validation"]["checks"])
    assert (out / "run_config.json").read_text() == '{"old":true}'


@pytest.mark.parametrize("text", ["{}", "[]", "{broken", '{"x":NaN}'])
def test_all_outputs_present_does_not_excuse_invalid_generic_json(tmp_path, text):
    c = declared_case(tmp_path, source=SOURCE +
        f"(out / 'run_config.json').write_text({text!r})\n")
    _, _, receipt = execute(c)
    assert len(receipt["outputs"]) == 4
    assert receipt["validation"]["status"] == "failed"
    assert any(row["check"] == "data_artifact_structure:run_config.json" and not row["ok"]
               for row in receipt["validation"]["checks"])


def test_v1_two_declared_one_produced_is_failed(tmp_path):
    from .test_project_data_tools import case, approve, run
    c = case(tmp_path)
    c[3]["steps"][0]["outputs"] = ["inspection", "second"]
    c[4]["items"] = [item for item in c[4]["items"] if item["id"] == "forcing"]
    c[4]["items"].extend({"id": ident, "required_by": ["M"], "status": "missing",
        "acceptable_sources": ["generated"], "chosen_source": "generated",
        "local_paths": [f"outputs/{ident}.json"], "agent_resolvable": True, "needs_user": False}
        for ident in c[3]["steps"][0]["outputs"])
    approve(c)
    result = run(c)
    summary = json.loads(result.splitlines()[1].split("[RECEIPT] ", 1)[1])
    receipt = json.loads(Path(summary["receipt"]).read_text())
    assert receipt["exit_code"] == 0
    assert receipt["validation"]["status"] == "failed"
    assert evidence(c)["steps_passed"] == []


@pytest.mark.parametrize("path", ["../outside.json", "inputs/soil.json", "outputs/../outside.json",
                                 "outputs/sub/../../outside.json", "C:/outside.json"])
def test_resolved_generic_output_cannot_escape_allowed_roots(tmp_path, path):
    c = declared_case(tmp_path, missing=False)
    c[4]["items"][-1]["local_paths"] = [path]
    result = project_data_tools.validate_outputs(c[1], [], 0, step=c[3]["steps"][0], inventory=c[4])
    assert result["status"] == "failed"
    assert any(row["check"] == "declared_data_output_contract" and not row["ok"]
               for row in result["checks"])
    with pytest.raises(ValueError):
        project_data_tools.worker_request(c[1], Path(c[5]["tool"]), c[3]["steps"][0], c[4], [])


@pytest.mark.parametrize("defect", ["missing_path", "duplicate_id", "duplicate_path", "typed_conflict"])
def test_partial_inventory_cannot_hide_ambiguous_or_unresolved_outputs(tmp_path, defect):
    c = declared_case(tmp_path, missing=False)
    if defect == "missing_path":
        c[4]["items"][-1]["local_paths"] = []
    elif defect == "duplicate_id":
        c[4]["items"].append(copy.deepcopy(c[4]["items"][-1]))
    elif defect == "duplicate_path":
        c[4]["items"][-1]["local_paths"] = ["outputs/weather.csv"]
    else:
        c[4]["items"][1]["local_paths"] = ["outputs/other.csv"]
    result = project_data_tools.validate_outputs(c[1], [], 0, step=c[3]["steps"][0], inventory=c[4])
    assert result["status"] == "failed"
    assert any(row["check"] == "declared_data_output_contract" and not row["ok"]
               for row in result["checks"])


def test_symbolic_typed_output_uses_its_exact_format_path(tmp_path):
    c = declared_case(tmp_path, missing=False)
    c[4]["items"] = [item for item in c[4]["items"] if item["id"] not in {"weather", "agro"}]
    _, _, receipt = execute(c)
    assert receipt["validation"]["status"] == "passed", receipt["validation"]


def test_generic_output_hardlink_is_rejected(tmp_path):
    c = declared_case(tmp_path, missing=False)
    (c[1] / "outputs").mkdir()
    os.link(c[1] / "inputs/raw.csv", c[1] / "outputs/soil.json")
    result = project_data_tools.validate_outputs(c[1], [c[1] / "outputs/soil.json"], 0,
        step=c[3]["steps"][0], inventory=c[4])
    assert result["status"] == "failed"
    assert any(row["check"] == "declared_data_output_contract" and not row["ok"]
               for row in result["checks"])


def test_new_review_refuses_symbolic_generic_outputs_but_signed_legacy_still_runs(tmp_path):
    c = typed_case(tmp_path)
    c[4]["items"] = [item for item in c[4]["items"] if item["id"] == "forcing"]
    policy = c[2].flow.plan
    errors = policy.validate(c[3], c[4], ["M"], {"M": c[0].root},
                             project=c[1], for_review=True)
    assert any("exact inventory local_paths" in error and "soil" in error for error in errors)
    assert policy.validate(c[3], c[4], ["M"], {"M": c[0].root},
                           project=c[1], for_execution=True) == []
    # Persist a real pre-upgrade signed plan; do not resubmit it for new review.
    fs = c[2]
    policy.write_artifacts(c[1], c[3], c[4])
    fs.flow.approval.approve(c[1], by="auto")
    fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True})
    fs.move("approved", {"approval": "OK"})
    fs.move("execution_started", {"setup_verified": True})
    from .test_project_data_tools import run
    result = run(c)
    summary = json.loads(result.splitlines()[1].split("[RECEIPT] ", 1)[1])
    receipt = json.loads(Path(summary["receipt"]).read_text(encoding="utf-8"))
    assert receipt["validation"]["status"] == "passed"
    assert evidence(c)["steps_passed"] == ["M:read"]


def test_new_review_accepts_explicit_generic_and_symbolic_typed_outputs(tmp_path):
    c = declared_case(tmp_path, missing=False)
    c[4]["items"] = [item for item in c[4]["items"] if item["id"] not in {"weather", "agro"}]
    assert c[2].flow.plan.validate(c[3], c[4], ["M"], {"M": c[0].root},
                                  project=c[1], for_review=True) == []


def test_pending_old_card_cannot_newly_approve_symbolic_generic_output(review_project, monkeypatch):
    env = review_project
    from kiss_cli import flowgate
    policy = flowgate.load().plan

    def symbolic(plan, inventory):
        source = env.project / "inputs/source.txt"
        source.parent.mkdir(exist_ok=True)
        source.write_text("fixture data\n", encoding="utf-8")
        authored = project_data_tools.write(env.project, "M", "inspect",
            "from pathlib import Path\nPath('inputs/source.txt').read_text(encoding='utf-8')\n", "check")
        step = plan["steps"][0]
        step.update(kind="check", tool=authored["tool"], inputs=["source"], outputs=["report"],
                    project_data_tool=authored["project_data_tool"])
        step.pop("command", None)
        step.pop("cwd", None)
        inventory["items"] = [{"id": "source", "required_by": ["M"], "status": "ready",
            "acceptable_sources": ["local"], "chosen_source": "local",
            "local_paths": ["inputs/source.txt"], "agent_resolvable": False, "needs_user": False}]

    with monkeypatch.context() as old_host:
        old_host.setattr(policy, "project_data_output_paths", lambda *args, **kwargs: {})
        card = _draft(env, revise=symbolic)
    response = _click(env, card)
    assert "exact inventory local_paths" in response.replan_reason
    assert not (env.project / "runs/approval.json").exists()
