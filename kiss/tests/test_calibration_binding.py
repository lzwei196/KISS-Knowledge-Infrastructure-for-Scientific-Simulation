"""Concrete project calibration authorization and bundled result-writer readiness."""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from kiss_cli import api, calibration, paths
from kiss_cli.catalog import KI
from kiss_cli.flowgate import FlowDenied


@pytest.fixture
def adapter(tmp_path):
    project = tmp_path / "project"
    root = project / "calibration/kis/Demo"
    (root / "tools").mkdir(parents=True)
    contract = {
        "identity": {"case_id": "REFERENCE:fixture"},
        "parameters": [{"name": "p", "range": [0.8, 1.5], "default": 1.3}],
        "runner": {"kind": "subprocess", "command": ["python", "{ki_path}/tools/calib_run.py"]},
        "strategy": {"default_algorithm": "dds", "max_evaluations": 60},
    }
    (root / "calibration.yaml").write_text(yaml.safe_dump(contract), encoding="utf-8")
    (root / "tools/calib_run.py").write_text("# approved model adapter\n", encoding="utf-8")
    return project, root, contract


def test_resolve_exact_bytes_and_defaults_before_review(adapter):
    project, root, _ = adapter
    binding, snapshot = calibration.prepare_invocation(project, "Demo", {"obs_shape_by_var": {"Q": "point_time_series"}})
    assert binding["budget"] == 60
    assert binding["algorithm"] == "dds" and binding["seed"] == 0
    assert binding["expected_case_id"] == "REFERENCE:fixture"
    assert binding["contract_path"] == str((root / "calibration.yaml").resolve())
    assert binding["contract_sha256"] == hashlib.sha256(snapshot.contract_bytes).hexdigest()
    assert binding["runner_sha256"] == hashlib.sha256(snapshot.runner_bytes).hexdigest()


@pytest.mark.parametrize("change", [
    {"budget": True}, {"budget": 2.5}, {"budget": 0}, {"budget": 10001},
    {"seed": False}, {"seed": "1"}, {"seed": -1}, {"seed": 2**32}, {"algorithm": "not-an-optimizer"},
    {"obs_shape_by_var": {"Q": None}}, {"obs_shape_by_var": {}}, {"determining_metric": False},
])
def test_invalid_invocation_never_gets_review_binding(adapter, change):
    project, _, _ = adapter
    with pytest.raises(ValueError):
        calibration.prepare_invocation(project, "Demo", {"obs_shape_by_var": {"Q": "point"}, **change})


@pytest.mark.parametrize("runner", [
    {"kind": "subprocess", "command": ["python", "original-ki/tools/calib_run.py"]},
    {"kind": "subprocess", "command": ["python", "-c", "other_code", "{ki_path}/tools/calib_run.py"]},
    {"kind": "subprocess", "command": ["unrelated.exe", "{ki_path}/tools/calib_run.py"]},
    {"kind": "python", "callable": "unreviewed:run"}, [],
])
def test_contract_cannot_bypass_reviewed_runner(adapter, runner):
    project, root, contract = adapter
    contract["runner"] = runner
    (root / "calibration.yaml").write_text(yaml.safe_dump(contract), encoding="utf-8")
    with pytest.raises(ValueError, match="requires a subprocess runner"):
        calibration.prepare_invocation(project, "Demo", {"obs_shape_by_var": {"Q": "point"}})


def test_materialized_runtime_uses_reviewed_bytes_not_later_edits(adapter, tmp_path):
    project, root, _ = adapter
    _, snapshot = calibration.prepare_invocation(project, "Demo", {"obs_shape_by_var": {"Q": "point"}})
    source = tmp_path / "ki"
    source.mkdir()
    (source / "dag.yaml").write_text("outputs: []\n")
    (root / "tools/calib_run.py").write_text("# changed after check\n")
    (root / "calibration.yaml").write_text("parameters: []\n")
    runtime = calibration._runtime_ki(project, "Demo", source, snapshot)
    assert (runtime / "tools/calib_run.py").read_bytes() == snapshot.runner_bytes
    assert (runtime / "calibration.yaml").read_bytes() == snapshot.contract_bytes
    assert (root / "tools/calib_run.py").read_text() == "# changed after check\n"


def test_new_run_keeps_previous_runtime_intact_for_receipts(adapter, tmp_path):
    project, root, _ = adapter
    source = tmp_path / "ki"
    source.mkdir()
    (source / "dag.yaml").write_text("outputs: []\n")
    first = calibration._runtime_ki(project, "Demo", source, run_id="first")
    before = {p.relative_to(first): p.read_bytes() for p in first.rglob("*") if p.is_file()}
    (root / "tools/calib_run.py").write_text("# revised runner\n")
    second = calibration._runtime_ki(project, "Demo", source, run_id="second")
    assert second != first
    assert {p.relative_to(first): p.read_bytes() for p in first.rglob("*") if p.is_file()} == before
    assert (second / "tools/calib_run.py").read_text() == "# revised runner\n"
    with pytest.raises(FileExistsError):
        calibration._runtime_ki(project, "Demo", source, run_id="first")


