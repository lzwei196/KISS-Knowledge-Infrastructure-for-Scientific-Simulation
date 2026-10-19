"""Retained preflight observations never become present-day readiness."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from kiss_cli import install, ki_guard, runtime_provenance
from kiss_cli import project_verification as pv
from .test_project_verification import case, _passing  # noqa: F401


def context(digest="a", version="0.6.60"):
    return {"schema_version": 1, "application": {
        "name": "GeoForge", "version": version,
        "version_source": "source-project-metadata",
        "build": {"scheme": "python-application-tree-sha256-v1", "sha256": digest * 64}},
        "backend": {"kind": "native", "platform": "Windows", "machine": "AMD64"}}


@pytest.fixture
def observed(monkeypatch):
    value = context()
    monkeypatch.setattr(runtime_provenance, "capture", lambda: deepcopy(value))
    return value


def current_bytes(project, model):
    return ki_guard._io(pv._receipt_path(project, model)).read_bytes()


def save_signed(project, model, doc):
    sealed = pv._receipts().sign(project, deepcopy(doc))
    raw = (json.dumps(sealed, indent=2, ensure_ascii=False) + "\n").encode()
    ki_guard._io(pv._receipt_path(project, model)).write_bytes(raw)
    return raw


def tree_state(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file()}


def forbidden(*_a, **_kw):
    pytest.fail("Historical observation read invoked a check, writer or current-build capture")


def test_two_builds_preserve_exact_old_signed_receipt_without_changing_gate(case, observed, monkeypatch):
    project, ki, man, cfg, _config = case
    _passing(monkeypatch)
    first = pv.verify(project, ki, man)
    assert first["ok"] and first["receipt"]["verification_context"] == context()
    raw = current_bytes(project, ki.name)
    observed.update(context("b"))
    second = pv.verify(project, ki, man)
    assert second["ok"]
    retained = pv._history_dir(project, ki.name) / (hashlib.sha256(raw).hexdigest() + ".json")
    assert ki_guard._io(retained).read_bytes() == raw
    result = pv.history(project, ki.name)
    verified = [row for row in result["records"] if row.get("state") == "verified"]
    assert len(verified) == 2
    assert {row["verification_context"]["application"]["build"]["sha256"] for row in verified} == {"a" * 64, "b" * 64}
    assert all(row["authentication"] == "verified" for row in verified)
    assert result["historical"] and result["complete_history"] is False
    assert result["readiness_rechecked"] is False and result["scope"] == "project_preflight"
    # Observational additions do not become a new dispatch/readiness identity.
    observed.update(context("c"))
    assert pv.status(project, ki, man)["can_run"]
    pv.require_current(project, ki.name, ki.root, cfg=cfg)
    cfg.python = "different-runtime"
    with pytest.raises(ValueError, match="launch configuration"):
        pv.require_current(project, ki.name, ki.root, cfg=cfg)


def test_legacy_receipt_stays_unknown_and_exact_bytes_are_archived(case, observed, monkeypatch):
    project, ki, man, _cfg, _config = case
    _passing(monkeypatch)
    doc = pv.verify(project, ki, man)["receipt"]
    doc.pop("verification_context")
    raw = save_signed(project, ki.name, doc)
    result = pv.history(project, ki.name)
    legacy = next(row for row in result["records"] if row["location"] == "current")
    assert legacy["provenance"] == "legacy_unknown" and legacy["verification_context"] is None
    assert current_bytes(project, ki.name) == raw
    observed.update(context("b"))
    assert pv.verify(project, ki, man)["ok"]
    assert ki_guard._io(pv._history_dir(project, ki.name) / (hashlib.sha256(raw).hexdigest() + ".json")).read_bytes() == raw
    old = next(row for row in pv.history(project, ki.name)["records"] if row["receipt_sha256"] == hashlib.sha256(raw).hexdigest())
    assert old["provenance"] == "legacy_unknown" and old["verification_context"] is None


def test_history_reads_do_not_probe_capture_sign_or_rewrite(case, observed, monkeypatch):
    project, ki, man, _cfg, _config = case
    _passing(monkeypatch)
    assert pv.verify(project, ki, man)["ok"]
    before = tree_state(project)
    monkeypatch.setattr(runtime_provenance, "capture", forbidden)
    monkeypatch.setattr(pv, "_identity", forbidden)
    monkeypatch.setattr(pv, "_config", forbidden)
    monkeypatch.setattr(pv._receipts(), "sign", forbidden)
    monkeypatch.setattr(install, "run_preflight", forbidden)
    assert pv.history(project, ki.name)["records"]
    assert tree_state(project) == before


def test_missing_history_creates_no_project_or_signing_key(tmp_path, monkeypatch):
    project, keys = tmp_path / "absent-project", tmp_path / "absent-keys"
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(keys))
    monkeypatch.setattr(runtime_provenance, "capture", forbidden)
    result = pv.history(project, "Demo")
    assert result["records"] == [] and result["invalid_count"] == 0
    assert not project.exists() and not keys.exists()


@pytest.mark.parametrize("change", ["signature", "project", "model", "ki_root"])
def test_history_rejects_tamper_and_wrong_binding(case, observed, monkeypatch, change):
    project, ki, man, _cfg, _config = case
    _passing(monkeypatch)
    doc = pv.verify(project, ki, man)["receipt"]
    if change == "signature":
        doc["state"] = "cancelled"
        ki_guard._io(pv._receipt_path(project, ki.name)).write_text(json.dumps(doc), encoding="utf-8")
    else:
        doc[change] = "different-binding"
        save_signed(project, ki.name, doc)
    result = pv.history(project, ki.name)
    assert result["invalid_count"] == 1
    assert not any(row["location"] == "current" for row in result["records"])


def test_present_invalid_signed_context_is_not_legacy_or_trusted_facts(case, observed, monkeypatch):
    project, ki, man, _cfg, _config = case
    _passing(monkeypatch)
    doc = pv.verify(project, ki, man)["receipt"]
    doc["verification_context"] = {"application": {"build": "claim"}}
    save_signed(project, ki.name, doc)
    row = next(row for row in pv.history(project, ki.name)["records"] if row["location"] == "current")
    assert row["provenance"] == "invalid" and row["verification_context"] is None
    assert row["authentication"] == "verified"
    assert not {"attempt_id", "state", "started_at", "checked_at"}.intersection(row)


def test_missing_key_never_regenerates_key_or_authenticates_history(case, observed, monkeypatch):
    project, ki, man, _cfg, _config = case
    _passing(monkeypatch)
    assert pv.verify(project, ki, man)["ok"]
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(project.parent / "no-key"))
    result = pv.history(project, ki.name)
    assert result["records"] == [] and result["invalid_count"] >= 1
    assert not (project.parent / "no-key").exists()


def test_archive_write_failure_keeps_previous_current_receipt(case, observed, monkeypatch):
    project, ki, man, _cfg, _config = case
    _passing(monkeypatch)
    assert pv.verify(project, ki, man)["ok"]
    raw = current_bytes(project, ki.name)
    original = Path.open
    def fail_archive(path, mode="r", *args, **kwargs):
        if mode == "xb" and path.parent.parent.name == "history":
            raise OSError("fixture history storage unavailable")
        return original(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", fail_archive)
    with pytest.raises(OSError, match="history storage unavailable"):
        pv.verify(project, ki, man)
    assert current_bytes(project, ki.name) == raw


def test_existing_archive_cannot_be_silently_replaced(case, observed, monkeypatch):
    project, ki, man, _cfg, _config = case
    _passing(monkeypatch)
    assert pv.verify(project, ki, man)["ok"]
    raw = current_bytes(project, ki.name)
    archive = ki_guard._io(pv._history_dir(project, ki.name) / (hashlib.sha256(raw).hexdigest() + ".json"))
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="history was modified"):
        pv.verify(project, ki, man)
    assert current_bytes(project, ki.name) == raw and archive.read_bytes() == b"tampered"


def test_start_context_retained_and_midcheck_drift_cannot_pass(case, observed, monkeypatch):
    project, ki, man, _cfg, _config = case
    def check(*_a, **_kw):
        pending = json.loads(current_bytes(project, ki.name))
        assert pending["state"] == "pending" and pending["verification_context"] == context()
        observed.update(context("b"))
        return install.Step("preflight", True, "fixture")
    monkeypatch.setattr(install, "run_preflight", check)
    result = pv.verify(project, ki, man)
    assert result["state"] == "failed" and not result["can_run"]
    assert result["receipt"]["verification_context"] == context()


@pytest.mark.parametrize("limit", [0, 33, True, "8"])
def test_history_limit_is_bounded(tmp_path, limit):
    with pytest.raises(ValueError, match="between 1 and 32"):
        pv.history(tmp_path / "absent", "Demo", limit=limit)


def test_history_byte_and_entry_limits_are_explicit(case, observed, monkeypatch):
    project, ki, man, _cfg, _config = case
    _passing(monkeypatch)
    assert pv.verify(project, ki, man)["ok"]
    monkeypatch.setattr(pv, "_MAX_HISTORY_BYTES", 1)
    result = pv.history(project, ki.name)
    assert result["truncated"] and result["records"] == []
    monkeypatch.setattr(pv, "_MAX_HISTORY_BYTES", 16 * 1024 * 1024)
    monkeypatch.setattr(pv, "_MAX_HISTORY_FILES", 0)
    assert pv.history(project, ki.name)["truncated"]


@pytest.mark.parametrize("current_time", [1, 100])
def test_current_cancelled_observation_survives_clock_rollback_and_history_limit(case, observed, monkeypatch, current_time):
    project, ki, man, _cfg, _config = case
    _passing(monkeypatch)
    doc = pv.verify(project, ki, man)["receipt"]
    # More historical passes than the ordinary display limit, each with a
    # later or equal wall-clock timestamp. They cannot displace the pointer.
    for index in range(9):
        doc.update(attempt_id=f"historical-pass-{index}", started_at=100,
                   checked_at=100, state="verified", ok=True)
        pv._write(project, ki.name, doc)
    doc.update(attempt_id="current-cancelled", started_at=current_time,
               checked_at=current_time, state="cancelled", ok=False)
    pv._write(project, ki.name, doc)
    result = pv.history(project, ki.name)
    assert result["truncated"] and len(result["records"]) == 8
    current = result["records"][0]
    assert current["location"] == "current" and current["state"] == "cancelled"
    assert current["attempt_id"] == "current-cancelled"
    assert current["checked_at"] == current_time
    assert pv.history(project, ki.name, limit=1)["records"] == [current]


def test_linked_history_record_cannot_supply_an_observation(case, observed, monkeypatch):
    project, ki, man, _cfg, _config = case
    _passing(monkeypatch)
    assert pv.verify(project, ki, man)["ok"]
    archive = next(pv._history_dir(project, ki.name).glob("*.json"))
    import os
    os.link(archive, project / "linked-receipt.json")
    result = pv.history(project, ki.name)
    assert result["invalid_count"] == 1
    assert not any(row["receipt_sha256"] == archive.stem for row in result["records"])
