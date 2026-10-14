"""Publication trust cannot substitute for authoring, repair or arbitrary imports.

The structural KDT engine is an explicit fixture; hashes, signatures, origin
binding, snapshot validation, catalogue enrollment and adoption gates are real.
"""
from copy import deepcopy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from kiss_cli import kdtstudio, ki_guard, ki_investigation, ki_updates, ki_verification
from kiss_cli import published_acceptance as publication
from kiss_cli.catalog import Catalog
from .test_ki_verification_boundaries import (
    import_handler, isolated_engine, write_package, zip_package,
)


@pytest.fixture
def case(tmp_path, monkeypatch):
    for name, folder in (("GEOFORGE_KI_UPDATE_HOME", "updates"),
                         ("GEOFORGE_KDT_HOME", "studio"),
                         ("GEOFORGE_KI_INVESTIGATION_HOME", "investigations"),
                         ("GEOFORGE_FLOW_REGISTRY", "registry")):
        monkeypatch.setenv(name, str(tmp_path / folder))
    monkeypatch.delenv("GEOFORGE_KDT_ENGINE", raising=False)
    monkeypatch.setattr(ki_guard, "_legacy_installation_roots", lambda: [])
    with isolated_engine(tmp_path) as engine:
        # Consume legacy migration before introducing any publication fixture.
        # A later arbitrary catalogue cannot gain trust through first-use setup.
        ki_guard._legacy_inventory()
        staging = ki_updates.update_root() / ".incoming-fixture"
        package = staging / "models" / "Demo"
        write_package(package)
        common = staging / "ki_tools_common"
        (common / "ki_tools_common").mkdir(parents=True)
        (common / "ki_tools_common/__init__.py").write_text("", encoding="utf-8")
        (common / "pyproject.toml").write_text(
            '[project]\nname="ki_tools_common"\nversion="0.1.0"\n', encoding="utf-8")
        origin_args = {"source_commit": "d" * 40, "archive_sha256": "a" * 64,
                       "source_content_sha256": ki_updates._snapshot_content_hash(staging),
                       "overlay": {}, "trees": {"models": "1" * 40,
                       "manifests": "2" * 40, "shared_tools": "3" * 40, "data_kis": None}}
        origin = publication._issue_origin(staging, **origin_args)
        yield SimpleNamespace(root=tmp_path, staging=staging, package=package,
                              origin=origin, origin_args=origin_args, engine=engine)
        ki_investigation._STOPS.clear()
        ki_investigation._RUNNING.clear()


def accepted(case):
    report = publication.verify_candidate(case.package, name="Demo", kind="process_model",
                                          origin=case.origin)
    assert report["ok"], report
    return report


def managed_snapshot(case, report=None):
    report = report if report is not None else accepted(case)
    row = {"name": "Demo", "state": report["state"], "report": report,
           "candidate_digest": ki_verification.content_digest(case.package)}
    revision = "b" * 32
    envelope = publication._seal_snapshot(case.staging, origin=case.origin, rows=[row], revision=revision)
    meta = {"schema_version": 1, "revision": revision,
            "source_commit": case.origin["source_commit"], "trees": case.origin["trees"],
            "windows_overlay": None, "content_sha256": envelope["content_sha256"],
            "validation_policy": ki_updates._validation_policy(),
            "publication_acceptance": envelope}
    (case.staging / ki_updates.SNAPSHOT_MANIFEST).write_text(json.dumps(meta), encoding="utf-8")
    snapshot = ki_updates.update_root() / "snapshots" / revision
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    case.staging.replace(snapshot)
    return snapshot, meta


@pytest.mark.parametrize("field,value", [("source_commit", "main"), ("source_commit", ""),
    ("archive_sha256", "not-a-hash"), ("source_content_sha256", "short")])
def test_origin_requires_exact_transport_identities(case, field, value):
    arguments = {**case.origin_args, field: value}
    with pytest.raises(ValueError):
        publication._issue_origin(case.staging, **arguments)


@pytest.mark.parametrize("folder", ["arbitrary", "snapshots/.incoming-lookalike"])
def test_official_looking_metadata_does_not_authorize_arbitrary_origin(case, folder):
    target = ki_updates.update_root() / folder
    shutil.copytree(case.staging, target)
    with pytest.raises(ValueError, match="updater staging"):
        publication._issue_origin(target, **case.origin_args)


