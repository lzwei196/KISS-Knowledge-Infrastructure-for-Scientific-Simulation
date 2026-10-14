"""An intact old KI is integrity evidence, never new publication acceptance.

KDT's structural result is an explicit fixture. Official origins, package
hashes, signed reports, baseline integrity and snapshot seals remain real.
"""
from __future__ import annotations

import json
import shutil
from types import SimpleNamespace

import pytest

from kiss_cli import doctor, kdtstudio, ki_guard, ki_updates, ki_verification
from kiss_cli import published_acceptance as publication
from .test_ki_verification_boundaries import isolated_engine, write_package


def origin(root):
    return publication._issue_origin(root, source_commit="d" * 40,
        archive_sha256="a" * 64, source_content_sha256=ki_updates._snapshot_content_hash(root),
        overlay=None, trees={"models": "1" * 40, "manifests": "2" * 40,
                            "shared_tools": "3" * 40, "data_kis": None})


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_UPDATE_HOME", str(tmp_path / "updates"))
    monkeypatch.delenv("GEOFORGE_KDT_ENGINE", raising=False)
    with isolated_engine(tmp_path) as engine:
        previous = tmp_path / "previous"
        package = previous / "models/Demo"
        write_package(package)
        common = previous / "ki_tools_common"
        (common / "ki_tools_common").mkdir(parents=True)
        (common / "ki_tools_common/__init__.py").write_text("VALUE = 1\n")
        (common / "pyproject.toml").write_text('[project]\nname="ki_tools_common"\nversion="0.1.0"\n')
        ki_guard.enroll(package)
        incoming = ki_updates.update_root() / ".incoming-next"
        shutil.copytree(previous, incoming)
        manager = ki_updates.UpdateManager(previous, lambda _: pytest.fail("Direct validation activated a library"))
        manager._published_origin = origin(incoming)
        # Progress transport has independent integration coverage. Capture the
        # callbacks here without obscuring publication/integrity failures.
        progress = []
        monkeypatch.setattr(manager, "_progress", lambda stage, **values: progress.append((stage, values)), raising=False)
        yield SimpleNamespace(root=tmp_path, previous=previous, package=package,
                              incoming=incoming, manager=manager, engine=engine,
                              progress=progress, monkeypatch=monkeypatch)


def current_published_previous(c):
    staging = ki_updates.update_root() / ".incoming-previous"
    shutil.copytree(c.previous, staging)
    previous_origin = origin(staging)
    report = publication.verify_candidate(staging / "models/Demo", name="Demo",
                                         kind="process_model", origin=previous_origin)
    row = {"name": "Demo", "state": "PublishedPackageAccepted",
           "candidate_digest": report["candidate_digest"], "report": report}
    revision = "b" * 32
    envelope = publication._seal_snapshot(staging, origin=previous_origin, rows=[row], revision=revision)
    meta = {"schema_version": 1, "revision": revision,
        "source_commit": previous_origin["source_commit"], "trees": previous_origin["trees"],
        "windows_overlay": None, "content_sha256": envelope["content_sha256"],
        "publication_acceptance": envelope, "validation_policy": ki_updates._validation_policy()}
    (staging / ki_updates.SNAPSHOT_MANIFEST).write_text(json.dumps(meta), encoding="utf-8")
    snapshot = ki_updates.update_root() / "snapshots" / revision
    snapshot.parent.mkdir(parents=True)
    staging.replace(snapshot)
    publication.require_snapshot(snapshot, meta)
    ki_guard.enroll(snapshot / "models/Demo")
    c.manager.current_library_root = snapshot
    c.engine.seen.clear()
    return snapshot, meta, report


@pytest.mark.parametrize("missing_engine", [False, True])
def test_legacy_integrity_baseline_cannot_skip_current_package_gate(case, missing_engine):
    c = case
    baseline = ki_guard.require_intact(c.package)
    c.engine.installed = not missing_engine
    c.engine.ok = False
    with pytest.raises(ki_updates.SnapshotValidationError, match="published KDT verification required"):
        c.manager._validate(c.incoming)
    row, = c.manager._ki_verification
    assert row["state"] == "PublicationRejected"
    assert "report" in row and "previous_baseline" not in row
    assert ki_guard.require_intact(c.package) == baseline
    assert not hasattr(c.manager, "_validated_content_hash")


