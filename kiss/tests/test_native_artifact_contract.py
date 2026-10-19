"""Synthetic signed execution artifacts; no model or native process runs."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

from kiss_cli import flowgate, native_artifacts
from ki_tools_common.flow import declared_outputs as policy


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "authority"))
    project = tmp_path / "project"
    root = project / "models/Demo/ki"
    (root / "tools").mkdir(parents=True)
    (root / "SKILL.md").write_text("# Synthetic KI")
    (root / "dag.yaml").write_text("outputs:\n- var: flow\n  validation_rank: 1\n  unit: m3/s\n")
    tool = root / "tools/run.py"
    tool.write_text("# Never executed\n")
    engine = tmp_path / "install/engine.exe"
    engine.parent.mkdir()
    engine.write_bytes(b"synthetic engine identity; never executed")
    size, digest = engine.stat().st_size, hashlib.sha256(engine.read_bytes()).hexdigest()
    args = ["--exe", str(engine)]
    fs = flowgate.FlowSession.open(project, {"Demo": root}, python=sys.executable)
    step = {"id": "native", "ki": "Demo", "tool": str(tool), "kind": "model_run",
            "inputs": [], "outputs": ["flow"], "status": "planned", "command": args, "cwd": "."}
    inventory = {"schema_version": "1.0", "items": [{"id": "flow", "status": "missing",
                 "local_paths": ["outputs/run/flow.csv"]}]}
    plan = {"schema_version": "1.0", "goal": "synthetic signed receipt", "created_at": "test",
            "selected_kis": ["Demo"], "steps": [step], "unresolved_questions": [], "scientific_choices": []}
    fs.move("task_received"); fs.move("kis_resolved", {"selected_kis": ["Demo"]})
    fs.flow.plan.write_artifacts(project, plan, inventory)
    fs.flow.approval.approve(project, by="user"); fs.reload_artifacts()
    capture = fs.flow.receipts.RuntimeArgumentCapture(str(project.resolve()), str(project.resolve()),
        tuple(args), ((1, "--exe", str(engine), str(engine)),), ((str(engine), size, digest),))
    snapshot = fs.capture_step_inputs(step, args, project, runtime_authorization=capture)
    output = project / "outputs/run"; output.mkdir(parents=True)
    before = flowgate._snapshot(project)
    alias = output / "solver.exe"; alias.symlink_to(engine)
    scientific = output / "flow.csv"; scientific.write_text("time,flow\n0,1\n1,3\n2,2\n")
    return SimpleNamespace(project=project, root=root, tool=tool, engine=engine, size=size, digest=digest,
        args=args, fs=fs, step=step, inventory=inventory, capture=capture, snapshot=snapshot,
        before=before, alias=alias, scientific=scientific)


def classify(c, **overrides):
    params = dict(before=c.before, authorization=c.capture, arguments=c.args,
                  cwd=c.project, input_snapshot=c.snapshot, policy=policy)
    params.update(overrides)
    return native_artifacts.capture(c.project, "Demo", [c.alias, c.scientific], **params)


def test_only_exact_engine_alias_leaves_output_set_and_remains_signed(case):
    c = case
    outputs, snapshot = classify(c)
    assert outputs == [c.scientific]
    assert "runtime_executable_aliases" not in c.snapshot["input_coverage"]
    row = snapshot["input_coverage"]["runtime_executable_aliases"][0]
    assert row["path"] == "outputs/run/solver.exe"
    assert (row["target"], row["bytes"], row["sha256"]) == (str(c.engine), c.size, c.digest)
    c.fs.record_tool_run(ki="Demo", ki_root=c.root, command=[sys.executable, str(c.tool), *c.args],
        cwd=c.project, started_at=time.time()-1, finished_at=time.time(), exit_code=0,
        before=c.before, plan_step_id="native", input_arguments=c.args,
        input_snapshot=c.snapshot, runtime_authorization=c.capture)
    record = json.loads(next((c.project / ".geoforge/receipts/model-runs").glob("*.json")).read_text())
    assert c.fs.flow.receipts.verify(c.project, record)
    assert [item["path"] for item in record["outputs"]] == ["outputs/run/flow.csv"]
    assert record["input_coverage"]["runtime_executable_aliases"] == [row]
    assert policy.receipt_errors(c.project, c.step, c.inventory, record) == []
    evidence = c.fs.evidence()
    assert evidence["receipts_verified"] and "native" in evidence["steps_passed"]
    c.alias.unlink(); c.alias.symlink_to(c.scientific)
    assert policy.receipt_errors(c.project, c.step, c.inventory, record)
    assert "native" not in c.fs.evidence()["steps_passed"]


def test_common_execution_forwards_host_capability_to_signed_receipt(case, monkeypatch):
    """Only the process boundary is synthetic; use the actual common dispatch."""
    from kiss_cli import execution, ki_guard, paths, project_verification, runtime_arguments
    c = case
    c.alias.unlink(); c.scientific.unlink()
    cfg = paths.KissConfig.default(c.project); cfg.python = sys.executable
    (c.project / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    (c.root.parent / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    ki_guard.enroll(c.root)
    c.fs.move("plan_written", {"plan_valid": True})
    c.fs.move("approved", {"approval": "OK"})
    c.fs.move("execution_started", {"setup_verified": True})
    monkeypatch.setattr(project_verification, "require_current", lambda *a, **k: None)
    monkeypatch.setattr(runtime_arguments, "validate", lambda **k: c.capture)
    def synthetic_process(command, **kwargs):
        assert command[-2:] == c.args
        c.alias.symlink_to(c.engine)
        c.scientific.write_text("time,flow\n0,1\n1,3\n2,2\n")
        return SimpleNamespace(returncode=0, status="completed", detail="",
                               stdout="synthetic fixture only", stderr="", process_started=True)
    monkeypatch.setattr(execution, "run_process", synthetic_process)
    result = execution.execute_ki_tool(flow=c.fs, cfg=cfg, project=c.project,
        ki="Demo", ki_root=c.root, tool=c.tool, arguments=c.args, cwd=c.project,
        plan_step_id="native", python_tool=True)
    assert not result.receipt_error
    record = json.loads(next((c.project / ".geoforge/receipts/model-runs").glob("*.json")).read_text())
    assert c.fs.flow.receipts.verify(c.project, record)
    assert record["input_coverage"]["runtime_executable_aliases"][0]["target"] == str(c.engine)
    assert "native" in c.fs.evidence()["steps_passed"]


@pytest.mark.parametrize("kind", ["absent", "json", "legacy_hashless", "mpi", "output_flag"])
def test_no_implicit_or_caller_supplied_alias_authority(case, kind):
    c = case
    authorization, args, snapshot = c.capture, c.args, c.snapshot
    if kind == "absent": authorization = None
    elif kind == "json": authorization = {"expected_files": c.capture.expected_files}
    else:
        option = {"legacy_hashless": "--exe", "mpi": "--mpirun", "output_flag": "--output_exe"}[kind]
        args = [option, str(c.engine)]
        authorization = c.fs.flow.receipts.RuntimeArgumentCapture(str(c.project.resolve()), str(c.project.resolve()),
            tuple(args), ((1, option, str(c.engine), str(c.engine)),),
            () if kind == "legacy_hashless" else c.capture.expected_files)
        snapshot = c.fs.capture_step_inputs(c.step, args, c.project, runtime_authorization=authorization)
    if kind == "json":
        with pytest.raises(ValueError, match="capability"): classify(c, authorization=authorization)
    else:
        outputs, saved = classify(c, authorization=authorization, arguments=args, input_snapshot=snapshot)
        assert c.alias in outputs
        assert "runtime_executable_aliases" not in saved["input_coverage"]


@pytest.mark.parametrize("kind", ["other_target", "existing", "scientific_suffix", "changed_engine", "snapshot_drift"])
def test_alias_exclusions_remain_narrow(case, kind):
    c = case
    if kind == "other_target": c.alias.unlink(); c.alias.symlink_to(c.scientific)
    if kind == "existing": c.before[str(c.alias)] = (c.size, 1)
    if kind == "scientific_suffix":
        c.alias.unlink(); c.alias = c.alias.with_suffix(".csv"); c.alias.symlink_to(c.engine)
    if kind == "changed_engine": c.engine.write_bytes(b"different engine")
    if kind == "snapshot_drift": c.snapshot["input_coverage"]["runtime_arguments"][0]["target"] = str(c.scientific)
    if kind in {"changed_engine", "snapshot_drift"}:
        with pytest.raises(ValueError): classify(c)
    else:
        assert c.alias in classify(c)[0]


@pytest.mark.parametrize("damage", ["missing", "retarget", "not_link", "engine_bytes", "hash", "size", "runtime_binding", "input_hash", "mpi", "traversal", "duplicate", "declared_science"])
def test_signed_alias_currentness_rejects_incomplete_or_changed_authority(case, damage):
    c = case
    _, snapshot = classify(c)
    receipt = {"ki": "Demo", "inputs": snapshot["inputs"], "input_coverage": snapshot["input_coverage"]}
    row = receipt["input_coverage"]["runtime_executable_aliases"][0]
    if damage == "missing": c.alias.unlink()
    if damage == "retarget": c.alias.unlink(); c.alias.symlink_to(c.scientific)
    if damage == "not_link": c.alias.unlink(); c.alias.write_bytes(c.engine.read_bytes())
    if damage == "engine_bytes": c.engine.write_bytes(b"changed")
    if damage == "hash": row["sha256"] = "0" * 64
    if damage == "size": row["bytes"] += 1
    if damage == "runtime_binding": receipt["input_coverage"]["runtime_arguments"] = []
    if damage == "input_hash": receipt["inputs"][0]["sha256"] = "0" * 64
    if damage == "mpi": row["option"] = "--mpirun"
    if damage == "traversal": row["path"] = "outputs/../run/solver.exe"
    if damage == "duplicate": receipt["input_coverage"]["runtime_executable_aliases"].append(copy.deepcopy(row))
    if damage == "declared_science":
        with pytest.raises(ValueError, match="aliased"):
            policy._path(c.project, row["path"])
        return
    assert policy.execution_alias_errors(c.project, receipt)


@pytest.mark.skipif(os.name == "nt", reason="Real POSIX timestamp filenames require POSIX filesystem")
def test_posix_colon_scientific_and_supporting_files_keep_current_hashes(case):
    c = case
    colon = c.scientific.with_name("HYDRO_RST.2011-08-27_00:00_DOMAIN1")
    colon.write_bytes(b"supporting timestamp restart")
    assert policy._path(c.project, colon.relative_to(c.project).as_posix())[0] == colon
    c.fs.record_tool_run(ki="Demo", ki_root=c.root, command=[sys.executable, str(c.tool), *c.args],
        cwd=c.project, started_at=time.time()-1, finished_at=time.time(), exit_code=0,
        before=c.before, plan_step_id="native", input_arguments=c.args,
        input_snapshot=c.snapshot, runtime_authorization=c.capture)
    assert c.fs.evidence()["receipts_verified"]
    colon.write_bytes(b"tampered restart")
    assert not c.fs.evidence()["receipts_verified"]


@pytest.mark.parametrize("raw", ["C:stream", "C:/outside/result.nc", "C:\\outside\\result.nc", "\\\\server\\share\\result.nc"])
def test_windows_drive_syntax_is_never_a_posix_output_grant(tmp_path, raw):
    with pytest.raises(ValueError): policy._path(tmp_path, raw)


@pytest.mark.skipif(os.name != "nt", reason="Windows ADS checks use Windows paths")
@pytest.mark.parametrize("raw", ["outputs/result.nc:stream", "outputs/name.", "outputs/name "])
def test_windows_ads_and_nonordinary_names_still_fail(tmp_path, raw):
    with pytest.raises(ValueError): policy._path(tmp_path, raw)