def test_report_is_signed_scoped_and_keeps_original_package_bytes(case):
    before = ki_verification.content_digest(case.package)
    report = accepted(case)
    assert publication.require_current(case.package, report, name="Demo", origin=case.origin) == report
    assert report["state"] == "PublishedPackageAccepted"
    assert report["authoring_verification"] is False
    assert report["literature_evidence"] == "published_metadata_only"
    assert report["native_regression"]["verified"] is False
    assert report["candidate_digest"] == before == ki_verification.content_digest(case.package)
    assert ki_verification.current_report(case.package) is None
    assert not (case.package / "docs/gathered_papers.json").exists()


@pytest.mark.parametrize("what", ["origin_signature", "report_signature", "name", "commit", "profile"])
def test_changed_evidence_cannot_be_reused(case, what):
    report, origin = accepted(case), deepcopy(case.origin)
    name = "Demo"
    if what == "origin_signature":
        origin["repository"] = "someone/else"
    elif what == "report_signature":
        report["checked_at"] = 0
    elif what == "name":
        name = "Other"
    elif what == "commit":
        report["source_commit"] = "e" * 40
        report = publication._sign(case.package, report)
    else:
        report["profile_digest"] = "0" * 64
        report = publication._sign(case.package, report)
    with pytest.raises(ValueError):
        publication.require_current(case.package, report, name=name, origin=origin)


def test_changed_candidate_is_rejected_before_verification_and_after_receipt(case):
    report = accepted(case)
    case.engine.seen.clear()
    (case.package / "SKILL.md").write_text("Changed after origin capture", encoding="utf-8")
    with pytest.raises(ValueError, match="official staging origin"):
        publication.verify_candidate(case.package, name="Demo", kind="process_model", origin=case.origin)
    assert case.engine.seen == []
    with pytest.raises(ValueError, match="contents changed"):
        publication.require_current(case.package, report, name="Demo", origin=case.origin)


def test_unrelated_kdt_failure_still_blocks_publication(case):
    case.engine.ok = False
    report = publication.verify_candidate(case.package, name="Demo", kind="process_model", origin=case.origin)
    assert not report["ok"] and "fixture KDT failure" in report["failures"]
    with pytest.raises(ValueError):
        publication.require_current(case.package, report, name="Demo", origin=case.origin)


