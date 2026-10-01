"""The native calibration worker must execute the adapter and settings reviewed by the user."""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import api, calibration, cli, flowgate, plan_review, project_paths


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    project = tmp_path / "project"
    (project / "runs").mkdir(parents=True)
    ki_root = tmp_path / "M"
    (ki_root / "tools").mkdir(parents=True)
    (ki_root / "tools" / "run.py").write_text("# ordinary KI tool\n")
    adapter = project / "calibration" / "kis" / "M"
    (adapter / "tools").mkdir(parents=True)
    (adapter / "tools" / "calib_run.py").write_text("# reviewed adapter\n")
    (adapter / "calibration.yaml").write_text(
        "identity:\n  case_id: reference-case\n"
        "parameters:\n- name: p\n  range: [0.1, 3.0]\n  default: 1.0\n"
        "runner:\n  kind: subprocess\n  command: ['python', '{ki_path}/tools/calib_run.py']\n"
        "strategy:\n  default_algorithm: dds\n  max_evaluations: 7\n", encoding="utf-8")
    fs = flowgate.FlowSession.open(project, {"M": ki_root})
    plan = {"schema_version": "1.0", "goal": "Calibrate the reviewed case", "selected_kis": ["M"],
            "created_at": "test", "unresolved_questions": [], "scientific_choices": [],
            "steps": [{"id": "M:calibrate", "ki": "M", "kind": "calibrate", "status": "planned",
                       "tool": str(adapter / "tools" / "calib_run.py"), "inputs": [],
                       "outputs": ["calibration_result"],
                       "calibration": {"obs_shape_by_var": {"temperature": "point_time_series"}}}]}
    inventory = {"schema_version": "1.0", "items": []}
    return fs, plan, inventory, adapter


def _approve(case):
    fs, plan, inventory, adapter = case
    assert fs.write_plan(plan, inventory) == []
    fs.flow.approval.approve(fs.project, by="user")
    fs.reload_artifacts()
    return fs, plan, inventory, adapter


def test_native_calibration_plan_is_resolved_before_the_review_card(case):
    fs, plan, inv, adapter = case
    assert fs.write_plan(plan, inv) == []
    binding = plan["steps"][0]["calibration"]
    assert binding["algorithm"] == "dds"
    assert binding["budget"] == 7
    assert binding["seed"] == 0
    assert binding["expected_case_id"] == "reference-case"
    assert set(binding) == fs.flow.plan.CALIBRATION_FIELDS
    card = plan_review._card(fs.flow, fs, plan, inv, "exact")
    assert card["plan_review"]["steps"][0]["calibration"] == binding
    assert card["plan_review"]["steps"][0]["calibration_parameters"] == [
        {"name": "p", "range": [0.1, 3.0], "default": 1.0}]
    # This exact non-KI project path is valid only with the complete typed binding.
    assert fs.flow.plan.validate(plan, inv, ["M"], fs.ki_roots,
                                 project=fs.project, for_execution=True) == []
    untyped = copy.deepcopy(plan)
    untyped["steps"][0].pop("calibration")
    assert any("not a runnable" in e for e in fs.flow.plan.validate(
        untyped, inv, ["M"], fs.ki_roots, project=fs.project, for_review=True))


def test_exact_reviewed_calibration_invocation_is_allowed(case):
    fs, plan, _, adapter = _approve(case)
    binding, snapshot = calibration.prepare_invocation(
        fs.project, "M", {"obs_shape_by_var": {"temperature": "point_time_series"}})
    step = fs.check_calibration_step("M:calibrate", "M", snapshot.runner_path, binding)
    assert step["calibration"] == plan["steps"][0]["calibration"]


@pytest.mark.parametrize("field,value", [
    ("algorithm", "sceua"), ("budget", 99), ("seed", 5),
    ("determining_metric", "rmse"), ("obs_shape_by_var", {"temperature": "spatial_map"}),
    ("expected_case_id", "different-case"), ("contract_sha256", "0" * 64),
    ("runner_sha256", "0" * 64),
])
def test_changed_invocation_is_refused_before_execution(case, field, value):
    fs, plan, _, adapter = _approve(case)
    changed = copy.deepcopy(plan["steps"][0]["calibration"])
    changed[field] = value
    with pytest.raises(flowgate.FlowDenied, match="differs from the approved plan"):
        fs.check_calibration_step("M:calibrate", "M", adapter / "tools" / "calib_run.py", changed)


