"""Actual harmless API receipts retire no answer; old questions remain history."""
import json
import os
import time

import pytest

from kiss_cli import execution, flowrun, gui, project_status, projectrun, setup
from test_execution_continuation import c, run_step
from test_project_status_render import evaluate, fixture_data


def question(c, **extra):
    raw = {"id": "old-choice", "kind": "choice", "status": "waiting",
           "title": "Export refused overwrite", "message": "Choose a destination",
           "options": [{"id": "replace", "label": "Delete stale CSV and replace"}],
           "created_at": time.time(), **extra}
    (c.project / setup.REQUEST_FILE).write_text(json.dumps(raw), encoding="utf-8")
    return raw


def complete(c):
    run_step(c, 1)
    run_step(c, 2)
    flowrun.after(c.project, c.turn, "Finished")
    assert c.fs.state.value == "COMPLETED"


def begin(c, *, legacy=False):
    if legacy:
        # Windows file timestamps can share a clock tick; genuine old requests
        # precede a later user turn, unlike two adjacent fixture writes.
        time.sleep(0.02)
        execution.begin_turn(c.project)
    else:
        projectrun.begin_turn(c.project, "Retry the approved remaining work")


@pytest.mark.parametrize("legacy", [False, True])
def test_earlier_question_is_nonblocking_unanswered_history_without_disk_changes(c, legacy):
    old = question(c)
    begin(c, legacy=legacy)
    complete(c)
    before = {p: p.read_bytes() for p in c.project.rglob("*") if p.is_file()}
    for _ in range(2):
        pending = setup.request(c.project, archive_obsolete=False)
        assert pending["status"] == "historical" and pending["unanswered"] is True
        assert pending["id"] == old["id"] and "resolved_at" not in pending
        view = project_status.snapshot(c.project)
        assert view["progress"]["status"] == "complete"
        assert view["request"] is None
        assert view["request_history"]["id"] == old["id"]
    assert before == {p: p.read_bytes() for p in c.project.rglob("*") if p.is_file()}
    assert json.loads((c.project / setup.REQUEST_FILE).read_text())["status"] == "waiting"
    # A callback holding the previous popup cannot reinstate it as a blocker.
    finished = projectrun.finish_turn(c.project, request=old)
    assert finished["status"] != "waiting_for_user" and not finished.get("blocker")
    # A later explanation turn retains its earlier unanswered status.
    projectrun.begin_turn(c.project, "Explain the result")
    assert setup.request(c.project)["status"] == "historical"


@pytest.mark.parametrize("extra", [
    {"kind": "permission"}, {"kind": "download"}, {"kind": "licence"}, {"kind": "login"},
    {"plan_review": {"plan": {}}}, {"id": "flow-approve-old"},
    {"expected_path": "private/file"}, {"command": "grant access"},
    {"options": [{"id": "enable_https", "label": "Enable network"}]},
    {"options": [{"id": "allow-kimi-read-once", "label": "Read private file"}]},
    {"actions": ["permission"]},
])
def test_permission_download_and_approval_requests_remain_actionable(c, extra):
    question(c, **extra)
    begin(c)
    complete(c)
    assert setup.request(c.project)["status"] == "waiting"
    assert project_status.snapshot(c.project)["progress"]["status"] == "waiting_for_user"


@pytest.mark.parametrize("when", ["same-turn", "after-completion", "explanation-turn"])
def test_new_or_unrelated_questions_are_not_reclassified_by_old_completion(c, when):
    begin(c)
    if when == "same-turn":
        question(c, title="Choose a scientific scenario")
    complete(c)
    if when != "same-turn":
        question(c, title="Export another format?")
    if when == "explanation-turn":
        begin(c)
    assert setup.request(c.project)["status"] == "waiting"


@pytest.mark.parametrize("legacy", [False, True])
def test_rewritten_question_with_same_id_and_created_time_stays_active(c, legacy):
    old = question(c)
    begin(c, legacy=legacy)
    complete(c)
    path = c.project / setup.REQUEST_FILE
    original_mtime = path.stat().st_mtime
    old["message"] = "A genuinely new scientific decision"
    path.write_text(json.dumps(old), encoding="utf-8")
    os.utime(path, (original_mtime, original_mtime))
    assert setup.request(c.project)["status"] == "waiting"


@pytest.mark.parametrize("damage", ["output", "approval", "state", "boundary", "preflight"])
def test_unconfirmed_completion_never_hides_a_request(c, damage):
    question(c)
    begin(c)
    if damage != "state":
        complete(c)
    if damage == "output":
        (c.project / "outputs/two.csv").write_text("changed", encoding="utf-8")
    elif damage == "approval":
        c.fs.flow.approval.revoke(c.project, "fixture")
    elif damage == "boundary":
        path = c.project / setup.REQUEST_TURN_FILE
        doc = json.loads(path.read_text()); doc["started_at"] = 1
        path.write_text(json.dumps(doc), encoding="utf-8")
    elif damage == "preflight":
        (c.root / "preflight_check.py").write_text("raise RuntimeError('changed')", encoding="utf-8")
    assert setup.request(c.project)["status"] == "waiting"


def test_late_callback_cannot_replace_a_new_permission_with_old_choice(c):
    old = question(c)
    begin(c)
    complete(c)
    new = question(c, id="new-permission", kind="permission", title="Read private file")
    finished = projectrun.finish_turn(c.project, request=old)
    assert finished["status"] == "waiting_for_user"
    assert finished["blocker"]["id"] == new["id"]


def test_popup_route_and_status_share_readonly_history_and_cached_evidence(c, monkeypatch):
    question(c)
    begin(c, legacy=True)
    complete(c)
    project_status._EVIDENCE_CACHE.clear()
    evidence = c.fs.flow.receipts.evidence
    inspected = []
    def inspect(*args, **kwargs):
        inspected.append(True)
        return evidence(*args, **kwargs)
    monkeypatch.setattr(c.fs.flow.receipts, "evidence", inspect)
    sid = "b8b03523f587"
    handler = object.__new__(gui.Handler)
    handler.workroot = c.project.parent
    handler.path = f"/api/session/{sid}/request"
    handler._json = lambda doc, *args: doc
    monkeypatch.setattr(gui.sessions, "load", lambda *args: {"id": sid})
    monkeypatch.setattr(gui.sessions, "project_path", lambda *args: c.project)
    before = {p: p.read_bytes() for p in c.project.rglob("*") if p.is_file()}
    for _ in range(2):
        assert handler.do_GET()["request"]["status"] == "historical"
        view = project_status.snapshot(c.project)
        assert view["request"] is None and view["request_history"]["unanswered"]
    assert len(inspected) == 1
    assert before == {p: p.read_bytes() for p in c.project.rglob("*") if p.is_file()}


def test_history_renderer_preserves_unanswered_text_without_answer_actions():
    data = fixture_data()
    data["project_status"]["request_history"] = {
        "status": "historical", "title": "Old <choice>", "message": "Still <unanswered>"}
    rendered = evaluate(data)
    assert "Earlier unanswered question" in rendered["html"]
    assert "has not been answered and grants no permission" in rendered["html"]
    assert "Old &lt;choice&gt;" in rendered["html"]
    assert 'id="request-respond"' not in rendered["html"]
    assert not rendered["request"]