def test_overridden_engine_cannot_mint_official_publication(case, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KDT_ENGINE", str(case.root / "custom-engine"))
    with pytest.raises(ValueError, match="reviewed installed"):
        publication.verify_candidate(case.package, name="Demo", kind="process_model", origin=case.origin)
    assert not case.engine.seen


@pytest.mark.parametrize("rows", [[], [{"name": "Other", "state": "unchanged_existing",
                                      "candidate_digest": "x" * 64}],
    [{"name": "Demo", "state": "unchanged_existing", "candidate_digest": "x" * 64}]])
def test_snapshot_requires_complete_exact_package_bindings(case, rows):
    with pytest.raises(ValueError):
        publication._seal_snapshot(case.staging, origin=case.origin, rows=rows, revision="b" * 32)


@pytest.mark.parametrize("change", ["source_commit", "trees", "overlay", "signature", "contents"])
def test_signed_snapshot_rejects_changed_provenance_or_contents(case, change):
    root, meta = managed_snapshot(case)
    assert publication.require_snapshot(root, meta)
    if change == "source_commit":
        meta["source_commit"] = "e" * 40
    elif change == "trees":
        meta["trees"] = {**meta["trees"], "models": "f" * 40}
    elif change == "overlay":
        meta["windows_overlay"] = {"files": [{"path": "fabricated"}]}
    elif change == "signature":
        meta["publication_acceptance"]["checked_at"] = 0
    else:
        (root / "models/Demo/SKILL.md").write_text("Unreviewed edit", encoding="utf-8")
    with pytest.raises(ValueError):
        publication.require_snapshot(root, meta)


def test_managed_snapshot_enrolls_without_creating_authoring_acceptance(case):
    root, _meta = managed_snapshot(case)
    assert ki_updates._snapshot_valid(root)
    result = ki_guard.enroll_catalogue(Catalog(root / "models"))
    assert result["enrolled"] == ["Demo"] and not result["errors"], result
    ki_guard.require_intact(root / "models/Demo")
    assert ki_verification.current_report(root / "models/Demo") is None
    (root / "models/Demo/SKILL.md").write_text("Unreviewed local edit", encoding="utf-8")
    assert "Demo" in ki_guard.enroll_catalogue(Catalog(root / "models"))["errors"]


@pytest.mark.parametrize("location", ["elsewhere", "snapshots/renamed"])
def test_copied_snapshot_receipt_cannot_authorize_other_catalogue(case, location):
    root, meta = managed_snapshot(case)
    target = ki_updates.update_root() / location
    shutil.copytree(root, target)
    with pytest.raises(ValueError):
        publication.require_snapshot(target, meta)
    result = ki_guard.enroll_catalogue(Catalog(target / "models"))
    assert "Demo" in result["errors"] and not ki_guard.is_managed(target / "models/Demo")


def test_intact_unchanged_baseline_cannot_authorize_new_snapshot(case):
    previous = case.root / "previous/models/Demo"
    shutil.copytree(case.package, previous)
    ki_guard.enroll(previous)
    baseline = ki_guard.require_intact(previous)
    row = {"name": "Demo", "state": "unchanged_existing",
           "candidate_digest": ki_verification.content_digest(case.package),
           "previous_root": str(previous), "previous_baseline": baseline}
    with pytest.raises(ValueError, match="current published KDT"):
        publication._seal_snapshot(case.staging, origin=case.origin, rows=[row], revision="b" * 32)
    assert case.engine.seen == []
    assert ki_guard.require_intact(previous) == baseline
    assert ki_verification.current_report(case.package) is None
    assert ki_verification.content_digest(previous) == row["candidate_digest"]


def test_current_snapshot_requires_actual_report_for_every_package(case):
    root, meta = managed_snapshot(case)
    envelope = publication.require_snapshot(root, meta)
    assert envelope["package_validation"] == publication.SNAPSHOT_CONTRACT
    assert len(envelope["packages"]) == len(envelope["origin"]["packages"]) == 1
    row = envelope["packages"][0]
    assert row["state"] == "PublishedPackageAccepted" and row["report"]["ok"] is True
    assert publication.require_current(root / "models/Demo", row["report"], name="Demo", origin=envelope["origin"])
    assert row["report"]["native_regression"]["verified"] is False


@pytest.mark.parametrize("change", ["legacy_row", "missing_report", "missing_row", "duplicate_row",
                                    "wrong_digest", "stale_report", "missing_contract", "old_policy"])
def test_even_signed_snapshot_cannot_bypass_all_package_validation(case, change):
    root, meta = managed_snapshot(case)
    before = ki_verification.content_digest(root / "models/Demo")
    envelope = deepcopy(meta["publication_acceptance"])
    row = envelope["packages"][0]
    if change == "legacy_row":
        row["state"] = "unchanged_existing"
        row.pop("report")
    elif change == "missing_report":
        row.pop("report")
    elif change == "missing_row":
        envelope["packages"] = []
    elif change == "duplicate_row":
        envelope["packages"].append(deepcopy(row))
    elif change == "wrong_digest":
        row["candidate_digest"] = "0" * 64
    elif change == "stale_report":
        row["report"]["profile_digest"] = "0" * 64
        row["report"] = publication._sign(root, row["report"])
    elif change == "missing_contract":
        envelope.pop("package_validation")
    else:
        envelope["policy"] = "official-published-ki-v1"
    meta["publication_acceptance"] = publication._sign(root, envelope)
    (root / ki_updates.SNAPSHOT_MANIFEST).write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(ValueError):
        publication.require_snapshot(root, meta)
    assert not ki_updates._snapshot_valid(root)
    assert publication.catalogue_bindings(Catalog(root / "models")) == {}
    assert ki_verification.content_digest(root / "models/Demo") == before


def test_exact_old_report_is_not_rebound_to_new_official_origin(case):
    report = accepted(case)
    new_origin = publication._issue_origin(case.staging,
        **{**case.origin_args, "source_commit": "e" * 40})
    with pytest.raises(ValueError, match="evidence contract changed"):
        publication.require_current(case.package, report, name="Demo", origin=new_origin)
    row = {"name": "Demo", "state": "PublishedPackageAccepted", "report": report,
           "candidate_digest": report["candidate_digest"]}
    with pytest.raises(ValueError):
        publication._seal_snapshot(case.staging, origin=new_origin, rows=[row], revision="b" * 32)


@pytest.mark.parametrize("damage", ["missing_baseline", "prior_edit", "false_baseline"])
def test_unchanged_package_requires_real_intact_previous_baseline(case, damage):
    previous = case.root / "previous/models/Demo"
    shutil.copytree(case.package, previous)
    baseline = {"digest": ki_verification.content_digest(previous)}
    if damage != "missing_baseline":
        ki_guard.enroll(previous)
        baseline = ki_guard.require_intact(previous)
    if damage == "prior_edit":
        (previous / "SKILL.md").write_text("Unreviewed source edit", encoding="utf-8")
    elif damage == "false_baseline":
        baseline = {**baseline, "digest": "e" * 64}
    row = {"name": "Demo", "state": "unchanged_existing",
           "candidate_digest": ki_verification.content_digest(case.package),
           "previous_root": str(previous), "previous_baseline": baseline}
    with pytest.raises((ValueError, ki_guard.KIIntegrityError)):
        publication._seal_snapshot(case.staging, origin=case.origin, rows=[row], revision="b" * 32)


@pytest.mark.parametrize("damage", ["receipt", "receipt_and_policy", "marker"])
def test_removing_publication_metadata_cannot_downgrade_to_unsigned_cache(case, damage):
    root, meta = managed_snapshot(case)
    # Deliberately use the old state shape as well: neither the state file nor
    # missing policy metadata may select a weaker snapshot validator.
    (ki_updates.update_root() / "state.json").write_text(json.dumps({
        "active_snapshot": root.name, "revision": root.name}), encoding="utf-8")
    assert ki_updates.active_library_root() == root
    marker = root / ki_updates.SNAPSHOT_MANIFEST
    if damage == "marker":
        marker.unlink()
    else:
        meta.pop("publication_acceptance")
        if damage == "receipt_and_policy":
            meta.pop("validation_policy")
        marker.write_text(json.dumps(meta), encoding="utf-8")
    assert not ki_updates._snapshot_valid(root)
    assert ki_updates.active_library_root() is None
    assert "Demo" in ki_guard.enroll_catalogue(Catalog(root / "models"))["errors"]


@pytest.mark.parametrize("change", ["engine", "doctor"])
def test_snapshot_requires_current_engine_and_desktop_evidence(case, monkeypatch, change):
    root, meta = managed_snapshot(case)
    assert publication.require_snapshot(root, meta)
    if change == "engine":
        monkeypatch.setattr(kdtstudio, "engine_source_digest", lambda: "e" * 64)
    else:
        monkeypatch.setattr(publication.doctor, "VALIDATION_POLICY_VERSION", "next-doctor-policy")
    with pytest.raises(ValueError, match="current signed acceptance"):
        publication.require_snapshot(root, meta)
    assert not ki_updates._snapshot_valid(root)


def test_publication_cannot_cross_authoring_registry_or_adoption(case):
    report = accepted(case)
    with pytest.raises(ValueError):
        ki_verification.require_current(case.package, report)
    registry = ki_verification._record_path(report["candidate_digest"], "process_model", True)
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps(report), encoding="utf-8")
    assert ki_verification.current_report(case.package) is None
    active = case.root / "project/models/Demo/ki"
    write_package(active, skill="# Original active KI\n")
    ki_guard.enroll(active)
    before = ki_verification.content_digest(active)
    with pytest.raises(ValueError):
        ki_guard.activate(active, case.package, report, quiescent=True)
    assert ki_verification.content_digest(active) == before