def test_prepare_adapter_writes_only_two_files_and_does_not_execute(tmp_path):
    contract = {"targets": [{"var": "Q"}], "parameters": [{"name": "p", "range": [.1, 1], "default": .5}],
                "runner": {"kind": "subprocess", "command": ["python", "{ki_path}/tools/calib_run.py"]}}
    marker = tmp_path / "must-not-execute"
    source = f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
    result = calibration.write_adapter(tmp_path, "Demo", contract, source)
    assert result["executed"] is False
    assert not marker.exists()
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()) == [
        "calibration/kis/Demo/calibration.yaml", "calibration/kis/Demo/tools/calib_run.py"]


def test_invalid_adapter_source_preserves_existing_files(adapter):
    project, root, contract = adapter
    contract["targets"] = [{"var": "Q"}]
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises(SyntaxError):
        calibration.write_adapter(project, "Demo", contract, "def invalid syntax\n")
    assert {p: p.read_bytes() for p in before} == before


def test_linked_adapter_cannot_overwrite_another_selected_ki(tmp_path):
    project = tmp_path / "project"
    target = project / "calibration/kis/Other"
    target.mkdir(parents=True)
    link = target.parent / "Demo"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="path escapes"):
        calibration.write_adapter(project, "Demo", {}, "pass\n")
    assert not list(target.iterdir())


@pytest.mark.parametrize("state", ["EXECUTING", "WAITING_FOR_USER", "COMPLETED"])
def test_adapter_authoring_unavailable_outside_planning(tmp_path, state):
    flow = SimpleNamespace(check_tool=lambda name: None, state=SimpleNamespace(value=state))
    with pytest.raises(api.ToolError, match="only during project planning"):
        api.execute_tool("write_calibration_adapter", {"ki": "Demo", "contract": {}, "runner_source": "pass"},
                         KI("Demo", tmp_path), paths.KissConfig.default(tmp_path), project_mode=True, flow=flow)


@pytest.mark.parametrize("arguments", [
    {"ki": "Foreign", "contract": {}, "runner_source": "pass"},
    {"ki": "Demo", "contract": {}, "runner_source": "pass", "path": "../escape.py"},
])
def test_adapter_api_rejects_foreign_ki_or_path_argument(tmp_path, arguments):
    def selected(name, _):
        raise FlowDenied("KI not selected")
    flow = SimpleNamespace(check_tool=lambda name: None, state=SimpleNamespace(value="PLANNING"), ki_root_for=selected)
    with pytest.raises(api.ToolError):
        api.execute_tool("write_calibration_adapter", arguments, KI("Demo", tmp_path),
                         paths.KissConfig.default(tmp_path), project_mode=True, flow=flow)
    assert not (tmp_path / "calibration").exists()


def test_invocation_drift_rejected_before_runtime_or_worker(adapter, tmp_path, monkeypatch):
    project, _, _ = adapter
    binding, snapshot = calibration.prepare_invocation(project, "Demo", {"obs_shape_by_var": {"Q": "point"}})
    monkeypatch.setattr(calibration, "framework_status", lambda: {"ready": True})
    build = Mock(side_effect=AssertionError("must not materialize or launch"))
    monkeypatch.setattr(calibration, "_runtime_ki", build)
    with pytest.raises(ValueError, match="differs from the approved binding"):
        calibration.run_project(project=project, ki_name="Demo", ki_path=tmp_path,
                                obs_shape_by_var={"Q": "point"}, budget=61, seed=0, algorithm="dds",
                                expected_case_id="REFERENCE:fixture", adapter_snapshot=snapshot,
                                approved_binding=binding)
    build.assert_not_called()


def test_missing_ram_discovery_marks_backend_unavailable(monkeypatch):
    real_import = calibration.importlib.import_module
    def import_module(name):
        if name == "spotpy.database":
            return SimpleNamespace(__dir__=lambda: ["custom", "noData"])
        return real_import(name)
    monkeypatch.setattr(calibration.importlib, "import_module", import_module)
    status = calibration.backend_module_status()
    assert status["spotpy.database.ram"]["available"] is False
    assert "RAM result writer" in status["spotpy.database.ram"]["error"]
    assert calibration.framework_status()["ready"] is False


def test_missing_backend_message_names_ram_not_empty_dependency_list(tmp_path, monkeypatch):
    monkeypatch.setattr(calibration, "framework_status", lambda: {
        "ready": False, "available": True, "dependencies": {},
        "backend_modules": {"spotpy.database.ram": {"available": False}}})
    with pytest.raises(RuntimeError, match="spotpy.database.ram"):
        calibration.run_project(project=tmp_path, ki_name="Demo", ki_path=tmp_path,
                                obs_shape_by_var={"Q": "point"})


@pytest.fixture
def completed_result():
    return {"approved_binding": {"budget": 80}, "report": {
        "status": "completed", "best_loss": [0.01], "best_params": {"p": 1.01},
        "n_evaluations": 91, "train_metrics": {"Q": {"nse": .99, "r": .95}},
        "promotable": True, "holdout_validated": True,
        "holdout": {"passed": True, "inconclusive": False, "per_objective": [
            {"ok": True, "calibration_loss": .01, "holdout_loss": .02}]}}}