@pytest.mark.parametrize("relative", ["calibration.yaml", "tools/calib_run.py"])
def test_mutated_adapter_or_contract_revokes_approval(case, relative):
    fs, plan, _, adapter = _approve(case)
    path = adapter / relative
    path.write_bytes(path.read_bytes() + b"\n# changed after review\n")
    assert fs.flow.approval.check(fs.project) == "DRIFT"
    with pytest.raises(flowgate.FlowDenied, match="no valid approval"):
        fs.check_calibration_step("M:calibrate", "M", adapter / "tools" / "calib_run.py",
                                  plan["steps"][0]["calibration"])


@pytest.mark.parametrize("field", ["runner_sha256", "contract_sha256", "contract_path", "expected_case_id"])
def test_submission_never_silently_replaces_stale_explicit_binding(case, field):
    fs, plan, inv, _ = case
    plan["steps"][0]["calibration"][field] = "stale"
    errors = fs.write_plan(plan, inv)
    assert any(field in error for error in errors)
    assert not (fs.project / "runs" / "plan.json").exists()


def test_typed_binding_does_not_allow_a_different_project_tool(case):
    fs, plan, inv, adapter = case
    rogue = fs.project / "elsewhere.py"
    rogue.write_text("# not the calibration adapter\n")
    plan["steps"][0]["tool"] = str(rogue)
    assert any("exact project adapter" in e for e in fs.write_plan(plan, inv))


def test_an_ordinary_calibrate_ki_step_cannot_be_used_by_the_native_operation(case):
    fs, plan, inv, _ = case
    step = plan["steps"][0]
    step.pop("calibration")
    step["tool"] = str(fs.ki_roots["M"] / "tools" / "run.py")
    assert fs.write_plan(plan, inv) == []
    fs.flow.approval.approve(fs.project)
    fs.reload_artifacts()
    with pytest.raises(flowgate.FlowDenied, match="typed calibration"):
        fs.check_calibration_step(step["id"], "M", Path(step["tool"]), {})


def test_case_input_exemption_is_limited_to_declared_consumed_inputs(case):
    fs, plan, _, adapter = case
    directory = fs.project / "calibration" / "cases" / "official"
    directory.mkdir(parents=True)
    (directory / "observations.csv").write_text("date,value\n1,4\n")
    other = directory.parent / "not-declared.csv"
    other.write_text("1,2\n")
    result = fs.project / "calibration" / "runs" / "injected.csv"
    result.parent.mkdir()
    result.write_text("1,2\n")
    plan["steps"][0]["inputs"] = ["observations"]
    inventory = {"items": [{"id": "observations", "local_paths": [str(directory)]},
                            {"id": "calibration_result", "local_paths": [str(result)]}]}
    evidence = fs.flow.receipts.evidence(fs.project, plan, {}, inventory=inventory)
    assert "calibration/cases/official/observations.csv" not in evidence["unreceipted_artifacts"]
    assert "calibration/cases/not-declared.csv" in evidence["unreceipted_artifacts"]
    assert "calibration/runs/injected.csv" in evidence["unreceipted_artifacts"]


