"""Real static port copies and bounded overlays; no model/preflight execution."""
from copy import deepcopy
import ast
import hashlib
import json
from pathlib import Path

import pytest

from kiss_cli import ki_adaptations as adapt, ki_fresh_paths as fresh, ki_guard, ki_tree
from kiss_cli import ki_path_contracts as retained, paths, port, project_verification
from kiss_cli.catalog import KI
from .test_ki_path_contracts import prepare


def case(tmp_path, *, newline="\n"):
    source, _, cfg, target = prepare(tmp_path, portable=True, newline=newline)
    (source / "SKILL.md").write_bytes(b"# Published fixture; no execution\n")
    (source / "test_cases").mkdir()
    (source / "test_cases/data.txt").write_bytes(b"KISSPATH_ROOT\r\nunchanged input bytes\n")
    (source / "notes.txt").write_bytes(b"KISSPATH_OUTPUTS/result.csv\n")
    (target / retained.RUNNER).unlink()
    target.rmdir()
    return source, cfg, target


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("staged", [False, True])
def test_real_materialise_preserves_ordinary_bytes_and_uses_logical_target(tmp_path, newline, staged):
    source, cfg, target = case(tmp_path, newline=newline)
    dest = tmp_path / "runtime-candidate" if staged else target
    original = fresh.tree_files(source)
    ordinary = tmp_path / "ordinary"
    baseline = port.materialise(source, ordinary, cfg)
    assert not baseline.unresolved and not baseline.corrupted
    old = fresh.tree_files(ordinary)
    report, proof = adapt.project_runtime(source, dest, cfg, model="WOFOST", target_root=target)
    assert not report.unresolved and not report.corrupted
    assert fresh.tree_files(source) == original
    assert proof["ordinary_digest"] == ki_tree.digest(ordinary)
    assert proof["ordinary_files"] == old
    changed = {name for name, value in fresh.tree_files(dest).items() if old[name] != value}
    assert changed == {retained.PREFLIGHT, retained.MANIFEST}
    text = (dest / retained.PREFLIGHT).read_text(encoding="utf-8")
    values = retained._assignments(ast.parse(text))
    assert ast.literal_eval(values["PYTHON"].value) == cfg.python.replace("\\", "/")
    assert ast.literal_eval(values["KI_TOOLS_COMMON"].value) == str(cfg.roles["ki_tools_common"]).replace("\\", "/")
    assert ast.dump(values["MODEL_ENTRYPOINT"].value) == ast.dump(ast.parse('os.path.join(KI_DIR,"run_and_score.py")', mode="eval").body)
    assert str(target / retained.RUNNER).replace("\\", "/") in (dest / retained.MANIFEST).read_text(encoding="utf-8")
    assert str(dest).replace("\\", "/") not in (dest / retained.MANIFEST).read_text() if staged else True
    assert (dest / retained.RUNNER).read_bytes() == (ordinary / retained.RUNNER).read_bytes()
    assert (dest / "test_cases/data.txt").read_bytes() == (source / "test_cases/data.txt").read_bytes()
    assert target.exists() is (not staged)
    assert proof["runtime_bound"] is False
    assert all(proof[key] is False for key in ("model_execution", "native_execution", "preflight_passed", "scientific_validation"))
    assert not ki_guard.is_managed(dest)
    fresh.require_fresh_current(proof)
    with pytest.raises(ValueError):
        retained.require_runtime_current(proof)
    assert project_verification.status(cfg.root, KI("WOFOST", dest))["can_run"] is False


@pytest.mark.parametrize("damage", ["preflight", "runner", "manifest", "missing_runner", "missing_manifest", "empty"])
def test_unknown_or_incomplete_wofost_fails_before_destination_or_enrollment(tmp_path, damage):
    source, cfg, target = case(tmp_path)
    if damage == "preflight":
        p = source / retained.PREFLIGHT
        p.write_text(p.read_text().replace("critical=True", "critical=False", 1))
    elif damage == "runner":
        p = source / retained.RUNNER
        p.write_text(p.read_text(encoding="utf-8") + "\nside_effect()\n", encoding="utf-8")
    elif damage == "manifest":
        p = source / retained.MANIFEST
        p.write_text(p.read_text().replace("type: Python", "type: changed"))
    elif damage.startswith("missing_"):
        (source / (retained.RUNNER if damage == "missing_runner" else retained.MANIFEST)).unlink()
    else:
        source = tmp_path / "empty"; source.mkdir()
    dest = tmp_path / "stage"
    with pytest.raises(adapt.AdaptationError, match="Unsupported WOFOST fresh path contract"):
        adapt.project_runtime(source, dest, cfg, model="WOFOST", target_root=target)
    assert not dest.exists() and not target.exists()


