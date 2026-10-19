"""Real guarded setup→project path derivation with explicit KDT/reviewer doubles.

Published path/case fixtures and real signatures are used. Inert runtime files
are never executed; this suite proves orchestration, not native readiness.
"""
from dataclasses import replace
import hashlib
from pathlib import Path
import shutil

import pytest

from kiss_cli import (helper_identity, install, ki_adaptations as adapt, ki_guard,
    ki_verification, paths, project_paths, project_setup_repair as derivation,
    setup, setup_ki_repair)
from kiss_cli.manifest import Manifest
from . import test_ki_maintenance_shaw as shaw_fixture
from . import test_ki_maintenance_epanet as epanet_fixture
from .test_ki_verification_boundaries import isolated_engine
from .test_setup_ki_repair import reviewer as review_fixture


@pytest.fixture(params=["SHAW", "EPANET"])
def case(tmp_path, monkeypatch, request):
    model = request.param
    fixture = shaw_fixture if model == "SHAW" else epanet_fixture
    for key, folder in (("GEOFORGE_KI_INVESTIGATION_HOME", "investigations"),
                        ("GEOFORGE_KI_ADAPTATION_HOME", "adaptations"),
                        ("GEOFORGE_FLOW_REGISTRY", "registry"),
                        ("GEOFORGE_KDT_HOME", "studio")):
        monkeypatch.setenv(key, str(tmp_path / folder))
    monkeypatch.delenv("GEOFORGE_KDT_ENGINE", raising=False)
    with isolated_engine(tmp_path) as engine:
        shared, active = fixture.prepare(tmp_path)
        library = tmp_path / "library"
        source = library / "models" / model
        source.parent.mkdir(parents=True)
        shutil.move(str(active), source)
        for relative, filename in ((fixture.fix.PREFLIGHT, model.lower() + "_preflight_published.py"),
                                   (fixture.fix.RUNNER, model.lower() + "_runner_published.py")):
            (source / relative).write_bytes((fixture.FIXTURES / filename).read_bytes())
        (source / fixture.fix.MANIFEST).write_text(fixture.MANIFEST_TEXT, encoding="utf-8")
        helper = library / "ki_tools_common"
        (helper / "ki_tools_common").mkdir(parents=True)
        (helper / "ki_tools_common/__init__.py").write_text(
            'ROOT = "KISSPATH_ROOT"\nOUTPUTS = "KISSPATH_OUTPUTS"\n')
        shared.roles["ki_tools_common"] = shared.root / "projected_helpers"
        setup.prepare_common(shared, library)
        (shared.root / "kiss.toml").write_text(shared.dumps(), encoding="utf-8")
        manifest = Manifest(model=model)
        adapt.materialise(source, active, shared, model=model, library_root=library, manifest=manifest)

        def reviewer(role, context, digest, stop, emit):
            result = review_fixture(role, context, digest, stop, emit)
            result["findings"][0]["evidence"] = [f"kis/{model}/preflight_check.py"]
            return result

        job = setup_ki_repair.run(shared.root, ki_name=model, source_root=source,
            library_root=library, manifest=manifest, provider="api:fixture",
            issue="Exact Windows path repair", recipe=fixture.fix.RECIPE, reviewer=reviewer)
        assert job["status"] == "applied", job.get("verification")
        project = tmp_path / "new project"
        project.mkdir()
        cfg = project_paths.model_config(project, model, shared)
        home = project / "models" / model
        helper_cfg = replace(cfg, root=home, roles={**cfg.roles, "ki_tools_common": home / "ki_tools_common"})
        cfg.roles["ki_tools_common"] = setup.prepare_common(helper_cfg, library)
        yield dict(model=model, fixture=fixture, engine=engine, source=source, library=library,
            shared=shared, cfg=cfg, live=home / "ki", manifest=manifest)


def args(case):
    return dict(model=case["model"], setup_root=case["shared"].root,
        library_root=case["library"], manifest=case["manifest"])


def make(case):
    return derivation.materialise(case["source"], case["live"], case["cfg"], **args(case))


def current(case):
    return derivation.require_current(case["live"], case["cfg"], source=case["source"], **args(case))


