"""Profile-bound named child arguments through shared API/CLI dispatch.

Native capability transport is replaced by explicit synthetic records here;
its signatures, package checks and real Ubuntu probes have separate tests.
Only the harmless Python wrapper runs; no model, MPI or native fixture runs.
"""
from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kiss_cli import execution, native_dependency_gate as gate, runtime_arguments
from kiss_cli import project_verification as pv
from .test_runtime_arguments import case as runtime_case, verify, invoke, denied


def identity(path):
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


@pytest.fixture
def case(runtime_case, tmp_path, monkeypatch):
    c = runtime_case
    # This profile verifies an ordinary exact product, not a legacy engine alias.
    c.alias.unlink()
    c.alias.write_bytes(c.external.read_bytes())
    c.alias.chmod(0o755)
    verify(c)
    system = tmp_path / "system"
    system.mkdir()
    launcher = system / "orterun"
    launcher.write_bytes(b"official MPI fixture; never executed")
    alias = system / "mpiexec"
    alias.symlink_to(launcher)
    other = system / "other-official-tool"
    other.write_bytes(b"another official tool; not MPI")
    monkeypatch.setattr(gate, "_MPI_LAUNCHER", str(alias))
    monkeypatch.setattr(gate, "_MPI_TARGET", str(launcher))
    manifest = {"model": "CRHM", "install_dir": "crhm", "acquire": {"produces": "build/crhm"},
                "system_deps": ["mpif90", "nf-config"]}
    capability = {"profile": gate.capabilities.PROFILE, "evidence": {"system_files": {
        str(path): {"path": str(path), "package": "openmpi-bin", **identity(path)}
        for path in (launcher, other)}}}
    binary = {"executable": str(c.alias), "evidence": {"executable": str(c.alias), **identity(c.alias)}}
    record = {"capabilities": capability, "binary": binary}
    monkeypatch.setattr(gate, "_context", lambda: ("fixture binding", tmp_path / "authority", "fixture backend"))
    monkeypatch.setattr(gate, "_read", lambda _: record)
    current, current_binary = Mock(), Mock()
    monkeypatch.setattr(gate.capabilities, "require_current", current)
    monkeypatch.setattr(gate.capabilities, "require_binary_current", current_binary)
    monkeypatch.setattr(gate.capabilities, "validate_loader_environment", Mock())
    original_status = pv.status
    def status(*args, **kwargs):
        result = copy.deepcopy(original_status(*args, **kwargs))
        if result.get("can_run"):
            result["receipt"]["effective_manifest"] = manifest
        return result
    monkeypatch.setattr(pv, "status", status)
    return SimpleNamespace(base=c, manifest=manifest, alias=alias, launcher=launcher, other=other,
        record=record, current=current, current_binary=current_binary)


def approve_arguments(c, arguments):
    plan = copy.deepcopy(c.flow.plan)
    plan["steps"][0].update(command=list(arguments), cwd=".")
    c.flow.flow.plan.write_artifacts(c.project, plan, c.flow.inventory)
    c.flow.flow.approval.approve(c.project, by="user")
    c.flow.reload_artifacts()


def arguments(case, form="separate"):
    if form == "equals":
        return ["--exe=" + str(case.base.alias), "--mpirun=" + str(case.alias)]
    return ["--exe", str(case.base.alias), "--mpirun", str(case.alias)]


@pytest.mark.parametrize("adapter", ["api", "cli"])
@pytest.mark.parametrize("form", ["separate", "equals"])
def test_exact_profile_engine_and_launcher_are_captured_with_signed_hashes(case, capsys, adapter, form):
    c, argv = case.base, arguments(case, form)
    approve_arguments(c, argv)
    result = invoke(c, adapter, argv, capsys)
    assert result[0] == 0 if adapter == "cli" else result.startswith("exit_code=0"), result
    assert case.current.called and case.current_binary.called
    assert json.loads((c.project / "launched.json").read_text()) == argv
    doc = json.loads(next((c.project / ".geoforge/receipts/model-runs").glob("*.json")).read_text())
    assert c.flow.flow.receipts.verify(c.project, doc)
    rows = doc["input_coverage"]["runtime_arguments"]
    assert {row["option"] for row in rows} == {"--exe", "--mpirun"}
    assert {(row["path"], row["target"]) for row in rows} == {
        (str(c.alias), str(c.alias)), (str(case.alias), str(case.launcher))}
    inputs = {row["path"]: row for row in doc["inputs"]}
    for path in (c.alias, case.launcher):
        assert inputs[str(path)]["sha256"] == identity(path)["sha256"]


@pytest.mark.parametrize("adapter", ["api", "cli"])
@pytest.mark.parametrize("defect", ["contained_engine", "contained_mpi", "signed_other_tool",
    "positional", "output_flag", "wrong_native_flag", "directory", "missing_value"])
def test_profile_never_widens_paths_or_allows_contained_native_substitutes(case, capsys, adapter, defect):
    c = case.base
    fake = c.project / "fake-native"
    fake.write_bytes(b"a plausible but unverified native file")
    argv = {
        "contained_engine": ["--exe", str(fake)],
        "contained_mpi": ["--mpirun", str(fake)],
        "signed_other_tool": ["--mpiexec", str(case.other)],
        "positional": [str(case.alias)],
        "output_flag": ["--output", str(case.alias)],
        "wrong_native_flag": ["--other_exe", str(case.alias)],
        "directory": ["--mpirun", str(case.alias.parent)],
        "missing_value": ["--mpirun"],
    }[defect]
    approve_arguments(c, argv)
    denied(c, adapter, argv, capsys)


