"""Planning questions outrank saved drafts at the real desktop turn boundary.

No provider, server, download or model is run. Only the existing request/resume,
FlowSession and planning-worktree lifecycles operate on an isolated project.
"""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from kiss_cli import acquire, flowrun, obs_access, obs_subset, plan_review, projectrun
from kiss_cli import setup as setup_flow


@pytest.fixture
def planning(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    project = tmp_path / "project"
    (project / "runs").mkdir(parents=True)
    root = tmp_path / "kis" / "M"
    (root / "tools").mkdir(parents=True)
    (root / "SKILL.md").write_text("# M\n> **MANDATORY EXECUTION POLICY**\n> run the real model\n")
    (root / "dag.yaml").write_text(
        "outputs:\n- var: discharge\n  validation_rank: 1\n  unit: m3/s\n"
        "processes:\n  modules:\n  - id: run\n    inputs: []\n    outputs: [discharge]\n"
    )
    (root / "tools/run.py").write_text("raise AssertionError('planning must not run a model')\n")
    ki = SimpleNamespace(name="M", root=root)
    cfg = SimpleNamespace(root=project, python=sys.executable, roles={"binaries": project / "bin"})
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)

    guard = SimpleNamespace(allow_review=False, calls=[])

    def forbidden(*_args, **_kwargs):
        pytest.fail("planning must never approve, download, or execute")

    def stamp(*_args, **_kwargs):
        assert guard.allow_review, "an unanswered question must prevent inventory finalization"
        guard.calls.append("stamp")
        return []

    def refresh(*_args, **_kwargs):
        assert guard.allow_review, "an unanswered question must prevent subset re-estimates"
        guard.calls.append("estimate")

    original_issue = plan_review.issue

    def issue(*args, **kwargs):
        assert guard.allow_review, "an unanswered question must not be replaced by an approval card"
        guard.calls.append("review")
        return original_issue(*args, **kwargs)

    monkeypatch.setattr(obs_access, "stamp_inventory", stamp)
    monkeypatch.setattr(obs_subset, "refresh_inventory", refresh)
    monkeypatch.setattr(plan_review, "issue", issue)
    monkeypatch.setattr(flowrun._flow().approval, "approve", forbidden)
    monkeypatch.setattr(obs_subset, "approve_inventory", forbidden)
    monkeypatch.setattr(acquire, "run", forbidden)
    monkeypatch.setattr(flowrun.flowgate.FlowSession, "fetch", forbidden)
    return SimpleNamespace(project=project, ki=ki, cfg=cfg, guard=guard)


def start(fixture, provider="kimi", goal="run M for 2003"):
    return flowrun.turn(fixture.project, [fixture.ki], fixture.cfg,
                        "api" if provider == "deepseek" else "cli", provider, None, goal)


def save_draft(fixture, turn, goal="Agent-reviewed draft"):
    flow = turn.session.flow
    root = turn.planning_worktree or fixture.project
    plan, inventory = flow.plan.read_artifacts(root)
    plan["goal"] = goal
    for step in plan["steps"]:
        step["tool"] = str(fixture.ki.root / "tools/run.py")
        step["kind"] = "run"
    for item in inventory["items"]:
        item["status"] = "resolved"
        item["needs_user"] = False
    if turn.policy.provider == "api":
        assert turn.session.write_plan(plan, inventory) == []
    else:
        flow.plan.write_artifacts(root, plan, inventory)
    return plan, inventory


def ask(fixture, title="Which study area?"):
    setup_flow.request_user(fixture.project, {
        "kind": "choice", "title": title, "message": "Please answer before planning continues.",
        "allow_note": True,
        "options": [{"id": "answer", "label": "Answer", "response": "My answer"}],
    })
    return setup_flow.request(fixture.project)


def assert_paused(fixture, turn, question, result):
    project = fixture.project
    assert result.request is None
    assert not result.continue_now and not result.retry_planning
    assert turn.session.state.value == "PLANNING"
    assert setup_flow.request(project) == question
    status = projectrun.load(project)
    assert status["status"] == "waiting_for_user"
    assert status["blocker"]["id"] == question["id"]
    assert not (project / "runs/approval.json").exists()
    assert not (project / "runs/plan-review.json").exists()
    assert fixture.guard.calls == []


def test_question_without_plan_files_is_a_pause_not_a_failed_submission(planning):
    turn = start(planning, "deepseek")
    for rel in ("runs/plan.json", "runs/data-inventory.json"):
        (planning.project / rel).unlink()
    question = ask(planning)
    result = flowrun.after(planning.project, turn, "Which study area?")
    assert_paused(planning, turn, question, result)
    assert not (planning.project / "runs/plan-validation.txt").exists()


