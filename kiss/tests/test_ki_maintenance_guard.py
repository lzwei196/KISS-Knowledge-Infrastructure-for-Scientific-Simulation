"""Maintenance adoption stays separate from authoring and bound to its source."""
from pathlib import Path
import shutil

import pytest

from kiss_cli import ki_guard, ki_verification


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_GUARD_HOME", str(tmp_path / "guard"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_KI_VERIFICATION_HOME", str(tmp_path / "verification"))
    root = tmp_path / "project" / "models" / "M" / "ki"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text("source\n", encoding="utf-8")
    ki_guard.enroll(root)
    draft = tmp_path / "draft"
    shutil.copytree(root, draft)
    (draft / "SKILL.md").write_text("bounded fixture repair\n", encoding="utf-8")
    report = {"source": {"original_root": str(root), "base_digest": ki_verification.content_digest(root)},
              "candidate_digest": ki_verification.content_digest(draft)}
    return root, draft, report


def accept_fixture(monkeypatch, report):
    # This file isolates replacement mechanics. The real evidence/receipt gate
    # is exercised by test_ki_maintenance; there is no native/model execution.
    from kiss_cli import ki_maintenance
    calls = []
    def require(candidate, provided, *, source=None):
        assert provided is report
        assert ki_verification.content_digest(candidate) == report["candidate_digest"]
        calls.append(Path(candidate))
        return report
    monkeypatch.setattr(ki_maintenance, "require_current", require)
    return calls


def test_maintenance_adoption_preserves_previous_and_rechecks_receipt(case, monkeypatch):
    root, draft, report = case
    calls = accept_fixture(monkeypatch, report)
    result = ki_guard.activate_maintenance(root, draft, report, quiescent=True)
    assert len(calls) == 2
    assert result["origin"] == "verified_maintenance_candidate"
    assert result["digest"] == report["candidate_digest"]
    assert next(root.parent.glob("ki-previous-*/SKILL.md")).read_text() == "source\n"
    assert ki_guard.require_intact(root)["digest"] == report["candidate_digest"]


@pytest.mark.parametrize("mismatch", ["path", "digest"])
def test_maintenance_cannot_adopt_against_different_source(case, monkeypatch, mismatch):
    root, draft, report = case
    accept_fixture(monkeypatch, report)
    report["source"]["original_root" if mismatch == "path" else "base_digest"] = (
        str(root.parent / "other") if mismatch == "path" else "0" * 64)
    with pytest.raises(ki_guard.KIIntegrityError, match="another active KI"):
        ki_guard.activate_maintenance(root, draft, report, quiescent=True)
    assert (root / "SKILL.md").read_text() == "source\n"


def test_maintenance_requires_stopped_workers(case, monkeypatch):
    root, draft, report = case
    accept_fixture(monkeypatch, report)
    with pytest.raises(ki_guard.KIIntegrityError, match="Stop active"):
        ki_guard.activate_maintenance(root, draft, report)
    with ki_guard.worker(root), pytest.raises(ki_guard.KIIntegrityError, match="worker"):
        ki_guard.activate_maintenance(root, draft, report, quiescent=True)


def test_maintenance_report_does_not_satisfy_ordinary_authoring_adoption(case):
    root, draft, report = case
    with pytest.raises(ki_verification.VerificationError):
        ki_guard.activate(root, draft, report, quiescent=True)
    assert (root / "SKILL.md").read_text() == "source\n"


def test_source_drift_during_candidate_copy_refuses_adoption(case, monkeypatch):
    root, draft, report = case
    accept_fixture(monkeypatch, report)
    real_copy = ki_guard._copy
    def changed(source, destination):
        real_copy(source, destination)
        if Path(destination).name.startswith(".ki-adopt-"):
            (root / "SKILL.md").write_text("external edit\n", encoding="utf-8")
    monkeypatch.setattr(ki_guard, "_copy", changed)
    with pytest.raises(ki_guard.KIIntegrityError, match="another active KI"):
        ki_guard.activate_maintenance(root, draft, report, quiescent=True)
    assert (root / "SKILL.md").read_text() == "external edit\n"
