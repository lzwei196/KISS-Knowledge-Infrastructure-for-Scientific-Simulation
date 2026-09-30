"""Explicit planning answers through normalization and the real chat handoff.

The chat handler stops at Flow's boundary, before any provider, approval,
download or scientific execution. All session/request files are temporary.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from kiss_cli import acquire, flowrun, gui, policy, sessions
from kiss_cli import setup as setup_flow


CUSTOM = "__custom_answer__"


def question(**overrides):
    return {
        "id": "planning-question", "kind": "choice", "status": "waiting",
        "title": "Which input should this project use?", "allow_note": True,
        "message": "Select a candidate or provide your own value/file.",
        "options": [{"id": f"source-{index}", "label": f"Source {index}",
                     "response": f"Use source {index}"} for index in range(12)],
        **overrides,
    }


def custom_action(pending, note="0.25", **overrides):
    return {"request_id": pending["id"], "option_id": CUSTOM, "note": note, **overrides}


def test_request_round_trip_preserves_all_candidates_and_no_picked_default(tmp_path):
    source = question()
    created = setup_flow.request_user(tmp_path, source)
    loaded = setup_flow.request(tmp_path)
    assert len(created["options"]) == len(loaded["options"]) == 12
    assert [option["id"] for option in loaded["options"]] == [f"source-{index}" for index in range(12)]
    assert "picked" not in loaded and "selected_option" not in loaded
    assert setup_flow.choice_response(loaded, None) is None
    for option in loaded["options"]:
        actual = setup_flow.choice_response(loaded, {
            "request_id": loaded["id"], "option_id": option["id"],
        })
        assert actual == option


@pytest.mark.parametrize("answer", ["0.25", "inputs/uploads/my weather.nc", "使用我上传的土壤文件"])
def test_explicit_custom_value_or_path_is_a_planning_answer(answer):
    pending = question()
    assert setup_flow.choice_response(pending, custom_action(pending, f"  {answer}  ")) == {
        "id": CUSTOM, "label": "Custom answer", "response": answer,
    }
    assert pending["status"] == "waiting"  # resolver itself grants nothing


DENIED_CASES = [
    ({}, {"request_id": "different-question"}),
    ({}, {"note": " \n "}),
    ({"allow_note": False}, {}),
    ({"status": "ready"}, {}),
    ({"kind": "permission"}, {}),
    ({"kind": "download"}, {}),
    ({"kind": "login"}, {}),
    ({"kind": "licence"}, {}),
    ({"plan_review": {"goal": "approve a plan"}}, {}),
    ({"id": flowrun.APPROVAL_REQUEST_ID_PREFIX + "test"}, {}),
    ({"id": flowrun.BLOCKED_REQUEST_ID}, {}),
    ({"id": acquire.MANUAL_REQUEST_ID}, {}),
]


@pytest.mark.parametrize("pending_change,action_change", DENIED_CASES)
def test_custom_answer_never_becomes_a_permission_download_or_approval(pending_change, action_change):
    pending = question(**pending_change)
    assert setup_flow.choice_response(pending, custom_action(pending, **action_change)) is None


class ReachedFlow(BaseException):
    """Stop outside the handler's Exception catch before provider dispatch."""


@pytest.fixture
def chat(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry.json"))
    workroot = tmp_path / "workroot"
    session = sessions.create(workroot, [], "cli:kimi", project_parent=tmp_path / "projects")
    session["title"] = "Planning answer fixture"
    sessions.save(workroot, session)
    project = sessions.project_path(workroot, session)
    handler = object.__new__(gui.Handler)
    handler.workroot = workroot
    handler.catalog = []
    handler._open_stream = lambda: None
    handler._chunk = lambda text: None
    handler._end_stream = lambda: None
    reached = []

    def before_flow(*args, **kwargs):
        reached.append((args, kwargs))
        raise ReachedFlow

    def forbidden(*args, **kwargs):
        pytest.fail("answering a planning question must not grant permission, download, or run a provider")

    monkeypatch.setattr(flowrun, "pre", before_flow)
    monkeypatch.setattr(policy.Policy, "approve", forbidden)
    monkeypatch.setattr(acquire, "run", forbidden)
    monkeypatch.setattr(gui.api, "run", forbidden)

    def submit(pending, message, action=None):
        path = project / setup_flow.REQUEST_FILE
        path.write_text(json.dumps(pending), encoding="utf-8")
        before = path.read_bytes()
        request = {"message": message}
        if action is not None:
            request["action"] = action
        with pytest.raises(ReachedFlow):
            handler._stream_session_chat(session["id"], request)
        assert len(reached) == 1
        assert not (project / "runs" / "approval.json").exists()
        assert not sessions.load(workroot, session["id"]).get("temporary_read_grants")
        return setup_flow.request(project), before, path.read_bytes()

    return SimpleNamespace(project=project, submit=submit, reached=reached)


@pytest.mark.parametrize("answer", ["0.25", "inputs/uploads/site soil.csv"])
@pytest.mark.parametrize("options", [[], question()["options"]])
def test_real_chat_records_explicit_custom_answer_without_approval(chat, answer, options):
    pending = question(options=options)
    current, _before, _after = chat.submit(pending, f"Use my answer: {answer}", custom_action(pending, answer))
    assert current["status"] == "ready"
    assert answer in current["user_note"]
    assert chat.reached[0][0][4]["note"] == answer
    assert chat.reached[0][0][5] is None  # not a Flow approval click


def test_real_chat_saves_the_clicked_answer_for_later_turns(chat):
    """Issue #3: the click used to live only in the request file, which the next question archives."""
    from kiss_cli import plan_review
    pending = question()
    chat.submit(pending, "Source 3", {"request_id": pending["id"], "option_id": "source-3"})
    rec = plan_review.load_user_answers(chat.project)["interview:planning-question"]
    assert rec["value"] == "Source 3" and rec["question"] == pending["title"]


def test_real_chat_saves_a_custom_answer_for_later_turns(chat):
    from kiss_cli import plan_review
    pending = question()
    chat.submit(pending, "2003–2005", custom_action(pending, "2003–2005"))
    assert plan_review.load_user_answers(chat.project)["interview:planning-question"]["value"] == "2003–2005"


def test_real_chat_keeps_the_note_on_an_option_answer(chat):
    from kiss_cli import plan_review
    pending = question()
    chat.submit(pending, "Source 3, for validation only", {
        "request_id": pending["id"], "option_id": "source-3", "note": "for validation only"})
    answer = plan_review.load_user_answers(chat.project)["interview:planning-question"]
    assert answer["value"] == "Source 3" and answer["note"] == "for validation only"
    assert "for validation only" in plan_review.settled_answers_block(chat.project)


@pytest.mark.parametrize("options", [[], question()["options"]])
def test_ask_about_choices_prose_leaves_the_question_pending(chat, options):
    pending = question(options=options)
    current, before, after = chat.submit(
        pending, "I cannot decide yet. Compare these options, their risks, and their effects, then ask me again.")
    assert current["status"] == "waiting"
    assert before == after


@pytest.mark.parametrize("options", [[], question()["options"]])
@pytest.mark.parametrize("pending_change,action_change", DENIED_CASES)
def test_real_chat_rejects_invalid_custom_answers_without_resolving_request(
        chat, options, pending_change, action_change):
    pending = question(options=options, **pending_change)
    current, before, after = chat.submit(
        pending, "My custom answer is 0.25", custom_action(pending, **action_change))
    assert current["status"] == pending["status"]
    assert before == after