@pytest.mark.parametrize("defect", ["capability_stale", "binary_stale", "alias_swap", "launcher_hash",
    "engine_hash", "missing_hash", "wrong_profile", "wrong_package"])
def test_profile_requires_current_role_target_and_proof_hash(case, capsys, defect):
    c, argv = case.base, arguments(case)
    approve_arguments(c, argv)
    if defect == "capability_stale": case.current.side_effect = ValueError("stale capability signature")
    elif defect == "binary_stale": case.current_binary.side_effect = ValueError("stale binary proof")
    elif defect == "alias_swap":
        case.alias.unlink(); case.alias.symlink_to(case.other)
    elif defect == "launcher_hash": case.launcher.write_bytes(b"changed launcher")
    elif defect == "engine_hash": c.alias.write_bytes(b"changed engine")
    elif defect == "missing_hash": case.record["capabilities"]["evidence"]["system_files"][str(case.launcher)].pop("sha256")
    elif defect == "wrong_profile": case.record["capabilities"]["profile"] = "another-profile"
    else: case.record["capabilities"]["evidence"]["system_files"][str(case.launcher)]["package"] = "not-mpi"
    denied(c, "api", argv, capsys)


def capture(case, argv=None, **kwargs):
    c = case.base
    proof = gate.require_current(case.manifest, c.cfg)
    return runtime_arguments.validate(project=c.project, ki=c.ki.name, ki_root=c.ki.root, cfg=c.cfg,
        arguments=argv or arguments(case), cwd=c.project, allow_runtime=True,
        native_capability=proof, **kwargs)


@pytest.mark.parametrize("option,role", [("--binary", "engine"), ("--executable", "engine"),
    ("--crhm_exe", "engine"), ("--mpiexec", "mpi_launcher")])
def test_existing_named_engine_options_and_mpiexec_use_same_profile_capture(case, option, role):
    path = case.base.alias if role == "engine" else case.alias
    auth = capture(case, [option, str(path)])
    assert len(auth.expected_files) == 1
    assert auth.bindings[0][1] == option


def test_mpi_alias_rejection_names_exact_permitted_path(case):
    # The resolved tool is official, but callers must use the profile's exact
    # probed alias so receipt currentness can detect alternatives retargeting.
    with pytest.raises(ValueError, match="exact verified path") as error:
        capture(case, ["--mpirun", str(case.launcher)])
    assert str(case.alias) in str(error.value)


@pytest.mark.parametrize("defect", ["launcher", "engine", "same_bytes_alias"])
def test_capture_rechecks_signed_hash_and_alias_before_and_after_launch(case, defect):
    c, argv = case.base, arguments(case)
    auth = capture(case, argv)
    assert len(auth.expected_files) == 2
    if defect == "same_bytes_alias":
        twin = case.launcher.with_name("twin")
        twin.write_bytes(case.launcher.read_bytes())
        case.alias.unlink(); case.alias.symlink_to(twin)
    else:
        target = case.launcher if defect == "launcher" else c.alias
        data = target.read_bytes()
        target.write_bytes(b"x" + data[1:])
    with pytest.raises(ValueError, match="runtime argument|binding changed"):
        auth.checked_bindings(c.project, argv, c.project)


def test_successful_wrapper_cannot_earn_pass_when_proved_target_changes_during_run(case, capsys, monkeypatch):
    c, argv = case.base, arguments(case)
    approve_arguments(c, argv)
    real_run = execution.run_process
    def run(*args, **kwargs):
        result = real_run(*args, **kwargs)
        data = case.launcher.read_bytes()
        case.launcher.write_bytes(b"x" + data[1:])
        return result
    monkeypatch.setattr(execution, "run_process", run)
    response = invoke(c, "api", argv, capsys)
    assert response.startswith("exit_code=1"), response
    doc = json.loads(next((c.project / ".geoforge/receipts/model-runs").glob("*.json")).read_text())
    assert c.flow.flow.receipts.verify(c.project, doc)
    assert doc["exit_code"] == 1 and doc["execution_status"] == "failed"


@pytest.mark.parametrize("defect", ["json", "data_tool", "different_config", "missing_capture_hash"])
def test_capability_cannot_be_supplied_by_json_or_borrowed_for_data_tools(case, defect):
    c, argv = case.base, arguments(case)
    proof = gate.require_current(case.manifest, c.cfg)
    if defect == "missing_capture_hash":
        auth = capture(case, argv)
        with pytest.raises(ValueError, match="cover every argument"):
            replace(auth, expected_files=auth.expected_files[:1]).checked_bindings(c.project, argv, c.project)
        return
    cfg = copy.copy(c.cfg)
    if defect == "different_config": cfg.python = "different-python"
    with pytest.raises(ValueError, match="capability|another runtime"):
        runtime_arguments.validate(project=c.project, ki=c.ki.name, ki_root=c.ki.root, cfg=cfg,
            arguments=argv, cwd=c.project, allow_runtime=defect != "data_tool",
            native_capability={} if defect == "json" else proof)


def test_profile_checked_report_is_immutable_after_currentness(case):
    c = case.base
    proof = gate.require_current(case.manifest, c.cfg)
    case.record["binary"]["evidence"]["sha256"] = "0" * 64
    binding = proof.binding(c.cfg, "engine", c.alias)
    assert binding[-1] == identity(c.alias)["sha256"]
