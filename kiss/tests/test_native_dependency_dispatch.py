"""Direct dispatch must use the executable covered by dependency evidence.

Only the expensive Linux capability transport is replaced here. These tests
exercise actual host project/config/dispatch routing without executing a model;
the verifier's real Ubuntu probes are covered separately.
"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import json
import sys

import pytest

from kiss_cli import execution, flowgate, ki_guard, native_dependency_gate as gate
from kiss_cli import paths, project_paths, project_verification as pv, software_verification


@pytest.fixture
def bound(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    project = tmp_path / "project"
    root = project / "models" / "Demo" / "ki"
    (root / "tools").mkdir(parents=True)
    (root / "SKILL.md").write_text("# Test KI\n")
    engine = project / "binaries" / "Demo" / "engine.exe"
    engine.parent.mkdir(parents=True)
    alternate = engine.with_name("alternate.exe")
    for path in (engine, alternate):
        path.write_bytes(b"synthetic bytes; never execute")
        path.chmod(0o700)
    (root / "knowledge_infrastructure.yaml").write_text(json.dumps({
        "binaries": [{"path": str(engine)}, {"path": str(alternate)}]}))
    wrapper = root / "tools" / "reader.py"
    wrapper.write_text("raise AssertionError('never execute')\n")
    ki_guard.enroll(root)
    cfg = project_paths.model_config(project, "Demo", paths.KissConfig.default(project))
    cfg.python = sys.executable
    (root.parent / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    manifest = {"model": "Demo", "acquire": {"produces": "engine.exe"},
                "system_deps": ["mpif90", "nf-config"]}
    # The actual capability signature/ELF checks are independently tested.
    # Record mocks expose only whether the host selected the right executable.
    report = {"capabilities": {"fixture": "capability"}, "binary": {"fixture": "signed ELF"}}
    monkeypatch.setattr(gate, "_context", lambda: ("binding", tmp_path / "authority", "backend"))
    monkeypatch.setattr(gate, "_read", lambda _: report)
    capability = Mock()
    binary = Mock()
    monkeypatch.setattr(gate.capabilities, "require_current", capability)
    monkeypatch.setattr(gate.capabilities, "require_binary_current", binary)
    monkeypatch.setattr(gate.capabilities, "validate_loader_environment", Mock())
    monkeypatch.setattr(pv, "status", lambda *_args, **_kwargs: {
        "can_run": True, "receipt": {
            "runtime_identity": software_verification.runtime_identity(cfg),
            "effective_manifest": manifest}})
    return SimpleNamespace(project=project, root=root, cfg=cfg, engine=engine,
        alternate=alternate, wrapper=wrapper, manifest=manifest,
        capability=capability, binary=binary)


def test_exact_native_target_still_requires_authenticated_binary_proof(bound):
    gate.require_current(bound.manifest, bound.cfg, native_executable=bound.engine)
    bound.capability.assert_called_once()
    assert bound.binary.call_args.args[3] == str(bound.engine)
    bound.binary.side_effect = ValueError("signature invalid")
    with pytest.raises(ValueError, match="signature invalid"):
        gate.require_current(bound.manifest, bound.cfg, native_executable=bound.engine)


@pytest.mark.parametrize("selection", ["alternate", "relative"])
def test_other_native_target_rejected_before_probing(bound, selection):
    target = bound.alternate if selection == "alternate" else Path("engine.exe")
    with pytest.raises(ValueError, match="differs from the dependency-verified"):
        gate.require_current(bound.manifest, bound.cfg, native_executable=target)
    bound.capability.assert_not_called()
    bound.binary.assert_not_called()


def test_actual_common_dispatch_refuses_an_alternate_declared_native_binary(bound, monkeypatch):
    launch = Mock(side_effect=AssertionError("must not launch"))
    monkeypatch.setattr(execution, "run_process", launch)
    with pytest.raises(flowgate.FlowDenied, match="differs from the dependency-verified"):
        execution.execute_ki_tool(flow=None, cfg=bound.cfg, project=bound.project,
            ki="Demo", ki_root=bound.root, tool=bound.alternate, arguments=[],
            cwd=bound.project, plan_step_id=None, python_tool=False)
    launch.assert_not_called()
    assert not list(bound.project.glob(".geoforge/receipts/model-runs/*.json"))


def test_python_reader_requires_model_proof_without_equating_interpreter_and_engine(bound, monkeypatch):
    class ReachedLaunch(Exception): pass
    launch = Mock(side_effect=ReachedLaunch)
    monkeypatch.setattr(execution, "run_process", launch)
    with pytest.raises(ReachedLaunch):
        execution.execute_ki_tool(flow=None, cfg=bound.cfg, project=bound.project,
            ki="Demo", ki_root=bound.root, tool=bound.wrapper, arguments=[],
            cwd=bound.project, plan_step_id=None, python_tool=True)
    bound.capability.assert_called_once()
    assert bound.binary.call_args.args[3] == str(bound.engine)
    assert launch.call_args.args[0][:2] == [sys.executable, str(bound.wrapper)]


def test_actual_exact_native_dispatch_reaches_launch_only_after_both_proofs(bound, monkeypatch):
    class ReachedLaunch(Exception): pass
    def launch(command, **kwargs):
        bound.capability.assert_called_once()
        bound.binary.assert_called_once()
        assert bound.binary.call_args.args[3] == str(bound.engine)
        assert command == [str(bound.engine)]
        raise ReachedLaunch
    monkeypatch.setattr(execution, "run_process", launch)
    with pytest.raises(ReachedLaunch):
        execution.execute_ki_tool(flow=None, cfg=bound.cfg, project=bound.project,
            ki="Demo", ki_root=bound.root, tool=bound.engine, arguments=[],
            cwd=bound.project, plan_step_id=None, python_tool=False)


def test_models_without_native_profile_are_unchanged(bound):
    gate.require_current({"model": "NoNativeProfile"}, bound.cfg,
                         native_executable=bound.alternate)
    bound.capability.assert_not_called()
    bound.binary.assert_not_called()