@pytest.mark.parametrize("provider", ["deepseek", "claude", "kimi", "codex"])
def test_planning_handoff_says_to_settle_questions_before_final_submission(planning, provider):
    prompt = start(planning, provider).extra_prompt.split("[PLAN HANDOFF]", 1)[1]
    assert "Only when the planning decisions are settled" in prompt
    assert "ONE request_user_action" in prompt and "stop for the user's answer" in prompt
    assert "Ask before rewriting either full draft" in prompt
    assert "the conversation retains previous answers" in prompt
    assert "not a final submission while a question remains" in prompt


@pytest.mark.parametrize("provider", ["deepseek", "claude", "kimi"])
def test_saved_plan_does_not_overwrite_an_unanswered_question(planning, provider):
    turn = start(planning, provider)
    plan, inventory = save_draft(planning, turn)
    original = turn.session.flow.plan.read_artifacts(planning.project)
    question = ask(planning)
    request_bytes = (planning.project / setup_flow.REQUEST_FILE).read_bytes()
    result = flowrun.after(planning.project, turn, "I saved a draft, but need your answer first.")
    assert_paused(planning, turn, question, result)
    assert (planning.project / setup_flow.REQUEST_FILE).read_bytes() == request_bytes
    assert turn.session.flow.plan.read_artifacts(turn.planning_worktree or planning.project) == (plan, inventory)
    assert turn.session.flow.plan.read_artifacts(planning.project) == original
    if turn.planning_worktree:
        metadata = json.loads((planning.project / ".geoforge/planning-last.json").read_text())
        assert metadata == {"draft_root": str(turn.planning_worktree)}


@pytest.mark.parametrize("provider,submitted", [("kimi", False), ("deepseek", True)])
def test_provider_failure_keeps_the_valid_question_and_preserved_draft(planning, provider, submitted):
    turn = start(planning, provider)
    if submitted:
        save_draft(planning, turn)
    question = ask(planning)
    turn.provider_succeeded = False
    result = flowrun.after(planning.project, turn, "", provider_note="connection interrupted")
    assert_paused(planning, turn, question, result)
    assert "provider" in result.message.lower() and "question" in result.message.lower()
    assert not (planning.project / "runs/plan-validation.txt").exists()


def test_two_questions_resume_the_same_draft_before_the_final_review(planning):
    project = planning.project
    first = start(planning)
    initial = first.session.flow.plan.read_artifacts(project)
    first_draft = save_draft(planning, first, "Draft awaiting study area")
    first_question = ask(planning)
    assert_paused(planning, first, first_question, flowrun.after(project, first, "Which study area?"))
    assert first.session.flow.plan.read_artifacts(project) == initial

    # This is the existing explicit user-answer path. It is not approval.
    setup_flow.resume(project, "Harbin")
    pre = flowrun.pre(project, "Harbin", ["M"], [planning.ki], None, setup_flow.request(project))
    assert pre.message is None
    second = start(planning, goal="Harbin")
    assert second.planning_worktree != first.planning_worktree
    assert second.session.flow.plan.read_artifacts(second.planning_worktree) == first_draft
    second_draft = save_draft(planning, second, "Harbin draft awaiting simulation period")
    second_question = ask(planning, "Which simulation period?")
    assert second_question["id"] != first_question["id"]
    assert_paused(planning, second, second_question, flowrun.after(project, second, "Which period?"))
    assert second.session.flow.plan.read_artifacts(project) == initial

    setup_flow.resume(project, "2003-2004")
    flowrun.pre(project, "2003-2004", ["M"], [planning.ki], None, setup_flow.request(project))
    third = start(planning, goal="2003-2004")
    assert third.session.flow.plan.read_artifacts(third.planning_worktree) == second_draft
    final_draft = save_draft(planning, third, "Harbin for 2003-2004, both answers incorporated")
    third.provider_succeeded = True
    planning.guard.allow_review = True
    result = flowrun.after(project, third, "Ready for your review.")
    assert result.request["id"].startswith(flowrun.APPROVAL_REQUEST_ID_PREFIX)
    assert third.session.state.value == "WAITING_FOR_USER"
    assert setup_flow.request(project)["id"] == result.request["id"]
    assert third.session.flow.plan.read_artifacts(project) == final_draft
    assert planning.guard.calls == ["stamp", "estimate", "stamp", "review"]
    assert not result.continue_now and not result.retry_planning
    assert not (project / "runs/approval.json").exists()
    assert not (project / ".geoforge/planning-last.json").exists()