def test_no_overwrite_of_existing_active_or_staged_content(tmp_path):
    source, cfg, target = case(tmp_path)
    target.mkdir(); (target / "sentinel").write_bytes(b"preserved")
    before = fresh.tree_files(target)
    with pytest.raises(adapt.AdaptationError, match="new empty destination"):
        adapt.project_runtime(source, target, cfg, model="WOFOST", target_root=target)
    assert fresh.tree_files(target) == before


@pytest.mark.parametrize("change", ["helper", "python", "config", "source", "candidate", "policy", "ordinary", "scope", "promotion"])
def test_current_fresh_proof_rejects_source_runtime_or_scope_drift(tmp_path, monkeypatch, change):
    source, cfg, target = case(tmp_path)
    dest = tmp_path / "stage"
    _, proof = adapt.project_runtime(source, dest, cfg, model="WOFOST", target_root=target)
    if change == "helper":
        (cfg.roles["ki_tools_common"] / "ki_tools_common/__init__.py").write_text("changed")
    elif change == "python":
        Path(cfg.python).write_bytes(b"changed")
    elif change == "config":
        proof["runtime"]["config"]["python"] = str(tmp_path / "other.exe")
    elif change == "source":
        (source / "notes.txt").write_text("changed")
    elif change == "candidate":
        (dest / "test_cases/data.txt").write_text("changed")
    elif change == "policy":
        monkeypatch.setattr(fresh, "source_digest", lambda: "0" * 64)
    elif change == "ordinary":
        proof["ordinary_files"]["notes.txt"]["sha256"] = "0" * 64
    elif change == "scope":
        proof["scope"] = "path_binding_regression"
    else:
        proof["preflight_passed"] = True
    with pytest.raises((ValueError, OSError)):
        fresh.require_fresh_current(proof)


def test_whole_overlay_verification_rejects_unrelated_modification(tmp_path, monkeypatch):
    source, cfg, target = case(tmp_path)
    original = fresh.validate_fresh_projection
    def corrupt(base, candidate, config, **kwargs):
        (candidate / "notes.txt").write_text("outside scope")
        return original(base, candidate, config, **kwargs)
    monkeypatch.setattr(fresh, "validate_fresh_projection", corrupt)
    with pytest.raises(ValueError, match="two-file scope"):
        adapt.project_runtime(source, tmp_path / "stage", cfg, model="WOFOST", target_root=target)
    assert not target.exists()


def test_source_change_during_real_materialise_never_publishes_a_proof(tmp_path, monkeypatch):
    source, cfg, target = case(tmp_path)
    materialise = port.materialise
    def changed(base, dest, config):
        result = materialise(base, dest, config)
        (base / "notes.txt").write_text("source changed")
        return result
    monkeypatch.setattr(port, "materialise", changed)
    with pytest.raises(adapt.AdaptationError, match="Source or saved runtime context changed"):
        adapt.project_runtime(source, tmp_path / "stage", cfg, model="WOFOST", target_root=target)
    assert not target.exists()