def test_typed_receipt_requires_actual_metrics_and_holdout(completed_result):
    assert calibration.validate_receipt_result(completed_result, {"budget": 80})["status"] == "passed"
    # Batch-based algorithms can exceed the requested optimizer budget; actual
    # count is disclosed, not confused with a strict native-model launch cap.
    assert "actual evaluations=91" in calibration.validate_receipt_result(completed_result, {"budget": 80})["checks"][4]["detail"]


@pytest.mark.parametrize("change", [
    {"status": "engine_error"}, {"best_loss": [float("nan")]},
    {"best_params": {"p": "<apply failed>"}}, {"n_evaluations": 0},
    {"train_metrics": {"__kdt__": {"evaluation_id": 42}}},
])
def test_invalid_result_or_metadata_numbers_cannot_pass_receipt(completed_result, change):
    completed_result["report"].update(change)
    assert calibration.validate_receipt_result(completed_result, {"budget": 80})["status"] == "failed"


def test_completed_search_without_holdout_is_only_warning(completed_result):
    completed_result["report"].update(holdout=None, promotable=False, holdout_validated=None)
    result = calibration.validate_receipt_result(completed_result, {"budget": 80})
    assert result["status"] == "warning"
    assert result["checks"][-1]["ok"] is False


def test_receipt_binding_mismatch_fails(completed_result):
    assert calibration.validate_receipt_result(completed_result, {"budget": 81})["status"] == "failed"


def test_api_calibration_has_plan_step_argument(tmp_path):
    schema = next(t for t in api.tool_schemas(KI("Demo", tmp_path), project_mode=True) if t["name"] == "run_calibration")
    assert "plan_step_id" in schema["input_schema"]["properties"]


@pytest.mark.skipif(os.name != "nt", reason="Windows console launch policy")
def test_worker_hides_only_framework_evaluation_children_and_restores_on_error(monkeypatch):
    real_run = Mock(return_value=SimpleNamespace(returncode=0))
    original = SimpleNamespace(run=real_run, CREATE_NO_WINDOW=0x08000000, TimeoutExpired=TimeoutError)
    runner = SimpleNamespace(subprocess=original)
    monkeypatch.setattr(calibration.importlib, "import_module", lambda name: runner)
    with pytest.raises(RuntimeError, match="fixture engine failure"):
        with calibration._quiet_evaluation_processes():
            runner.subprocess.run(["model.exe"], creationflags=0x400, capture_output=True)
            assert runner.subprocess.TimeoutExpired is TimeoutError
            assert runner.subprocess is not original
            assert original.run is real_run
            raise RuntimeError("fixture engine failure")
    assert runner.subprocess is original
    assert real_run.call_args.kwargs == {"creationflags": 0x08000400, "capture_output": True}


@pytest.mark.parametrize("deny", [False, True])
def test_api_checks_concrete_binding_before_launch_and_receipts_same_approval(adapter, tmp_path, monkeypatch, deny):
    project, root, _ = adapter
    ki_root = tmp_path / "ki"
    ki_root.mkdir()
    cfg = paths.KissConfig.default(tmp_path / "setup")
    monkeypatch.setattr(calibration, "ensure_project", lambda *a, **k: {})
    run = Mock(return_value={"report": {"status": "completed", "promotable": False}, "run_id": "one"})
    monkeypatch.setattr(calibration, "run_project", run)
    flow = SimpleNamespace(check_tool=lambda name: None, approval_id="current-signed-id", inventory={"items": []},
                           record_tool_run=Mock(return_value={"run_id": "receipt"}))
    def checked(step_id, ki_name, runner_path, binding):
        assert step_id == "fit" and ki_name == "Demo"
        assert runner_path == (root / "tools/calib_run.py").resolve()
        assert binding["budget"] == 60
        if deny:
            raise FlowDenied("wrong approved calibration")
        return {"id": "fit", "inputs": []}
    flow.check_calibration_step = checked
    call = lambda: api.execute_tool("run_calibration", {"obs_shape_by_var": {"Q": "point"}, "plan_step_id": "fit"},
                                    KI("Demo", ki_root), cfg, project_mode=True,
                                    setup_context={"project_root": project}, flow=flow)
    if deny:
        with pytest.raises(api.ToolError, match="wrong approved calibration"):
            call()
        run.assert_not_called()
        flow.record_tool_run.assert_not_called()
    else:
        assert json.loads(call())["receipt"]["run_id"] == "receipt"
        kwargs = run.call_args.kwargs
        assert kwargs["budget"] == 60 and kwargs["algorithm"] == "dds"
        assert kwargs["approved_binding"]["runner_sha256"] == hashlib.sha256(kwargs["adapter_snapshot"].runner_bytes).hexdigest()
        receipt = flow.record_tool_run.call_args.kwargs
        assert receipt["expected_approval_sha256"] == "current-signed-id"
        assert str(root / "calibration.yaml") in receipt["input_arguments"]