def test_approved_setup_is_reverified_for_exact_project_without_readiness(case):
    setup_files = {p: p.read_bytes() for p in (case["shared"].root / "kiss.toml",
        setup_ki_repair._pointer(case["shared"].root))}
    before = len(case["engine"].seen)
    ordinary, record = make(case)
    assert len(case["engine"].seen) > before
    assert ordinary.dest == case["live"]
    assert record["status"] == "complete"
    assert record["preflight_passed"] is False and record["native_verified"] is False
    assert record["project_report"]["path_binding_regression"]["runtime"]["target_ki"] == str(case["live"])
    assert record["ordinary_projection"] == adapt._read(adapt._location(case["live"]))
    assert record["ordinary_projection"]["projected_digest"] != record["projected_digest"]
    assert derivation.require_record(case["live"], case["cfg"], model=case["model"]) == record
    assert current(case) == record
    assert not (case["cfg"].root / ".geoforge/project-verification").exists()
    for path, raw in setup_files.items():
        assert path.read_bytes() == raw
    for relative, item in record["protected_inventory"].items():
        if relative.startswith("test_cases/") and item["kind"] == "file":
            assert hashlib.sha256((case["live"] / relative).read_bytes()).hexdigest() == item["sha256"]
    text = (case["live"] / "preflight_check.py").read_text(encoding="utf-8")
    if case["model"] == "SHAW":
        assert 'SHAW_DIST_DIR = HYDROCRAFT_ROOT / "model" / "shaw" / "Shaw303"' in text
        copied = case["cfg"].root / "model/shaw/Shaw303"
        assert {p.name for p in copied.iterdir()} == set(shaw_fixture.fix.CASE_SHA256S)
    else:
        assert 'MODEL_DIR = Path("' + str(case["cfg"].root).replace("\\", "/") in text
        assert not (case["cfg"].root / "model").exists()
    assert case["cfg"].roles["outputs"].is_relative_to(case["cfg"].root)
    assert case["cfg"].roles["ki_tools_common"].is_relative_to(case["live"].parent)
    assert ((case["cfg"].roles["ki_tools_common"] / "ki_tools_common/__init__.py").read_bytes()
            != (case["shared"].roles["ki_tools_common"] / "ki_tools_common/__init__.py").read_bytes())


@pytest.mark.parametrize("fault", ["source", "setup_runtime", "setup_helpers", "project_helpers", "active", "config", "record", "baseline", "policy"])
def test_currentness_fails_closed(case, fault, monkeypatch):
    make(case)
    if fault == "source":
        (case["source"] / "SKILL.md").write_text("changed upstream")
    elif fault == "setup_runtime":
        Path(case["shared"].python).write_bytes(b"same path replacement")
    elif fault in ("setup_helpers", "project_helpers"):
        cfg = case["shared"] if fault == "setup_helpers" else case["cfg"]
        (cfg.roles["ki_tools_common"] / "ki_tools_common/__init__.py").write_text("changed")
    elif fault == "active":
        (case["live"] / "SKILL.md").write_text("changed")
    elif fault == "config":
        with (case["live"].parent / "kiss.toml").open("a") as stream:
            stream.write("\n# changed exact saved configuration\n")
    elif fault == "record":
        path = derivation._location(case["live"])
        path.write_text(path.read_text(encoding="utf-8").replace('"complete"', '"forged"'), encoding="utf-8")
    elif fault == "baseline":
        adapt._location(case["live"]).unlink()
    else:
        monkeypatch.setattr(derivation, "_policy", lambda: "changed policy")
    with pytest.raises((ValueError, RuntimeError)):
        current(case)


def test_kdt_rejection_retains_pending_and_cannot_be_reopened_as_plain_projection(case):
    case["engine"].ok = False
    with pytest.raises((ValueError, RuntimeError)):
        make(case)
    assert derivation._read(case["live"])["status"] == "pending"
    assert ki_guard.require_intact(case["live"])
    with pytest.raises(ValueError, match="incomplete"):
        current(case)
    with pytest.raises(ValueError, match="fresh"):
        make(case)


def test_existing_managed_project_is_never_silently_repaired(case):
    adapt.materialise(case["source"], case["live"], case["cfg"], model=case["model"],
        library_root=case["library"], manifest=case["manifest"])
    digest = ki_verification.content_digest(case["live"])
    with pytest.raises(ValueError, match="fresh"):
        make(case)
    assert ki_verification.content_digest(case["live"]) == digest
    assert not derivation._location(case["live"]).exists()


def test_reference_asset_conflict_or_drift_fails_closed(case):
    if case["model"] != "SHAW":
        return
    folder = case["cfg"].root / "model/shaw/Shaw303"
    folder.mkdir(parents=True)
    existing = folder / "Trial.tem"
    existing.write_bytes(b"owned by this project already")
    with pytest.raises(ValueError, match="already exists|must be new"):
        make(case)
    assert existing.read_bytes() == b"owned by this project already"
    assert not case["live"].exists()
    existing.unlink()
    folder.rmdir()
    make(case)
    existing.write_bytes(b"changed after adoption")
    with pytest.raises((ValueError, RuntimeError)):
        current(case)


def test_no_adoption_returns_none_without_creating_project_files(case):
    setup_ki_repair._pointer(case["shared"].root).unlink()
    assert make(case) is None
    assert not case["live"].exists()
    assert not derivation._location(case["live"]).exists()


def test_setup_preflight_refresh_does_not_revoke_unchanged_derivation(case):
    _, before = make(case)
    setup_ki_repair.finish_preflight(case["shared"].root, passed=False,
        source_root=case["source"], library_root=case["library"],
        manifest=case["manifest"], cfg=case["shared"])
    after = current(case)
    assert after == before
    assert after["preflight_passed"] is False