def test_equal_bytes_receive_fresh_current_report_and_complete_snapshot_seal(case):
    c = case
    baseline = ki_guard.require_intact(c.package)
    assert c.manager._validate(c.incoming)[0] == 1
    assert len(c.engine.seen) == 1
    row, = c.manager._ki_verification
    assert row["state"] == "PublishedPackageAccepted"
    publication.require_current(c.incoming / "models/Demo", row["report"],
                                name="Demo", origin=c.manager._published_origin)
    envelope = publication._seal_snapshot(c.incoming, origin=c.manager._published_origin,
                                         rows=c.manager._ki_verification, revision="a" * 32)
    assert envelope["packages"][0]["report"] == row["report"]
    assert row["report"]["native_regression"]["verified"] is False
    assert ki_guard.require_intact(c.package) == baseline


def test_even_current_previous_publication_is_freshly_bound_to_new_origin(case):
    c = case
    snapshot, meta, old_report = current_published_previous(c)
    original = ki_updates._snapshot_content_hash(snapshot)
    c.manager._validate(c.incoming)
    row, = c.manager._ki_verification
    assert len(c.engine.seen) == 1 and row["state"] == "PublishedPackageAccepted"
    assert row["report"]["candidate_digest"] == old_report["candidate_digest"]
    assert row["report"]["origin_id"] != old_report["origin_id"]
    assert ki_updates._snapshot_content_hash(snapshot) == original
    publication.require_snapshot(snapshot, meta)


@pytest.mark.parametrize("changed", ["profile", "doctor", "engine"])
def test_changed_evidence_policy_rechecks_equal_bytes(case, changed):
    c = case
    snapshot, meta, old_report = current_published_previous(c)
    if changed == "profile":
        c.monkeypatch.setattr(publication, "profile_digest", lambda: "e" * 64)
        field, value = "profile_digest", "e" * 64
    elif changed == "doctor":
        c.monkeypatch.setattr(doctor, "VALIDATION_POLICY_VERSION", "fixture-new-doctor")
        field, value = "doctor_policy", "fixture-new-doctor"
    else:
        c.monkeypatch.setattr(kdtstudio, "engine_source_digest", lambda *_: "e" * 64)
        c.monkeypatch.setattr(kdtstudio, "engine_status", lambda: {
            "installed": True, "commit": kdtstudio.REVIEWED_COMMIT, "source_digest": "e" * 64})
        field, value = "engine_source_digest", "e" * 64
    with pytest.raises(ValueError):
        publication.require_snapshot(snapshot, meta)
    c.manager._validate(c.incoming)
    row, = c.manager._ki_verification
    assert len(c.engine.seen) == 1 and row["state"] == "PublishedPackageAccepted"
    assert row["report"][field] == value and old_report[field] != value
    publication.require_current(c.incoming / "models/Demo", row["report"],
                                name="Demo", origin=c.manager._published_origin)


@pytest.mark.parametrize("damage", ["source", "source_new_upstream", "baseline"])
def test_registered_integrity_failure_never_falls_back_to_fresh_validation(case, damage):
    c = case
    if damage.startswith("source"):
        (c.package / "SKILL.md").write_text("unreviewed source edit\n")
        if damage == "source_new_upstream":
            (c.incoming / "models/Demo/SKILL.md").write_text("# New official instructions\n")
            c.manager._published_origin = origin(c.incoming)
    else:
        baseline = ki_guard._entry(c.package) / "baseline.json"
        document = json.loads(baseline.read_text(encoding="utf-8"))
        document["digest"] = "0" * 64
        baseline.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ki_updates.SnapshotValidationError):
        c.manager._validate(c.incoming)
    assert c.engine.seen == []
    row, = c.manager._ki_verification
    assert row["state"] == "PublicationRejected" and row["report"] is None
    if damage.startswith("source"):
        assert (c.package / "SKILL.md").read_text() == "unreviewed source edit\n"


def test_changed_incoming_content_still_requires_and_gets_exact_fresh_evidence(case):
    c = case
    (c.incoming / "models/Demo/SKILL.md").write_text("# Official new instructions\n")
    c.manager._published_origin = origin(c.incoming)
    baseline = ki_guard.require_intact(c.package)
    c.manager._validate(c.incoming)
    row, = c.manager._ki_verification
    assert len(c.engine.seen) == 1 and row["state"] == "PublishedPackageAccepted"
    assert row["candidate_digest"] == ki_verification.content_digest(c.incoming / "models/Demo")
    assert row["candidate_digest"] != baseline["digest"]
    assert ki_guard.require_intact(c.package) == baseline
