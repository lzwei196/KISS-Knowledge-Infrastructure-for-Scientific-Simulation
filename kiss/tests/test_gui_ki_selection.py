"""Selecting a known KI permits diagnosis, never execution of unchecked code."""
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import gui, ki_guard, sessions
from kiss_cli.catalog import KI


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_GUARD_HOME", str(tmp_path / "guard"))
    known = KI("VIC", tmp_path / "broken-vic")
    def get(name):
        if name != "VIC":raise KeyError(name)
        return known
    handler = object.__new__(gui.Handler)
    handler.catalog = SimpleNamespace(get=get)
    handler.workroot = tmp_path / "work"
    handler._browser_write_allowed = lambda:(True, "")
    handler._json = lambda body, code=200:(body, code)
    session = sessions.create(handler.workroot, [], provider="api:deepseek", project_name="Diagnose VIC")
    copied=[]
    monkeypatch.setattr(gui.calibration, "ensure_project", lambda project, kis=():copied.extend(kis))
    return handler, session, known, copied


def update(case, payload):
    handler, session, _, _ = case
    body = json.dumps(payload).encode()
    handler.path = f"/api/session/{session['id']}/update"
    handler.headers = {"Content-Length": str(len(body))}
    handler.rfile = io.BytesIO(body)
    return handler.do_POST()


def test_broken_known_ki_can_be_selected_without_enrollment_or_adapter_copy(case):
    handler, session, known, copied = case
    assert handler._validate_binding({"models":["VIC"]}) is None
    body, status = update(case, {"models":["VIC"]})
    assert status == 200 and body["models"] == ["VIC"]
    assert sessions.load(handler.workroot, session["id"])["models"] == ["VIC"]
    assert not ki_guard.is_managed(known.root) and not copied
    with pytest.raises(KeyError, match="Not accepted on this computer"):
        handler._ki("VIC")


def test_unknown_ki_and_invalid_selection_are_rejected_before_mutation(case):
    handler, session, _, _ = case
    for invalid in [["Invented"], "VIC", [3]]:
        body,status=update(case,{"models":invalid})
        assert status == 400 and body["error"]
    assert sessions.load(handler.workroot, session["id"])["models"] == []


def test_intact_ki_still_supplies_existing_calibration_adapter(case):
    _, _, known, copied = case
    known.root.mkdir()
    (known.root / "SKILL.md").write_text("Fixture intact KI\n")
    ki_guard.enroll(known.root)
    body,status=update(case,{"models":["VIC"]})
    assert status == 200 and copied == [known]


def test_started_chat_keeps_its_model_binding_locked(case):
    handler, session, _, _ = case
    sessions.append_message(handler.workroot,session,{"role":"user","text":"Already started"})
    sessions.save(handler.workroot,session)
    body,status=update(case,{"models":["VIC"]})
    assert status == 409 and body["locked"] is True
    assert sessions.load(handler.workroot,session["id"])["models"] == []
