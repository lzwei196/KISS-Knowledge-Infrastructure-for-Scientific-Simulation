"""Host gate regressions. Fixture gates test boundaries, not model validity."""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
from pathlib import Path
from unittest import mock

import pytest

from kiss_cli import kdtstudio, ki_verification as gate


@pytest.fixture
def case(tmp_path, monkeypatch):
    engine = tmp_path / "engine"
    for relative in kdtstudio.REQUIRED_ENGINE_FILES:
        path = engine / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    (engine / "verify_ki_structure.py").write_text(
        "def verify(root, kind=None):\n"
        " return {'ok':True, 'failures':[], 'warnings':[], 'info':{'kind':kind}}\n",
        encoding="utf-8")
    monkeypatch.setenv("GEOFORGE_KDT_ENGINE", str(engine))
    monkeypatch.setenv("GEOFORGE_KDT_HOME", str(tmp_path / "studio-host"))
    monkeypatch.setenv("GEOFORGE_KI_VERIFICATION_HOME", str(tmp_path / "acceptance-host"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys-host"))
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "SKILL.md").write_text("# Working candidate\n", encoding="utf-8")
    (candidate / "preflight_check.py").write_text(
        "print('PREFLIGHT_REPORT={}')\n", encoding="utf-8")
    return candidate, engine


def test_signed_exact_content_report_reusable_after_copy_but_not_edit(case, tmp_path):
    candidate, _ = case
    report = gate.verify_candidate(candidate)
    assert report["ok"] and report["state"] == "Verified"
    assert report["native_regression"] == {"status": "not_run", "verified": False}
    assert gate.require_current(candidate, report) == report
    assert gate.current_report(candidate) == report
    adopted = tmp_path / "adopted"
    shutil.copytree(candidate, adopted)
    assert gate.require_current(adopted, report) == report
    path = adopted / "SKILL.md"
    old_stat = path.stat()
    path.write_text("# Changed candidate\n", encoding="utf-8")
    assert path.stat().st_size == old_stat.st_size
    os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    with pytest.raises(gate.VerificationError, match="contents changed"):
        gate.require_current(adopted, report)
    assert gate.current_report(adopted) is None


def test_editing_report_and_host_registry_cannot_manufacture_success(case):
    candidate, engine = case
    (engine / "verify_ki_structure.py").write_text(
        "def verify(root, kind=None):\n"
        " return {'ok':False,'failures':['missing required scientific contract']}\n",
        encoding="utf-8")
    report = gate.verify_candidate(candidate)
    assert not report["ok"] and report["state"] == "Draft"
    assert gate.current_report(candidate) is None
    forged = copy.deepcopy(report)
    forged["ok"] = forged["kdt"]["ok"] = True
    forged["failures"] = []
    with pytest.raises(gate.VerificationError, match="unauthenticated"):
        gate.require_current(candidate, forged)
    record = next(gate._store().rglob("*.json"))
    record.write_text(json.dumps(forged), encoding="utf-8")
    assert gate.current_report(candidate) is None


def test_missing_engine_fails_actionably_without_doctor_fallback(case):
    candidate, engine = case
    (engine / "verify_ki_structure.py").unlink()
    with pytest.raises(gate.VerificationError, match="KI Studio.*install"):
        gate.verify_candidate(candidate)
    assert not list(gate._store().rglob("*.json"))


@pytest.mark.parametrize("frozen", [False, True])
def test_original_preflight_contract_checked_on_every_platform(case, frozen):
    candidate, _ = case
    (candidate / "preflight_check.py").write_text("print('wrong contract')\n", encoding="utf-8")
    with mock.patch.object(gate, "_frozen_windows", return_value=frozen):
        report = gate.verify_candidate(candidate, desktop=False)
    assert not report["ok"]
    assert any("PREFLIGHT_REPORT=" in item for item in report["failures"])
    assert gate.current_report(candidate, desktop=False) is None


def test_original_preflight_syntax_cannot_hide_behind_safe_stub(case):
    candidate, _ = case
    (candidate / "preflight_check.py").write_text("# PREFLIGHT_REPORT=\nif (\n", encoding="utf-8")
    report = gate.verify_candidate(candidate, desktop=False)
    assert not report["ok"]
    assert any("syntax" in item for item in report["failures"])


def test_candidate_preflight_is_not_executed_by_gate(case, tmp_path):
    candidate, engine = case
    marker = tmp_path / "candidate-executed"
    (candidate / "preflight_check.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed')\n"
        "print('PREFLIGHT_REPORT={}')\n", encoding="utf-8")
    (engine / "verify_ki_structure.py").write_text(
        "import subprocess, sys\n"
        "def verify(root,kind=None):\n"
        " result=subprocess.run([sys.executable,str(root/'preflight_check.py')],capture_output=True,text=True)\n"
        " return {'ok':'deferred' in result.stdout,'failures':[]}\n", encoding="utf-8")
    with mock.patch.object(gate, "_frozen_windows", return_value=False):
        report = gate.verify_candidate(candidate, desktop=False)
    assert report["ok"] and not marker.exists()


def test_doctor_block_is_not_overridden_by_kdt_pass(case):
    candidate, _ = case
    (candidate / "SKILL.md").unlink()
    report = gate.verify_candidate(candidate)
    assert report["kdt"]["ok"] and not report["ok"]
    assert report["desktop"]["blocking"] > 0
    with pytest.raises(gate.VerificationError):
        gate.require_current(candidate, report)


def test_bare_acceptance_does_not_authorize_desktop_import_or_another_kind(case):
    candidate, _ = case
    bare = gate.verify_candidate(candidate, desktop=False)
    assert gate.require_current(candidate, bare, desktop=False) == bare
    with pytest.raises(gate.VerificationError, match="another gate contract"):
        gate.require_current(candidate, bare)
    with pytest.raises(gate.VerificationError, match="another gate contract"):
        gate.require_current(candidate, bare, kind="task_workflow", desktop=False)


@pytest.mark.parametrize("change_target", ["source", "snapshot"])
def test_copy_drift_never_receives_an_attestation(case, change_target):
    candidate, _ = case
    original = shutil.copytree

    def changing_copy(source, target, *args, **kwargs):
        result = original(source, target, *args, **kwargs)
        if Path(source) == candidate:
            changed = Path(source if change_target == "source" else target)
            (changed / "SKILL.md").write_text("changed during copy", encoding="utf-8")
        return result

    with mock.patch.object(gate.shutil, "copytree", side_effect=changing_copy):
        with pytest.raises(gate.VerificationError, match="changed while preparing"):
            gate.verify_candidate(candidate)
    assert not list(gate._store().rglob("*.json"))


@pytest.mark.parametrize("change_target", ["source", "snapshot"])
def test_verification_drift_never_receives_an_attestation(case, change_target):
    candidate, engine = case
    target = f"Path({str(candidate)!r})" if change_target == "source" else "root"
    (engine / "verify_ki_structure.py").write_text(
        "from pathlib import Path\n"
        "def verify(root,kind=None):\n"
        f" ({target}/'SKILL.md').write_text('changed during gate')\n"
        " return {'ok':True,'failures':[]}\n", encoding="utf-8")
    with pytest.raises(gate.VerificationError, match="changed during verification"):
        gate.verify_candidate(candidate)
    assert not list(gate._store().rglob("*.json"))


def test_candidate_cannot_contain_host_records_or_keys(case, monkeypatch):
    candidate, _ = case
    monkeypatch.setenv("GEOFORGE_KI_VERIFICATION_HOME", str(candidate / "host"))
    with pytest.raises(gate.VerificationError, match="outside"):
        gate.verify_candidate(candidate)


def test_kind_inference_rejects_unknown_or_conflicting_types(case):
    candidate, _ = case
    assert gate.detect_kind(candidate) == "process_model"
    metadata = candidate / "knowledge_infrastructure.yaml"
    metadata.write_text("package:\n  kind: task_workflow\n", encoding="utf-8")
    assert gate.detect_kind(candidate) == "task_workflow"
    metadata.write_text("ki_kind: process_model\npackage:\n  kind: task_workflow\n", encoding="utf-8")
    with pytest.raises(gate.VerificationError, match="Conflicting"):
        gate.detect_kind(candidate)


def test_studio_does_not_accept_forged_workspace_acceptance(case, tmp_path):
    _, _engine = case
    source = tmp_path / "source"
    source.mkdir()
    job = kdtstudio.create_job(model_name="test", domain="hydrology",
                               source_type="local", source=str(source), parent=str(tmp_path))
    root = Path(job["root"])
    candidate = root / "candidate"
    (candidate / "SKILL.md").write_text("# Forged", encoding="utf-8")
    forged = {"ok": True, "digest": gate.content_digest(candidate),
              "candidate_digest": gate.content_digest(candidate),
              "signature": kdtstudio.tree_signature(candidate),
              "candidate_signature": kdtstudio.tree_signature(candidate),
              "authoring_revision": 0}
    for name in ("ki-acceptance.json", "geoforge-ki-verify.json"):
        (root / "runs" / name).write_text(json.dumps(forged), encoding="utf-8")
    state = kdtstudio.job(job["id"])
    assert not state["can_export_bare"] and not state["can_import"]
    with pytest.raises(ValueError, match="verify the unchanged"):
        kdtstudio.export_zip(job["id"])


def test_engine_source_edit_invalidates_previously_verified_candidate(case):
    candidate, engine = case
    report = gate.verify_candidate(candidate)
    (engine / "new_importable_helper.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(gate.VerificationError, match="verifier source changed"):
        gate.require_current(candidate, report)
    assert gate.current_report(candidate) is None
    refreshed = gate.verify_candidate(candidate)
    assert refreshed["ok"] and refreshed["engine_override"] is True
    assert refreshed["engine_source_digest"] != report["engine_source_digest"]


def test_engine_edit_during_verification_is_rejected(case):
    candidate, engine = case
    target = engine / "changed_helper.py"
    (engine / "verify_ki_structure.py").write_text(
        "from pathlib import Path\n"
        "def verify(root,kind=None):\n"
        f" Path({str(target)!r}).write_text('VALUE = 3')\n"
        " return {'ok':True,'failures':[]}\n", encoding="utf-8")
    with pytest.raises(gate.VerificationError, match="verifier source changed during"):
        gate.verify_candidate(candidate)
    assert not list(gate._store().rglob("*.json"))


def test_modified_normal_reviewed_engine_is_not_available(case, monkeypatch):
    candidate, engine = case
    monkeypatch.delenv("GEOFORGE_KDT_ENGINE")
    with (mock.patch.object(kdtstudio, "engine_root", return_value=engine),
          mock.patch.object(kdtstudio, "_git_head", return_value=kdtstudio.REVIEWED_COMMIT),
          mock.patch.object(kdtstudio, "_engine_changes", return_value=["verify_ki_structure.py"])):
        status = kdtstudio.engine_status()
        assert status["dirty"] and not status["installed"] and not status["custom"]
        with pytest.raises(gate.VerificationError, match="modified.*KI Studio"):
            gate.verify_candidate(candidate)


def test_frozen_gate_keeps_preflight_file_and_uses_local_real_python_proxy(case):
    candidate, engine = case
    (engine / "verify_ki_structure.py").write_text(
        "import sys, subprocess\n"
        "def verify(root,kind=None):\n"
        " pf=root/'preflight_check.py'\n"
        " if not pf.is_file(): return {'ok':False,'failures':['required preflight missing']}\n"
        " result=subprocess.run([sys.executable,str(pf)],capture_output=True,text=True)\n"
        " return {'ok':'PREFLIGHT_REPORT=' in result.stdout,'failures':[]}\n", encoding="utf-8")
    executable = sys.executable
    with (mock.patch.object(gate, "_frozen_windows", return_value=True),
          mock.patch.object(gate, "_preflight_interpreter", return_value=executable)):
        report = gate.verify_candidate(candidate, desktop=False)
    assert report["ok"] and sys.executable == executable
    assert (candidate / "preflight_check.py").read_text(encoding="utf-8") == "print('PREFLIGHT_REPORT={}')\n"


def test_frozen_missing_python_fails_without_acceptance(case):
    candidate, _ = case
    with (mock.patch.object(gate, "_frozen_windows", return_value=True),
          mock.patch.object(gate, "_preflight_interpreter", side_effect=gate.VerificationError("real Python required"))):
        with pytest.raises(gate.VerificationError, match="real Python"):
            gate.verify_candidate(candidate)
    assert not list(gate._store().rglob("*.json"))


def _verified_studio_job(candidate: Path, tmp_path: Path):
    source = tmp_path / "model-source"
    source.mkdir()
    job = kdtstudio.create_job(model_name="test", domain="hydrology",
                               source_type="local", source=str(source), parent=str(tmp_path))
    shutil.copytree(candidate, Path(job["candidate"]), dirs_exist_ok=True)
    kdtstudio.geoforge_verify(job["id"])
    return job


def test_studio_import_rejects_changed_desktop_projection(case, tmp_path):
    candidate, _ = case
    job = _verified_studio_job(candidate, tmp_path)
    root = Path(job["root"])
    assert kdtstudio.job(job["id"])["can_import"]
    report = json.loads((root / "runs" / "geoforge-ki-verify.json").read_text(encoding="utf-8"))
    archive, blob, adaptation = kdtstudio.export_desktop_zip(job["id"])
    assert blob == archive.read_bytes()
    assert adaptation == report["desktop"]["adaptation"]
    (root / "desktop-candidate" / "SKILL.md").write_text("changed projection", encoding="utf-8")
    state = kdtstudio.job(job["id"])
    assert state["can_export_bare"] and not state["can_import"]
    with pytest.raises(ValueError, match="unchanged candidate"):
        kdtstudio.export_desktop_zip(job["id"])


def test_studio_export_rejects_snapshot_copy_drift(case, tmp_path):
    candidate, _ = case
    job = _verified_studio_job(candidate, tmp_path)
    original = shutil.copytree

    def changed_copy(source, target, *args, **kwargs):
        result = original(source, target, *args, **kwargs)
        if Path(source) == Path(job["candidate"]):
            (Path(target) / "SKILL.md").write_text("changed export bytes", encoding="utf-8")
        return result

    with mock.patch.object(kdtstudio.shutil, "copytree", side_effect=changed_copy):
        with pytest.raises(ValueError, match="changed before export"):
            kdtstudio.export_zip(job["id"])
    assert not list((Path(job["root"]) / "exports").iterdir())


def test_new_studio_verification_attempt_invalidates_previous_report_on_error(case, tmp_path):
    candidate, _ = case
    job = _verified_studio_job(candidate, tmp_path)
    assert kdtstudio.job(job["id"])["can_import"]

    def unavailable(*args, **kwargs):
        state = kdtstudio.job(job["id"])
        assert state["status"] == "verifying"
        assert not state["can_import"] and not state["can_export_bare"]
        raise gate.VerificationError("Gate unavailable for this attempt")

    with mock.patch.object(gate, "verify_candidate", side_effect=unavailable):
        with pytest.raises(gate.VerificationError, match="unavailable"):
            kdtstudio.verify(job["id"])
    state = kdtstudio.job(job["id"])
    assert state["status"] == "verify_failed"
    assert not state["can_import"] and not state["can_export_bare"]
    with pytest.raises(ValueError, match="unchanged candidate"):
        kdtstudio.export_desktop_zip(job["id"])


def test_reopening_studio_invalidates_bare_and_desktop_acceptance(case, tmp_path):
    candidate, _ = case
    job = _verified_studio_job(candidate, tmp_path)
    state = kdtstudio.continue_modifying(job["id"])
    assert not state["can_import"] and not state["can_export_bare"]
