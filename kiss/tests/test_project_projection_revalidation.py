"""Only explicit project preflight may refresh exact host projection metadata.

These test the shared host hook and ordering. The projection module's real
legacy-source/byte-comparison tests establish the separate refresh boundary.
"""
import pytest

from kiss_cli import install, ki_adaptations, ki_verification, software_verification
from kiss_cli import project_verification as pv
from .test_project_verification import case, _passing


def test_refresh_occurs_after_revocation_before_preflight(case, monkeypatch):
    project, ki, manifest, cfg, config = case
    order = []
    original = ki_adaptations.refresh_project_projection
    _passing(monkeypatch)
    assert pv.verify(project, ki, manifest)["ok"]
    before = config.read_bytes(), ki_verification.content_digest(ki.root)
    def refresh(live, saved, **kwargs):
        status = pv.status(project, ki)
        assert status["state"] == "pending" and not status["can_run"]
        assert live == ki.root and saved.root == project
        assert saved.python == cfg.python and saved.roles == cfg.roles
        assert kwargs == {"model": ki.name, "manifest": manifest}
        order.append("refresh")
        return original(live, saved, **kwargs)
    def preflight(*args, **kwargs):
        assert order == ["refresh"]
        order.append("preflight")
        return install.Step("preflight", True, "fixture")
    monkeypatch.setattr(ki_adaptations, "refresh_project_projection", refresh)
    monkeypatch.setattr(install, "run_preflight", preflight)
    result = pv.verify(project, ki, manifest)
    assert result["ok"] and order == ["refresh", "preflight"]
    assert before == (config.read_bytes(), ki_verification.content_digest(ki.root))


def test_refresh_failure_blocks_before_preflight_and_cannot_retain_old_pass(case, monkeypatch):
    project, ki, manifest, _cfg, config = case
    _passing(monkeypatch)
    assert pv.verify(project, ki, manifest)["ok"]
    old = config.read_bytes()
    def reject(*args, **kwargs):
        raise ValueError("legacy source/path identity cannot be established")
    monkeypatch.setattr(ki_adaptations, "refresh_project_projection", reject)
    monkeypatch.setattr(install, "run_preflight", lambda *a, **k: pytest.fail("must not launch"))
    result = pv.verify(project, ki, manifest)
    assert result["state"] == "failed" and not result["can_run"]
    assert "legacy source/path identity" in result["detail"]
    assert config.read_bytes() == old and not pv.status(project, ki)["can_run"]


def test_read_only_status_and_dispatch_never_refresh(case, monkeypatch):
    project, ki, manifest, cfg, _config = case
    _passing(monkeypatch)
    assert pv.verify(project, ki, manifest)["ok"]
    original_receipt = pv._receipt_path(project, ki.name).read_bytes()
    monkeypatch.setattr(ki_adaptations, "refresh_project_projection",
                        lambda *a, **k: pytest.fail("ordinary reads may not refresh"))
    monkeypatch.setattr(install, "run_preflight", lambda *a, **k: pytest.fail("no preflight"))
    assert pv.status(project, ki)["can_run"]
    pv.require_current(project, ki.name, ki.root, cfg=cfg)
    assert pv._receipt_path(project, ki.name).read_bytes() == original_receipt


def test_stop_precedes_refresh_and_does_not_restore_previous_success(case, monkeypatch):
    project, ki, manifest, _cfg, _config = case
    _passing(monkeypatch)
    assert pv.verify(project, ki, manifest)["ok"]
    monkeypatch.setattr(ki_adaptations, "refresh_project_projection",
                        lambda *a, **k: pytest.fail("cancelled refresh"))
    result = pv.verify(project, ki, manifest, stop=lambda: True)
    assert result["state"] == "cancelled" and not result["can_run"]


def test_metadata_refresh_alone_never_grants_preflight_success(case, monkeypatch):
    project, ki, manifest, _cfg, _config = case
    monkeypatch.setattr(ki_adaptations, "refresh_project_projection", lambda *a, **k: True)
    monkeypatch.setattr(install, "run_preflight",
                        lambda *a, **k: install.Step("preflight", False, "actual case requirement failed"))
    monkeypatch.setattr(software_verification, "requirements",
                        lambda *a, **k: pytest.fail("must stop after preflight failure"))
    result = pv.verify(project, ki, manifest)
    assert not result["ok"] and "actual case requirement failed" in result["detail"]
