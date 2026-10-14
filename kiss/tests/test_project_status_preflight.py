"""Project status reads exact preflight proof, never a shared installation pass."""
import json

import pytest

from kiss_cli import install, project_status
from .test_project_verification import case, _forbid_checks, _passing, pv
from .test_project_status_render import evaluate, fixture_data


def progress(rows, **overrides):
    values = dict(report={"status": "complete"}, state="COMPLETED", stage="results",
                  selected=["Demo"], plan={"goal": "Fixture"}, request=None,
                  proof={"receipts_verified": True, "validation": "passed"}, approval="OK",
                  acquisition={}, activity={}, errors=[], observed_at=1, now=2,
                  acquisition_progress={"counts": {}}, data_acquired=False, preflights=rows)
    values.update(overrides)
    return project_status._progress(**values)


def test_signed_failed_preflight_overrides_idle_and_old_completion(case, monkeypatch):
    project, ki, man, _cfg, _config = case
    monkeypatch.setattr(install, "run_preflight", lambda *a, **kw: install.Step("preflight", False, "wrong path"))
    assert pv.verify(project, ki, man)["state"] == "failed"
    before = pv._receipt_path(project, ki.name).read_bytes()
    _forbid_checks(monkeypatch)
    rows = project_status._project_preflights(project, [ki.name])
    assert rows == [{"name": "Demo", "state": "failed", "can_run": False}]
    for state in ("SETUP_REQUIRED", "COMPLETED"):
        result = progress(rows, state=state)
        assert result["status"] == "failed" and not result["science_complete"]
        assert not result["ready_to_start"] and "Latest project preflight did not pass: Demo" in result["summary"]
    assert pv._receipt_path(project, ki.name).read_bytes() == before


def test_new_pass_replaces_failure_but_runtime_drift_cannot_stay_green(case, monkeypatch):
    project, ki, man, cfg, config = case
    monkeypatch.setattr(install, "run_preflight", lambda *a, **kw: install.Step("preflight", False, "fixture"))
    pv.verify(project, ki, man)
    _passing(monkeypatch)
    assert pv.verify(project, ki, man)["ok"]
    _forbid_checks(monkeypatch)
    assert project_status._project_preflights(project, [ki.name])[0]["can_run"]
    cfg.python = "unverified-python"
    config.write_text(cfg.dumps(), encoding="utf-8")
    rows = project_status._project_preflights(project, [ki.name])
    assert rows[0]["state"] == "stale" and not rows[0]["can_run"]
    assert progress(rows)["status"] == "failed"


def test_forged_pass_and_unselected_failures_are_not_promoted(case, monkeypatch):
    project, ki, man, _cfg, _config = case
    _passing(monkeypatch)
    assert pv.verify(project, ki, man)["ok"]
    path = pv._receipt_path(project, ki.name)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["checked_at"] += 1
    path.write_text(json.dumps(doc), encoding="utf-8")
    _forbid_checks(monkeypatch)
    assert project_status._project_preflights(project, [ki.name])[0]["state"] == "stale"
    assert project_status._project_preflights(project, []) == []


@pytest.mark.parametrize("zh", [False, True])
def test_status_panel_does_not_substitute_shared_installation_for_project_pass(zh):
    data = fixture_data()
    data["preparation"]["software_summary"] = {"ready": 1, "total": 1}
    data["project_status"]["project_preflights"] = [{"name": "Demo", "state": "failed", "can_run": False}]
    data["project_status"]["progress"] = progress(data["project_status"]["project_preflights"])
    html = evaluate(data, zh=zh)["html"]
    assert ("0 / 1 项目预检通过" if zh else "0 / 1 project preflights passed") in html
    assert "Ready to continue" not in html and "1 / 1 software verified" not in html
