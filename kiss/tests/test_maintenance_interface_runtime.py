"""Runtime-sensitive maintenance boundaries; provider fixtures have their own suite.

The KDT engine and interface probe are explicit doubles here. Source copies,
signatures, inventory checks, saved project configuration and adoption are real.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import flowgate, ki_copy, ki_guard, ki_investigation as inv
from kiss_cli import ki_maintenance as maintenance, ki_maintenance_recipes as recipes
from kiss_cli import ki_maintenance_wofost as routing, ki_verification as gate, paths
from kiss_cli import published_kdt, software_verification
from .test_ki_maintenance import case, metadata
from .test_ki_verification_boundaries import isolated_engine, write_package
from .test_ki_investigation import case as investigation_case, new, reviewer
from .test_investigation_maintenance import maintenance as investigation_maintenance
from .test_rejected_update_maintenance import rejected, make_reviewed


@pytest.fixture
def interface_case(tmp_path, monkeypatch):
    monkeypatch.delenv("GEOFORGE_KDT_ENGINE", raising=False)
    state = SimpleNamespace(current=True, ok=True, calls=[])
    with isolated_engine(tmp_path) as engine:
        base = tmp_path / "active"
        write_package(base, name="WOFOST")
        metadata(base, "WOFOST")
        tool = base / routing.TOOL_PATH
        tool.parent.mkdir(parents=True)
        tool.write_text("# Before bounded interface projection\n", encoding="utf-8")
        ki_guard.enroll(base)
        generated = b"# Exact bounded interface projection\n"
        monkeypatch.setattr(recipes, "expected_changes", lambda *_: {routing.TOOL_PATH: generated})
        source = maintenance.capture_source(base, "WOFOST")
        candidate = tmp_path / "candidate"
        ki_copy.copytree(Path(source["base_root"]), candidate)
        (candidate / routing.TOOL_PATH).write_bytes(generated)

        def validate(before, after, python):
            state.calls.append((before, after, python))
            return {"ok": state.ok, "status": "passed" if state.ok else "failed",
                    "policy": routing.POLICY, "fixture_ids": ["explicit_test_double"],
                    "model_execution": False, "scientific_validation": False,
                    "runtime": {"selected_python": python}, "runtime_identity": "fixture"}

        def require(report):
            if (not state.current or not isinstance(report, dict) or report.get("ok") is not True
                    or report.get("policy") != routing.POLICY
                    or report.get("fixture_ids") != ["explicit_test_double"]):
                raise ValueError("Interface runtime or fixture report changed")
            return report

        monkeypatch.setattr(routing, "validate_behavior", validate)
        monkeypatch.setattr(routing, "require_runtime_current", require)
        yield SimpleNamespace(base=base, candidate=candidate, source=source, state=state,
                              engine=engine, python=str(tmp_path / "selected-runtime/python.exe"))


def verify(case):
    return maintenance.verify_candidate(case.candidate, source=case.source, name="WOFOST",
                                        runtime_python=case.python)


def test_interface_edit_requires_explicit_runtime_before_gate(interface_case):
    case = interface_case
    with pytest.raises(ValueError, match="saved project Python"):
        maintenance.verify_candidate(case.candidate, source=case.source, name="WOFOST")
    assert not case.state.calls and not case.engine.seen


def test_exact_interface_edit_has_separate_signed_evidence_and_current_kdt(interface_case):
    case = interface_case
    report = verify(case)
    assert report["ok"] and len(case.engine.seen) == 1
    assert case.state.calls == [(Path(case.source["base_root"]), case.candidate, case.python)]
    assert report["interface_regression"]["runtime"]["selected_python"] == case.python
    assert report["preflight_regression"]["status"] == "not_required"
    assert report["native_regression"] == {"status": "not_run", "verified": False}
    assert report["scientific_validation"] is False and report["authoring_verification"] is False
    assert maintenance.require_current(case.candidate, report) == report


@pytest.mark.parametrize("failure", ["interface", "kdt"])
def test_interface_or_kdt_failure_cannot_become_acceptance(interface_case, failure):
    case = interface_case
    if failure == "interface":
        case.state.ok = False
    else:
        case.engine.ok = False
    report = verify(case)
    assert not report["ok"] and report["state"] == "MaintenanceRejected"
    assert len(case.engine.seen) == 1
    with pytest.raises(ValueError):
        maintenance.require_current(case.candidate, report)


@pytest.mark.parametrize("report", [None, {}, {"ok": 1}, {"ok": True}])
def test_missing_or_incomplete_interface_result_is_never_signed_as_success(interface_case, monkeypatch, report):
    monkeypatch.setattr(routing, "validate_behavior", lambda *_: report)
    with pytest.raises(ValueError):
        verify(interface_case)


def test_runtime_change_after_verification_blocks_direct_guard_adoption(interface_case):
    case = interface_case
    report = verify(case)
    before = gate.content_digest(case.base)
    case.state.current = False
    with pytest.raises(ValueError, match="runtime or fixture"):
        ki_guard.activate_maintenance(case.base, case.candidate, report, source=case.source, quiescent=True)
    assert gate.content_digest(case.base) == before
    assert ki_guard.require_intact(case.base)


def test_runtime_change_while_kdt_runs_invalidates_result(interface_case, monkeypatch):
    case = interface_case
    real = gate._check_candidate
    def changed(*args, **kwargs):
        result = real(*args, **kwargs)
        case.state.current = False
        return result
    monkeypatch.setattr(gate, "_check_candidate", changed)
    with pytest.raises(ValueError, match="runtime or fixture"):
        verify(case)


def test_signed_report_without_interface_evidence_cannot_be_adopted(interface_case):
    case = interface_case
    report = deepcopy(verify(case))
    report.pop("interface_regression")
    report = maintenance._sign(case.candidate, report)
    with pytest.raises(ValueError, match="runtime or fixture"):
        maintenance.require_current(case.candidate, report)


def test_interface_module_change_invalidates_source_and_candidate_receipts(interface_case, monkeypatch):
    case = interface_case
    report = verify(case)
    original = published_kdt._module_identity
    monkeypatch.setattr(published_kdt, "_module_identity",
                        lambda module: "changed-module" if module is routing else original(module))
    with pytest.raises(ValueError, match="stale"):
        maintenance.require_current(case.candidate, report)


@pytest.fixture
def project_interface(investigation_case, investigation_maintenance, monkeypatch):
    project, active = investigation_case
    cfg = paths.KissConfig.default(project)
    cfg.python = str(project.parent / "selected-runtime/python.exe")
    cfg.relocation = "none"
    (active.parent / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    calls = []
    def check(root, *, source, name, runtime_python=None):
        calls.append(runtime_python)
        return {"ok": True, "fixture_maintenance": True, "source": source,
                "candidate_digest": gate.content_digest(root), "base_digest": source["base_digest"],
                "changes": [{"path": routing.TOOL_PATH}],
                "interface_regression": {"runtime": {"selected_python": str(Path(runtime_python).absolute())}}}
    monkeypatch.setattr(maintenance, "verify_candidate", check)
    return SimpleNamespace(pair=investigation_case, project=project, active=active, cfg=cfg, calls=calls)


def project_draft(case):
    job = new(case.pair)
    inv.run_reviews(case.project, job["id"], reviewer)
    return inv.create_draft(case.project, job["id"], "M", repair_mode="maintenance",
                            maintenance_recipe="wofost_parameter_routing")


@pytest.mark.parametrize("forward_slashes", [False, True])
def test_investigation_uses_exact_project_runtime_and_retains_readiness_gates(project_interface, forward_slashes):
    case = project_interface
    if forward_slashes:
        case.cfg.python = case.cfg.python.replace("\\", "/")
        (case.active.parent / paths.CONFIG_NAME).write_text(case.cfg.dumps(), encoding="utf-8")
    job = project_draft(case)
    result = inv.verify_draft(case.project, job["id"])
    expected = inv._project_runtime_config(case.project, "M", case.active)
    assert case.calls == [case.cfg.python]
    assert result["verification"]["runtime_identity"] == software_verification.runtime_identity(expected)
    assert result["can_apply"] and not result["verification"]["native_regression"]["verified"]
    applied = inv.apply(case.project, job["id"], result["verification"]["id"])
    assert applied["apply"]["requires_preflight"] and applied["apply"]["requires_plan_review"]
    assert inv.pending_preflight(case.project)["pending"]


@pytest.mark.parametrize("change", ["python", "roles", "missing_binding", "different_interpreter_report"])
def test_maintenance_apply_rechecks_runtime_binding_before_revoking_approval(project_interface, monkeypatch, change):
    case = project_interface
    job = project_draft(case)
    result = inv.verify_draft(case.project, job["id"])
    before = gate.content_digest(case.active)
    cfg = inv._project_runtime_config(case.project, "M", case.active)
    if change == "python":
        cfg.python = str(case.project.parent / "different-runtime/python.exe")
    elif change == "roles":
        cfg.roles["python_env"] = case.project.parent / "different-runtime"
    else:
        saved = inv._load(case.project, job["id"])
        if change == "missing_binding":
            saved["verification"].pop("runtime_identity")
        else:
            saved["verification"]["report"]["interface_regression"]["runtime"]["selected_python"] = "other-python"
        inv._save(case.project, saved)
    monkeypatch.setattr(inv, "_project_runtime_config", lambda *_: cfg)
    flow = flowgate.load()
    approval = flow.approval.read(case.project)
    assert not inv.get(case.project, job["id"])["can_apply"]
    with pytest.raises(ValueError, match="Runtime bindings changed"):
        inv.apply(case.project, job["id"], result["verification"]["id"])
    assert gate.content_digest(case.active) == before
    assert flow.approval.read(case.project) == approval
    assert not inv.pending_preflight(case.project)["pending"]


def test_runtime_sensitive_recipe_cannot_borrow_ancestor_or_missing_config(project_interface):
    case = project_interface
    config = case.active.parent / paths.CONFIG_NAME
    (case.project / paths.CONFIG_NAME).write_bytes(config.read_bytes())
    config.unlink()
    with pytest.raises(FileNotFoundError, match="kiss.toml"):
        project_draft(case)
    assert case.calls == []


def test_runtime_sensitive_recipe_cannot_use_a_rejected_downloads_runtime(rejected):
    _, package, _, project, _ = rejected
    before = gate.content_digest(package)
    job = make_reviewed(rejected)
    with pytest.raises(ValueError, match="prepared project KI and its saved runtime"):
        inv.create_draft(project, job["id"], "Demo", repair_mode="maintenance",
                         maintenance_recipe="wofost_parameter_routing")
    assert inv.get(project, job["id"])["draft"] is None
    assert gate.content_digest(package) == before


def test_runtime_binding_change_during_interface_verification_cannot_be_saved(project_interface, monkeypatch):
    case = project_interface
    job = project_draft(case)
    real = maintenance.verify_candidate
    def change_binding(*args, **kwargs):
        result = real(*args, **kwargs)
        changed = inv._project_runtime_config(case.project, "M", case.active)
        changed.python += ".changed"
        monkeypatch.setattr(inv, "_project_runtime_config", lambda *_: changed)
        return result
    monkeypatch.setattr(maintenance, "verify_candidate", change_binding)
    with pytest.raises(ValueError, match="Runtime bindings changed"):
        inv.verify_draft(case.project, job["id"])
    saved = inv.get(case.project, job["id"])
    assert saved["status"] == "verification_failed" and not saved["can_apply"]