def test_changed_selected_source_does_not_borrow_previous_setup_adoption(case, tmp_path):
    fresh_library = tmp_path / "other-library"
    shutil.copytree(case["library"], fresh_library)
    with pytest.raises(ValueError, match="Selected source"):
        derivation.materialise(fresh_library / "models" / case["model"], case["live"],
            case["cfg"], model=case["model"], setup_root=case["shared"].root,
            library_root=fresh_library, manifest=case["manifest"])
    assert not case["live"].exists()
    assert not derivation._location(case["live"]).exists()


def test_failed_completion_write_keeps_pending_after_guarded_adoption(case, monkeypatch):
    write = derivation._write

    def reject_completion(live, document):
        if document["status"] == "complete":
            raise OSError("fixture storage failure")
        return write(live, document)

    monkeypatch.setattr(derivation, "_write", reject_completion)
    with pytest.raises(OSError, match="storage failure"):
        make(case)
    assert ki_guard.require_intact(case["live"])
    assert derivation._read(case["live"])["status"] == "pending"
    with pytest.raises(ValueError, match="incomplete"):
        derivation.require_record(case["live"], case["cfg"], model=case["model"])


def test_runtime_change_after_project_kdt_prevents_adoption(case, monkeypatch):
    verifier = case["fixture"].fix
    verify = verifier.verify_candidate

    def verify_then_change(*args, **kwargs):
        result = verify(*args, **kwargs)
        Path(case["shared"].python).write_bytes(b"changed while KDT completed")
        return result

    monkeypatch.setattr(verifier, "verify_candidate", verify_then_change)
    with pytest.raises((ValueError, RuntimeError)):
        make(case)
    proof = adapt._read(adapt._location(case["live"]))
    assert ki_verification.content_digest(case["live"]) == proof["projected_digest"]
    assert derivation._read(case["live"])["status"] == "pending"


def test_unmaintained_missing_installation_is_noop(tmp_path):
    cfg = paths.KissConfig.default(tmp_path / "project")
    live = cfg.root / "models/Demo/ki"
    assert derivation.materialise(tmp_path / "source", live, cfg, model="Demo",
        setup_root=tmp_path / "absent-installation", library_root=None,
        manifest=Manifest(model="Demo")) is None
    assert not cfg.root.exists()


def test_historical_baseline_is_distinct_from_current_revision_authority(case):
    _, original = make(case)
    assert derivation.require_baseline(case["live"], case["cfg"], case["model"]) == original
    retained = derivation._location(case["live"]).parent / "candidate"
    assert derivation.require_baseline(case["live"], case["cfg"], case["model"], retained=retained) == original
    # Explicit synthetic later guard record, not a valid subsequent maintenance
    # chain. Historical evidence alone must never claim this live edit is valid.
    (case["live"] / "SKILL.md").write_text("synthetic later revision")
    ki_guard._save(case["live"], ki_verification.content_digest(case["live"]), origin="fixture-later-revision")
    with pytest.raises(ValueError, match="subsequent adoption lineage"):
        current(case)
    historical = derivation.require_baseline(case["live"], case["cfg"], case["model"])
    assert historical["projected_digest"] == original["projected_digest"]
    assert historical["projected_digest"] != ki_verification.content_digest(case["live"])
    (retained / "SKILL.md").write_text("tampered retained baseline")
    with pytest.raises((ValueError, RuntimeError)):
        derivation.require_baseline(case["live"], case["cfg"], case["model"])


def test_cancellation_before_start_creates_no_derivation(case, monkeypatch):
    def stopped():
        raise install.InstallStopped("fixture stopped")
    monkeypatch.setattr(install, "check_cancelled", stopped)
    with pytest.raises(install.InstallStopped):
        make(case)
    assert not derivation._location(case["live"]).exists()
    assert not case["live"].exists()


def test_unknown_transform_does_not_borrow_supported_adoption(case):
    with pytest.raises(ValueError, match="supported project path derivation"):
        derivation.materialise(case["source"], case["live"], case["cfg"],
            **{**args(case), "model": "DifferentModel"})
    assert not derivation._location(case["live"]).exists()


def test_missing_record_with_preserved_authority_fails_closed(case):
    make(case)
    derivation._location(case["live"]).unlink()
    with pytest.raises(ValueError, match="record is missing"):
        derivation.require_record(case["live"], case["cfg"], model=case["model"])


def test_existing_malformed_toml_is_never_rewritten(case):
    config = case["live"].parent / "kiss.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    raw = b'[kiss]\npython = "C:\\Users\\legacy\\python.exe"\n'
    config.write_bytes(raw)
    with pytest.raises(ValueError):
        make(case)
    assert config.read_bytes() == raw
    assert not derivation._location(case["live"]).exists()
    assert not case["live"].exists()