@pytest.mark.parametrize("holdout, expected", [(True, "passed"), (False, "warning")])
def test_calibration_receipt_hashes_raw_and_runtime_files_without_treating_config_as_science(case, holdout, expected):
    fs, plan, inv, adapter = _approve(case)
    binding = plan["steps"][0]["calibration"]
    before = flowgate._snapshot(fs.project, subs=("inputs", "outputs", "artifacts", "runs/logs", "calibration/runs"))
    run = fs.project / "calibration" / "runs" / "test-run"
    run.mkdir(parents=True)
    raw = run / "raw-model.out"
    raw.write_text("1,1.2\n2,2.6\n3,3.5\n")
    (run / "engine.log").write_text("Optimizer completed")
    (run / "engine-request.json").write_text('{"budget": 7}')
    runtime = fs.project / "calibration" / "runtime" / "M" / "test-run"
    runtime.mkdir(parents=True)
    (runtime / "source-example.txt").write_text("Source material, not scientific output")
    report = {"status": "completed", "n_evaluations": 9, "best_loss": [0.1],
              "best_params": {"p": 1.2}, "train_metrics": {"rmse": 0.2},
              "holdout": {"passed": holdout, "inconclusive": False,
                          "per_objective": [{"ok": holdout, "calibration_loss": 0.1, "holdout_loss": 0.12}]},
              "holdout_validated": holdout, "promotable": holdout}
    result = {"approved_binding": binding, "report": report, "run_id": "test-run",
              "runtime_ki": "calibration/runtime/M/test-run",
              "report_path": "calibration/runs/test-run/report.json"}
    (run / "report.json").write_text(json.dumps(result), encoding="utf-8")
    receipt = fs.record_tool_run(
        ki="M", ki_root=fs.ki_roots["M"], command=["geoforge-calibration", "--adapter", str(adapter / "tools" / "calib_run.py")],
        cwd=fs.project, started_at=time.time(), finished_at=time.time(), exit_code=0,
        before=before, plan_step_id="M:calibrate", calibration_result=result,
        input_arguments=[str(adapter / "tools" / "calib_run.py"), str(adapter / "calibration.yaml")])
    assert receipt["validation"] == expected
    document = json.loads(Path(receipt["receipt"]).read_text(encoding="utf-8"))
    paths = {item["path"] for item in document["outputs"]}
    assert "calibration/runs/test-run/raw-model.out" in paths
    assert "calibration/runs/test-run/engine.log" in paths
    assert "calibration/runs/test-run/engine-request.json" in paths
    assert "calibration/runtime/M/test-run/source-example.txt" in paths
    evidence = fs.flow.receipts.evidence(fs.project, fs.plan, fs.approval_doc, inventory=inv)
    assert evidence["receipts_verified"] is holdout
    assert evidence["validation"] == ("passed" if holdout else "incomplete")
    assert evidence["rejected_receipts"] == []


def _cli_case(case, monkeypatch):
    fs, plan, inv, _ = case
    root = fs.project / "models" / "M" / "ki"
    root.mkdir(parents=True)
    fs.ki_roots = {"M": root}
    cfg = SimpleNamespace(root=fs.project, python="python", roles={})
    monkeypatch.setattr(project_paths, "execution_config", lambda *args: cfg)
    args = SimpleNamespace(project=fs.project, ki_path=root, model="M", plan_step_id="M:calibrate",
                           obs_shapes_json='{"temperature":"point_time_series"}', budget=None,
                           seed=0, algorithm=None, expected_case_id=None, determining_metric=None)
    return fs, args


def test_cli_refuses_unapproved_calibration_before_worker(case, monkeypatch):
    fs, args = _cli_case(case, monkeypatch)
    monkeypatch.setattr(calibration, "run_project", lambda **kw: pytest.fail("unapproved worker launched"))
    with pytest.raises(api.ToolError, match="not allowed while.*NEW"):
        cli.cmd_calibrate(args)
    assert not (fs.project / ".geoforge" / "receipts" / "model-runs").exists()


@pytest.mark.parametrize("change", ["ki", "budget", "case"])
def test_cli_cannot_switch_the_reviewed_workspace_or_invocation(case, monkeypatch, change):
    fs, args = _cli_case(case, monkeypatch)
    _approve(case)
    fs.move("task_received")
    fs.move("kis_resolved", {"selected_kis": ["M"]})
    fs.move("plan_written", {"plan_valid": True})
    fs.move("approved", {"approval": "OK"})
    fs.move("execution_started", {"setup_verified": True})
    monkeypatch.setattr(calibration, "ensure_project", lambda *args: None)
    monkeypatch.setattr(calibration, "run_project", lambda **kw: pytest.fail("changed worker launched"))
    if change == "ki":
        args.ki_path = fs.project.parent / "different-KI"
    elif change == "budget":
        args.budget = 999
    else:
        args.expected_case_id = "another-case"
    with pytest.raises((ValueError, api.ToolError), match="materialized|differs from"):
        cli.cmd_calibrate(args)