def test_studio_cannot_export_or_import_publication_only_evidence(case):
    report = accepted(case)
    job = kdtstudio.create_job(model_name="Demo", domain="hydrology", source_type="local",
                               source=str(case.package), parent=str(case.root))
    root = Path(job["root"])
    shutil.copytree(case.package, root / "candidate", dirs_exist_ok=True)
    for name in ("ki-acceptance.json", "geoforge-ki-verify.json"):
        (root / "runs" / name).write_text(json.dumps(report), encoding="utf-8")
    state = kdtstudio.job(job["id"])
    assert not state["can_export_bare"] and not state["can_import"]
    with pytest.raises(ValueError, match="verify"):
        kdtstudio.export_zip(job["id"])


def test_zip_import_still_runs_full_authoring_gate(case):
    report = accepted(case)
    registry = ki_verification._record_path(report["candidate_digest"], "process_model", True)
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps(report), encoding="utf-8")
    case.engine.ok = False
    handler, response = import_handler(case.root)
    handler._import_ki_bytes(zip_package())
    assert response["code"] == 422 and response["body"]["state"] == "Draft"
    assert "fixture KDT failure" in str(response["body"])
    assert not (handler.catalog.user_dir / "Demo").exists()


def test_repair_apply_rejects_publication_receipt_before_mutating_project(case):
    report = accepted(case)
    project = case.root / "project"
    active = project / "models/Demo/ki"
    shutil.copytree(case.package, active)
    ki_guard.enroll(active)
    job = ki_investigation.create(project, {"id": "fixture"}, {"Demo": active}, "deepseek")
    def reviewer(_role, _context, digest, _stop, _emit):
        return {"status": "completed", "summary": "Fixture review of exact context",
                "context_digest": digest, "findings": [], "tests_not_run": ["Native model"],
                "uncertainties": []}
    ki_investigation.run_reviews(project, job["id"], reviewer)
    draft = ki_investigation.create_draft(project, job["id"], "Demo")
    stored = ki_investigation._load(project, job["id"])
    stored.update(status="verified", verification={"id": "publication-only", "ok": True,
                                                   "report": report})
    ki_investigation._save(project, stored)
    before = ki_verification.content_digest(active)
    with pytest.raises(ValueError):
        ki_investigation.apply(project, job["id"], "publication-only")
    assert ki_verification.content_digest(active) == before
    assert ki_verification.content_digest(Path(draft["draft"]["path"])) == report["candidate_digest"]
    assert not ki_investigation.pending_preflight(project)["pending"]