def test_enrolled_fresh_provenance_binds_normalizer_and_never_readiness(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_ADAPTATION_HOME", str(tmp_path / "authority"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    source, cfg, target = case(tmp_path)
    adapt.materialise(source, target, cfg, model="WOFOST")
    doc = adapt.projection(target, cfg)
    assert doc["context"]["path_normalizer"] == fresh.source_digest()
    assert doc["path_projection"]["candidate_digest"] == ki_tree.digest(target)
    assert doc["adaptation_id"] is None and doc["portable_report"] is None
    assert ki_guard.is_managed(target)
    assert not project_verification.status(cfg.root, KI("WOFOST", target))["can_run"]
    monkeypatch.setattr(fresh, "source_digest", lambda: "0" * 64)
    with pytest.raises(ValueError):
        adapt.projection(target, cfg)


def test_staged_proof_cannot_retarget_to_unreviewed_ki(tmp_path):
    source, cfg, target = case(tmp_path)
    _, proof = adapt.project_runtime(source, tmp_path / "stage", cfg, model="WOFOST", target_root=target)
    with pytest.raises(ValueError):
        fresh.require_fresh_current(proof, candidate_root=tmp_path / "unrelated")


def test_no_old_runtime_report_api_relaxation(tmp_path):
    source, cfg, target = case(tmp_path)
    _, proof = adapt.project_runtime(source, tmp_path / "stage", cfg, model="WOFOST", target_root=target)
    assert not target.exists()
    with pytest.raises(ValueError):
        retained.validate_behavior(source, tmp_path / "stage", cfg, target_root=target)
    with pytest.raises(ValueError):
        retained.require_runtime_current(proof)


def test_persisted_fresh_proof_uses_retained_source_not_disposable_library(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_ADAPTATION_HOME", str(tmp_path / "authority"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    source, cfg, target = case(tmp_path)
    adapt.materialise(source, target, cfg, model="WOFOST")
    first = adapt.projection(target, cfg)
    assert first["path_projection"]["source_root"] == first["portable_root"]
    assert Path(first["portable_root"]) != source
    (source / "notes.txt").write_text("original download no longer authoritative")
    assert adapt.projection(target, cfg) == first


def reusable_case(tmp_path, monkeypatch):
    from kiss_cli import kdtstudio, ki_copy
    monkeypatch.setenv("GEOFORGE_KI_ADAPTATION_HOME", str(tmp_path / "authority"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.delenv("GEOFORGE_KDT_ENGINE", raising=False)
    monkeypatch.setattr(kdtstudio, "engine_source_digest", lambda: "e" * 64)
    source, cfg, target = case(tmp_path)
    library = tmp_path / "library"
    ki_copy.copytree(cfg.roles["ki_tools_common"], library / "ki_tools_common")
    adapt.materialise(source, target, cfg, model="WOFOST", library_root=library)
    assert adapt.projection(target, cfg)["reusable"]
    return source, cfg, target


def test_wofost_registration_keeps_exact_kdt_boundary_and_retained_path_evidence(tmp_path, monkeypatch):
    # Synthetic KDT reports exercise only exact provenance/adoption plumbing.
    # They do not certify this fixture as a scientific package or native run.
    from kiss_cli import ki_copy
    from .test_ki_adaptations import accepted
    source, cfg, target = reusable_case(tmp_path, monkeypatch)
    portable = tmp_path / "portable-draft"
    ki_copy.copytree(source, portable)
    (portable / "notes.txt").write_text("reviewed portable repair\n")
    runtime = tmp_path / "runtime-draft"
    adapt.project_runtime(portable, runtime, cfg, model="WOFOST", target_root=target)
    with pytest.raises(ValueError):
        adapt.prepare_registration(target, cfg, portable, {}, runtime, accepted(runtime))
    prepared = adapt.prepare_registration(target, cfg, portable, accepted(portable), runtime, accepted(runtime))
    assert prepared["path_projection"]["source_root"] == prepared["portable_root"]
    with pytest.raises(adapt.AdaptationError, match="not been adopted"):
        adapt.register(prepared, target, cfg)
    ki_guard.activate(target, runtime, prepared["runtime_report"], quiescent=True)
    adapt.register(prepared, target, cfg)
    before = adapt.projection(target, cfg)
    (portable / "notes.txt").write_text("draft no longer authoritative")
    assert adapt.projection(target, cfg) == before
    assert (target / "notes.txt").read_text() == "reviewed portable repair\n"
    assert not project_verification.status(cfg.root, KI("WOFOST", target))["can_run"]


def test_old_projection_policy_requires_explicit_reconciliation_before_registration(tmp_path, monkeypatch):
    from .test_ki_adaptations import accepted
    source, cfg, target = reusable_case(tmp_path, monkeypatch)
    origin = adapt.projection(target, cfg)
    origin["context"]["projection_policy"] = "older-policy"
    origin["context_id"] = adapt._hash(origin["context"])
    adapt._write(adapt._location(target), origin)
    with pytest.raises(adapt.AdaptationError, match="older path projection policy"):
        adapt.prepare_registration(target, cfg, source, accepted(source), target, accepted(target))
