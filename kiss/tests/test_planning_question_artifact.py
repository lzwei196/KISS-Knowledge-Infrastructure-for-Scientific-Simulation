"""Offline CLI planning questions cross the real artifact -> host-card seam.

All projects and providers are fixtures. No socket, model, approval or download
is used; request_planning_question and after() are not mocked.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kiss_cli import acquire, flowrun, obs_access, obs_subset, plan_review
from kiss_cli import setup as setup_flow
from .test_cli_planning_question import QUESTION, project_case


@pytest.fixture
def artifact_case(project_case, monkeypatch):
    case = project_case

    def forbidden(*_args, **_kwargs):
        pytest.fail("planning question must not approve, acquire or run")

    monkeypatch.setattr(acquire, "run", forbidden)
    monkeypatch.setattr(obs_subset, "approve_inventory", forbidden)
    monkeypatch.setattr(flowrun._flow().approval, "approve", forbidden)
    monkeypatch.setattr(flowrun.flowgate.FlowSession, "fetch", forbidden)
    monkeypatch.setattr(obs_access, "stamp_inventory", lambda *_a, **_k: [])
    monkeypatch.setattr(obs_subset, "refresh_inventory", lambda *_a, **_k: None)
    return case


def _turn(case, provider="codex"):
    return flowrun.turn(case.project, [case.ki], case.cfg, "cli", provider, None,
                        "run M for 2003", database_access_mode="off")


def _path(turn):
    return turn.planning_worktree / "runs/question-request.json"


def _write_question(turn, question=QUESTION, **envelope):
    payload = {"turn_id": turn.planning_worktree.name, "question": question, **envelope}
    _path(turn).write_text(json.dumps(payload), encoding="utf-8")


def _save_plan(case, turn):
    tool = case.ki.root / "tools/run.py"
    tool.write_text("raise AssertionError('no model execution allowed')\n", encoding="utf-8")
    plan, inventory = turn.session.flow.plan.read_artifacts(turn.planning_worktree or case.project)
    plan["goal"] = "Reviewed fixture plan"
    for step in plan["steps"]:
        step.update(tool=str(tool), kind="run")
    for item in inventory["items"]:
        item.update(status="resolved", needs_user=False)
    turn.session.flow.plan.write_artifacts(turn.planning_worktree or case.project, plan, inventory)
    return plan, inventory


def _assert_no_review(case):
    assert flowrun.current_state(case.project) == "PLANNING"
    assert not (case.project / "runs/approval.json").exists()
    assert not (case.project / "runs/plan-review.json").exists()
    assert not (case.project / "runs/question-request.json").exists()


@pytest.mark.parametrize("provider", ["codex", "kimi"])
@pytest.mark.parametrize("saved", [False, True])
def test_worktree_question_pauses_even_with_saved_plan_files(artifact_case, monkeypatch, provider, saved):
    case = artifact_case
    turn = _turn(case, provider)
    initial = turn.session.flow.plan.read_artifacts(case.project)
    if saved:
        _save_plan(case, turn)
    turn.provider_succeeded = True
    _write_question(turn)
    monkeypatch.setattr(plan_review, "issue", lambda *_a, **_k: pytest.fail("question cannot issue review"))
    result = flowrun.after(case.project, turn, "I saved one question because loopback is unavailable.")
    card = setup_flow.request(case.project)
    assert card["title"] == QUESTION["title"] and card["status"] == "waiting"
    assert card["options"][0]["response"] == "Use Source A"
    assert turn.question_handoff_closed
    assert not result.continue_now and not result.retry_planning and result.request is None
    assert turn.session.flow.plan.read_artifacts(case.project) == initial
    assert _path(turn).exists()  # original artifact retained as evidence, not copied into the project
    assert not (case.project / "runs/plan-validation.txt").exists()
    _assert_no_review(case)


def test_prompt_example_is_valid_and_binds_exact_current_turn(artifact_case):
    turn = _turn(artifact_case)
    text = turn.extra_prompt.split("[QUESTION FALLBACK", 1)[1]
    example = text.split("Envelope: ", 1)[1].split(". The question", 1)[0]
    payload = json.loads(example)
    assert payload["turn_id"] == turn.planning_worktree.name
    assert set(payload) == {"turn_id", "question"}
    assert str(_path(turn)) in text
    assert "Prefer the exact CLI" in text and "do not retry repeatedly" in text
    assert "not available during intake" in text


@pytest.mark.parametrize("body", [
    b"{broken", b"\xff", b"[]", b"null",
    json.dumps({"question": QUESTION}).encode(),
    json.dumps({"turn_id": "old-turn", "question": QUESTION}).encode(),
    b" " * (64 * 1024 + 1),
    b"[" * 2000 + b"]" * 2000,
], ids=["broken", "non-utf8", "array", "null", "missing-turn", "stale-turn", "oversized", "deeply-nested"])
def test_malformed_stale_and_oversized_artifacts_fail_without_review(artifact_case, body):
    case = artifact_case
    turn = _turn(case)
    _save_plan(case, turn)
    _path(turn).write_bytes(body)
    result = flowrun.after(case.project, turn, "Question saved")
    assert "Question fallback rejected" in result.message
    assert setup_flow.request(case.project) is None
    assert result.request is None and not result.continue_now
    _assert_no_review(case)


@pytest.mark.parametrize("question", [
    {**QUESTION, "kind": "permission"},
    {**QUESTION, "approval": True},
    {**QUESTION, "options": [{"id": "enable_https", "label": "Allow network"}]},
    {**QUESTION, "options": [{"id": "approve", "label": "Approve plan"}]},
])
def test_artifact_cannot_grant_permissions_or_approval(artifact_case, question):
    case = artifact_case
    turn = _turn(case)
    _write_question(turn, question)
    result = flowrun.after(case.project, turn, "Question saved")
    assert "Question fallback rejected" in result.message
    assert setup_flow.request(case.project) is None
    _assert_no_review(case)


def test_complete_question_survives_a_later_provider_failure(artifact_case):
    case = artifact_case
    turn = _turn(case)
    _write_question(turn)
    turn.provider_succeeded = False
    result = flowrun.after(case.project, turn, "")
    assert setup_flow.request(case.project)["status"] == "waiting"
    assert "provider failed or was interrupted" in result.message
    assert not result.retry_planning
    _assert_no_review(case)


@pytest.mark.parametrize("link", ["file", "runs-directory", "hardlink"])
def test_linked_artifact_is_never_imported(artifact_case, tmp_path, link):
    case = artifact_case
    turn = _turn(case)
    outside = tmp_path / "outside"
    outside.mkdir()
    source = outside / "question-request.json"
    source.write_text(json.dumps({"turn_id": turn.planning_worktree.name, "question": QUESTION}))
    before = source.read_bytes()
    if link == "file":
        _path(turn).symlink_to(source)
    elif link == "hardlink":
        _path(turn).hardlink_to(source)
    else:
        runs = turn.planning_worktree / "runs"
        runs.rename(turn.planning_worktree / "original-runs")
        runs.symlink_to(outside, target_is_directory=True)
    result = flowrun.after(case.project, turn, "Question saved")
    assert "Question fallback rejected" in result.message
    assert setup_flow.request(case.project) is None and source.read_bytes() == before
    _assert_no_review(case)


def test_answered_artifact_never_reappears_or_finalizes_an_old_turn(artifact_case):
    case = artifact_case
    first = _turn(case)
    first_draft = _save_plan(case, first)
    _write_question(first)
    flowrun.after(case.project, first, "Question saved")
    original_card = setup_flow.request(case.project)
    setup_flow.resume(case.project, "Use Source A")
    repeated = flowrun.after(case.project, first, "Late duplicate completion")
    assert "already asked a question" in repeated.message
    assert setup_flow.request(case.project)["id"] == original_card["id"]
    assert setup_flow.request(case.project)["status"] == "ready"
    _assert_no_review(case)

    # A real next provider turn inherits draft progress, never its old question.
    second = _turn(case)
    assert second.planning_worktree != first.planning_worktree
    assert not _path(second).exists()
    assert second.session.flow.plan.read_artifacts(second.planning_worktree) == first_draft
    assert not second.question_handoff_closed
    _save_plan(case, second)
    second.provider_succeeded = True
    final = flowrun.after(case.project, second, "All choices are now settled.")
    assert final.request["id"].startswith(flowrun.APPROVAL_REQUEST_ID_PREFIX)
    assert not (case.project / "runs/approval.json").exists()


def test_copied_old_question_is_rejected_in_new_worktree(artifact_case):
    case = artifact_case
    first = _turn(case)
    _write_question(first)
    old_bytes = _path(first).read_bytes()
    second = _turn(case)
    _path(second).write_bytes(old_bytes)
    result = flowrun.after(case.project, second, "Copied an old question")
    assert "another planning turn" in result.message
    assert setup_flow.request(case.project) is None
    _assert_no_review(case)


def test_existing_helper_question_wins_over_a_later_artifact(artifact_case):
    case = artifact_case
    turn = _turn(case)
    first = flowrun.request_planning_question(case.project, QUESTION)
    _write_question(turn, {**QUESTION, "title": "A conflicting second question"})
    result = flowrun.after(case.project, turn, "Two transports attempted")
    assert setup_flow.request(case.project)["id"] == first["id"]
    assert setup_flow.request(case.project)["title"] == QUESTION["title"]
    assert not result.retry_planning
    setup_flow.resume(case.project, "Use Source A")
    repeated = flowrun.after(case.project, turn, "Duplicate completion")
    assert "already asked a question" in repeated.message
    assert setup_flow.request(case.project)["status"] == "ready"
    _assert_no_review(case)


def test_original_project_artifact_is_not_a_fallback_for_nonworktree_turns(artifact_case):
    case = artifact_case
    turn = _turn(case, "claude")
    assert turn.planning_worktree is None and "[QUESTION FALLBACK" not in turn.extra_prompt
    path = case.project / "runs/question-request.json"
    path.write_text(json.dumps({"turn_id": "forged", "question": QUESTION}))
    result = flowrun.after(case.project, turn, "No helper called")
    assert setup_flow.request(case.project) is None
    assert "No current-turn submission" in result.message
    assert not (case.project / "runs/approval.json").exists()


def test_turn_cannot_harvest_a_foreign_worktree(artifact_case, tmp_path):
    case = artifact_case
    turn = _turn(case)
    foreign = tmp_path / "different-project/.geoforge/planning" / ("f" * 32)
    (foreign / "runs").mkdir(parents=True)
    turn.planning_worktree = foreign
    _write_question(turn)
    result = flowrun.after(case.project, turn, "Wrong worktree")
    assert "not in this turn's project" in result.message
    assert setup_flow.request(case.project) is None
    _assert_no_review(case)