def test_cli_routes_approved_native_calibration_through_api_receipt_gate(case, monkeypatch, capsys):
    fs, args = _cli_case(case, monkeypatch)
    _approve(case)
    fs.move("task_received")
    fs.move("kis_resolved", {"selected_kis": ["M"]})
    fs.move("plan_written", {"plan_valid": True})
    fs.move("approved", {"approval": "OK"})
    fs.move("execution_started", {"setup_verified": True})
    monkeypatch.setattr(calibration, "ensure_project", lambda *args: None)
    calls = []
    def worker(**kwargs):
        calls.append(kwargs)
        result = {"approved_binding": kwargs["approved_binding"], "run_id": "test-native",
                  "runtime_ki": "calibration/runtime/M/test-native",
                  "report_path": "calibration/runs/test-native/report.json",
                  "report": {"status": "completed", "n_evaluations": 7, "best_loss": [0.1],
                             "best_params": {"p": 1.2}, "train_metrics": {"rmse": 0.2},
                             "holdout": {"passed": True, "inconclusive": False,
                                         "per_objective": [{"ok": True, "calibration_loss": 0.1, "holdout_loss": 0.12}]},
                             "holdout_validated": True, "promotable": True}}
        path = fs.project / result["report_path"]
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(result), encoding="utf-8")
        (fs.project / result["runtime_ki"]).mkdir(parents=True)
        return result
    monkeypatch.setattr(calibration, "run_project", worker)
    assert cli.cmd_calibrate(args) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["receipt"]["validation"] == "passed"
    assert len(calls) == 1
    assert calls[0]["approved_binding"] == fs.plan["steps"][0]["calibration"]
    assert Path(summary["receipt"]["receipt"]).is_file()


def test_adapter_preparation_has_a_separate_planning_only_capability():
    flow = flowgate.load()
    for state in flow.states.State:
        assert flow.policy.api_tool_allowed(state, "write_calibration_adapter") is (
            state in {flow.states.State.PLANNING, flow.states.State.REPLAN_REQUIRED})
    assert not flow.policy.api_tool_allowed(flow.states.State.PLANNING, "write_project_file")


def test_two_approved_calibration_steps_keep_separate_immutable_receipt_artifacts(case):
    fs, plan, inv, adapter = case
    second = copy.deepcopy(plan["steps"][0])
    second.update(id="M:second", outputs=["second_calibration_result"])
    second["calibration"]["seed"] = 13
    plan["steps"].append(second)
    _approve(case)
    documents = []
    for index, step in enumerate(plan["steps"]):
        before = flowgate._snapshot(fs.project, subs=("inputs", "outputs", "artifacts", "runs/logs", "calibration/runs"))
        run_id = f"run-{index}"
        run = fs.project / "calibration" / "runs" / run_id
        runtime = fs.project / "calibration" / "runtime" / "M" / run_id
        run.mkdir(parents=True)
        runtime.mkdir(parents=True)
        (runtime / "snapshot.txt").write_text(f"Reviewed seed {step['calibration']['seed']}")
        (run / "native.out").write_text("1 2.5\n2 3.5\n")
        report = {"status": "completed", "n_evaluations": 7, "best_loss": [0.1],
                  "best_params": {"p": 1.2}, "train_metrics": {"rmse": 0.2},
                  "holdout": {"passed": True, "inconclusive": False,
                              "per_objective": [{"ok": True, "calibration_loss": 0.1, "holdout_loss": 0.12}]},
                  "holdout_validated": True, "promotable": True}
        result = {"approved_binding": step["calibration"], "report": report, "run_id": run_id,
                  "runtime_ki": f"calibration/runtime/M/{run_id}",
                  "report_path": f"calibration/runs/{run_id}/report.json"}
        (run / "report.json").write_text(json.dumps(result), encoding="utf-8")
        receipt = fs.record_tool_run(
            ki="M", ki_root=fs.ki_roots["M"], command=["geoforge-calibration", "--adapter", str(adapter / "tools" / "calib_run.py")],
            cwd=fs.project, started_at=time.time(), finished_at=time.time(), exit_code=0,
            before=before, plan_step_id=step["id"], calibration_result=result,
            input_arguments=[str(adapter / "tools" / "calib_run.py"), str(adapter / "calibration.yaml")])
        assert receipt["validation"] == "passed"
        documents.append(json.loads(Path(receipt["receipt"]).read_text(encoding="utf-8")))
    for index, document in enumerate(documents):
        runtime_paths = [item["path"] for item in document["outputs"] if item["path"].startswith("calibration/runtime/")]
        assert runtime_paths == [f"calibration/runtime/M/run-{index}/snapshot.txt"]
    evidence = fs.flow.receipts.evidence(fs.project, fs.plan, fs.approval_doc, inventory=inv)
    assert evidence["receipts_verified"] is True
    assert evidence["validation"] == "passed"
    assert evidence["rejected_receipts"] == []