def test_profile_change_during_verification_is_rejected_before_signing(case, monkeypatch):
    generation = {"digest": "a" * 64}
    monkeypatch.setattr(publication, "profile_digest", lambda: generation["digest"])
    original_check = ki_verification._check_candidate
    signatures = []
    original_sign = publication._sign

    def changing_check(*args, **kwargs):
        report = original_check(*args, **kwargs)
        assert report["ok"]
        generation["digest"] = "b" * 64
        return report

    def record_signature(root, report):
        signatures.append(report)
        return original_sign(root, report)

    monkeypatch.setattr(ki_verification, "_check_candidate", changing_check)
    monkeypatch.setattr(publication, "_sign", record_signature)
    before = ki_verification.content_digest(case.package)
    with pytest.raises(ValueError, match="verifier changed during verification"):
        publication.verify_candidate(case.package, name="Demo", kind="process_model",
                                     origin=case.origin)
    assert signatures == []
    assert ki_verification.content_digest(case.package) == before


@pytest.mark.parametrize("restart", [False, True], ids=["live-attempt", "updater-restart"])
def test_generic_guidance_edit_cannot_replace_saved_host_baseline(case, restart):
    from kiss_cli import ki_platform_overlay

    source = case.root / "guidance-source"
    source_ki = source / "models/Demo"
    shutil.copytree(case.package, source_ki)
    generic_text = "kiss_manifest_version: 1\nmodel: Demo\nbinary_type: ELF\n"
    generic = source / "kiss/manifests/Demo.yaml"
    generic.parent.mkdir(parents=True)
    generic.write_text(generic_text, encoding="utf-8")
    (source_ki / "kiss.windows.yaml").write_text(
        "kiss_manifest_version: 1\nmodel: Demo\nbinary_type: PE\n", encoding="utf-8")
    # Establish a real signed KI baseline before the updater captures guidance.
    # The generic recipe deliberately lives outside this enrolled KI tree.
    ki_guard.enroll(source_ki)
    source_baseline = ki_guard.require_intact(source_ki)
    manager = ki_updates.UpdateManager(source, lambda _root: None)

    def fresh_overlay(name):
        incoming = case.root / name
        shutil.copytree(case.package, incoming / "models/Demo")
        incoming_generic = incoming / "kiss/manifests/Demo.yaml"
        incoming_generic.parent.mkdir(parents=True)
        incoming_generic.write_text(generic_text, encoding="utf-8")
        return ki_platform_overlay.apply_windows_overlay(
            source, incoming, platform="windows", architecture="x86_64",
            upstream_commit="d" * 40, source_identity="fixture-host-guidance")

    first_overlay = fresh_overlay("first-overlay")
    assert first_overlay["files"][0]["base_generic"]["path"] == "kiss/manifests/Demo.yaml"
    manager._check_overlay_source(first_overlay)
    saved = first_overlay["host_source"]["baseline"]
    assert publication._authentic(source, saved)
    assert "kiss/manifests/Demo.yaml" in saved["files"]
    baseline_files = list((publication._authority(source) / "guidance").glob("*.json"))
    assert len(baseline_files) == 1
    baseline_bytes = baseline_files[0].read_bytes()

    generic.write_text(generic_text + "# changed after host baseline capture\n", encoding="utf-8")
    assert ki_guard.require_intact(source_ki) == source_baseline
    if restart:
        manager = ki_updates.UpdateManager(source, lambda _root: None)
        assert manager._overlay_source_files != saved["files"]
    next_overlay = fresh_overlay("next-overlay")
    expected = "signed host baseline" if restart else "changed during this update attempt"
    with pytest.raises(ValueError, match=expected):
        manager._check_overlay_source(next_overlay)
    # A fresh in-memory inventory must not overwrite the persisted authority.
    assert baseline_files[0].read_bytes() == baseline_bytes
    assert "host_source" not in next_overlay
