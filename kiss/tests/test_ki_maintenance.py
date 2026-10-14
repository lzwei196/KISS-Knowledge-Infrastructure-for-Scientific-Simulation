"""Maintenance boundary tests: real copies, literature, signatures and hashes.

The installed KDT engine and deterministic projection output are explicit test
doubles here; their own suites check the pinned engine and real recipes.
"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from kiss_cli import kdtstudio, ki_copy, ki_guard, ki_maintenance as maintenance
from kiss_cli import ki_verification, published_acceptance, published_literature
from .test_ki_verification_boundaries import isolated_engine, write_package


def metadata(root, name="Demo"):
    (root / "docs").mkdir(exist_ok=True)
    (root / "tools").mkdir(exist_ok=True)
    (root / "tools/run.py").write_text("print('actual model invocation stays untouched')\n", encoding="utf-8")
    (root / "docs/papers.json").write_text(json.dumps({
        "model": name, "note": "Exported bibliography only", "count": 1, "open_access": 1,
        "papers": [{"doi": "10.1234/model", "title": "Model reference", "access": "open"}],
    }), encoding="utf-8")
    (root / "docs/validation_convention.yaml").write_text(yaml.safe_dump({
        "model_id": name, "references": {"paper": {"doi": "10.1234/model"}},
        "validation": [{"cites": ["paper"], "threshold": 0.7}],
    }), encoding="utf-8")
    (root / "knowledge_infrastructure.yaml").write_text(
        "tools:\n  count: 1\n  files: [tools/run.py]\nsummary:\n  total_tools: 2\n", encoding="utf-8")


@pytest.fixture
def case(tmp_path, monkeypatch):
    from kiss_cli import ki_maintenance_recipes as recipes
    monkeypatch.delenv("GEOFORGE_KDT_ENGINE", raising=False)
    monkeypatch.setenv("GEOFORGE_KI_UPDATE_HOME", str(tmp_path / "updates"))
    with isolated_engine(tmp_path) as engine:
        base = tmp_path / "active"
        write_package(base)
        metadata(base)
        ki_guard.enroll(base)
        original = (base / "knowledge_infrastructure.yaml").read_bytes()
        generated = original.replace(b"total_tools: 2", b"total_tools: 1")
        monkeypatch.setattr(recipes, "expected_changes", lambda root, name: {
            "knowledge_infrastructure.yaml": generated})
        source = maintenance.capture_source(base, "Demo")
        candidate = tmp_path / "candidate"
        ki_copy.copytree(Path(source["base_root"]), candidate)
        (candidate / "knowledge_infrastructure.yaml").write_bytes(generated)
        yield SimpleNamespace(base=base, candidate=candidate, source=source,
                              engine=engine, root=tmp_path, recipes=recipes)


def verify(case):
    return maintenance.verify_candidate(case.candidate, source=case.source, name="Demo")


def test_frozen_source_preserves_exact_metadata_without_claiming_authoring(case):
    frozen = maintenance.require_source(case.source, name="Demo")
    assert frozen != case.base and not frozen.is_relative_to(case.base)
    assert ki_verification.content_digest(frozen) == case.source["base_digest"]
    assert case.source["source_scope"] == "intact_host_baseline"
    assert case.source["literature_evidence"] == "published_metadata_only"
    assert case.source["authoring_verification"] is False
    assert not (frozen / "docs/gathered_papers.json").exists()
    assert published_literature.check(frozen, model_name="Demo")["ok"]


def test_exact_count_projection_runs_kdt_and_gets_separate_local_receipt(case):
    report = verify(case)
    assert report["ok"] and len(case.engine.seen) == 1
    assert report["state"] == "MaintenanceVerified"
    assert report["literature_evidence"] == "unchanged_published_metadata_only"
    assert report["authoring_verification"] is False and report["local_only"] is True
    assert report["native_regression"] == {"status": "not_run", "verified": False}
    assert [row["path"] for row in report["changes"]] == ["knowledge_infrastructure.yaml"]
    assert maintenance.require_current(case.candidate, report, source=case.source) == report
    assert ki_verification.current_report(case.candidate) is None
    with pytest.raises(ValueError):
        ki_verification.require_current(case.candidate, report)


def test_noop_still_runs_current_kdt_without_claiming_a_repair(case):
    (case.candidate / "knowledge_infrastructure.yaml").write_bytes(
        (case.base / "knowledge_infrastructure.yaml").read_bytes())
    report = verify(case)
    assert len(case.engine.seen) == 1 and report["changes"] == []


@pytest.mark.parametrize("relative", ["docs/papers.json", "docs/validation_convention.yaml",
                                     "dag.yaml", "tools/run.py", "SKILL.md"])
def test_non_recipe_edits_cannot_reuse_evidence(case, relative):
    path = case.candidate / relative
    path.write_bytes(path.read_bytes() + b"\n# unreviewed change\n")
    with pytest.raises(ValueError, match="maintenance contract"):
        verify(case)
    assert case.engine.seen == []


@pytest.mark.parametrize("change", ["add", "remove", "fake_count"])
def test_file_set_and_projection_are_exact(case, change):
    if change == "add":
        (case.candidate / "docs/gathered_papers.json").write_text("[]", encoding="utf-8")
    elif change == "remove":
        (case.candidate / "tools/run.py").unlink()
    else:
        (case.candidate / "knowledge_infrastructure.yaml").write_text("summary: {total_tools: 99}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        verify(case)
    assert case.engine.seen == []


def test_unrelated_kdt_failure_is_not_filtered(case):
    case.engine.ok = False
    report = verify(case)
    assert not report["ok"] and report["state"] == "MaintenanceRejected"
    assert "fixture KDT failure" in report["failures"]
    with pytest.raises(ValueError):
        maintenance.require_current(case.candidate, report)


def test_intact_baseline_required_before_source_capture(case):
    (case.base / "SKILL.md").write_text("changed active bytes", encoding="utf-8")
    with pytest.raises(ValueError, match="Active KI changed"):
        maintenance.capture_source(case.base, "Demo")


def test_unmanaged_source_cannot_start_maintenance(case):
    other = case.root / "unknown"
    ki_copy.copytree(case.base, other)
    with pytest.raises(ValueError, match="no host baseline"):
        maintenance.capture_source(other, "Demo")


def test_invalid_existing_bibliography_is_not_reusable(case):
    other = case.root / "invalid"
    ki_copy.copytree(case.base, other)
    (other / "docs/papers.json").write_text("{}", encoding="utf-8")
    ki_guard.enroll(other)
    with pytest.raises(ValueError, match="published evidence is invalid"):
        maintenance.capture_source(other, "Demo")


def test_model_identity_cannot_be_changed(case):
    with pytest.raises(ValueError, match="published evidence is invalid"):
        maintenance.capture_source(case.base, "Other")
    with pytest.raises(ValueError, match="context is unauthenticated or stale"):
        maintenance.verify_candidate(case.candidate, source=case.source, name="Other")


@pytest.mark.parametrize("what", ["source_signature", "report_signature", "candidate", "frozen",
                                  "policy", "engine", "engine_override"])
def test_receipt_rejects_changed_or_stale_evidence(case, monkeypatch, what):
    report = verify(case)
    if what == "source_signature":
        report["source"]["name"] = "Other"
    elif what == "report_signature":
        report["checked_at"] = 0
    elif what == "candidate":
        (case.candidate / "tools/run.py").write_text("changed", encoding="utf-8")
    elif what == "frozen":
        (Path(case.source["base_root"]) / "tools/run.py").write_text("changed", encoding="utf-8")
    elif what == "policy":
        monkeypatch.setattr(maintenance, "POLICY", "different-policy")
    elif what == "engine":
        monkeypatch.setattr(kdtstudio, "engine_source_digest", lambda: "0" * 64)
    else:
        monkeypatch.setenv("GEOFORGE_KDT_ENGINE", str(case.root / "unreviewed"))
    with pytest.raises(ValueError):
        maintenance.require_current(case.candidate, report)


def test_adoption_does_not_invalidate_frozen_source_receipt(case):
    report = verify(case)
    (case.base / "knowledge_infrastructure.yaml").write_bytes(
        (case.candidate / "knowledge_infrastructure.yaml").read_bytes())
    # Host guard adoption owns updating the active baseline; receipt identity
    # intentionally binds the frozen source, not the previous active bytes.
    assert maintenance.require_current(case.candidate, report) == report


def test_source_from_another_capture_is_not_interchangeable(case):
    report = verify(case)
    other = maintenance.capture_source(case.base, "Demo")
    assert other["base_digest"] == case.source["base_digest"]
    with pytest.raises(ValueError, match="another source context"):
        maintenance.require_current(case.candidate, report, source=other)


def test_preflight_behavior_failure_cannot_become_acceptance(case, monkeypatch):
    generated = (case.candidate / "preflight_check.py").read_bytes() + b"# reporting fixture\n"
    monkeypatch.setattr(case.recipes, "expected_changes", lambda root, name: {
        "knowledge_infrastructure.yaml": (case.candidate / "knowledge_infrastructure.yaml").read_bytes(),
        "preflight_check.py": generated})
    monkeypatch.setattr(case.recipes, "validate_preflight_behavior", lambda *_: {"ok": False, "status": "failed"})
    (case.candidate / "preflight_check.py").write_bytes(generated)
    report = verify(case)
    assert not report["ok"] and "behavior regression failed" in report["failures"][-1]
    with pytest.raises(ValueError):
        maintenance.require_current(case.candidate, report)


def test_candidate_race_during_verification_invalidates_acceptance(case, monkeypatch):
    real = ki_verification._check_candidate
    def changed(*args, **kwargs):
        report = real(*args, **kwargs)
        (case.candidate / "tools/run.py").write_text("late change", encoding="utf-8")
        return report
    monkeypatch.setattr(ki_verification, "_check_candidate", changed)
    with pytest.raises(ValueError, match="changed during verification"):
        verify(case)


def test_authentic_rejected_publication_can_supply_source_identity_only(case):
    from kiss_cli import ki_updates
    staging = ki_updates.update_root() / ".incoming-source"
    package = staging / "models/Demo"
    ki_copy.copytree(case.base, package)
    origin = published_acceptance._issue_origin(staging, source_commit="d" * 40,
        archive_sha256="a" * 64, source_content_sha256=ki_updates._snapshot_content_hash(staging),
        overlay={}, trees={})
    case.engine.ok = False
    rejected = published_acceptance.verify_candidate(package, name="Demo", kind="process_model", origin=origin)
    assert rejected["ok"] is False
    quarantine = ki_updates.update_root() / "quarantine/fixture"
    quarantine.parent.mkdir(parents=True)
    staging.rename(quarantine)
    package = quarantine / "models/Demo"
    source = maintenance.capture_source(package, "Demo", publication_report=rejected)
    assert source["source_scope"] == "signed_official_publication_source"
    assert source["source_report"]["ok"] is False and source["authoring_verification"] is False
    tampered = deepcopy(rejected)
    tampered["source_commit"] = "e" * 40
    with pytest.raises(ValueError, match="publication provenance"):
        maintenance.capture_source(package, "Demo", publication_report=tampered)

