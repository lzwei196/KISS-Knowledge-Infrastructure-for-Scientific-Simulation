"""Plan Review behavior across persisted desktop turns, not private helper calls.

All projects, signing keys and catalogue entries are local fixtures. No provider,
database token, download or scientific tool is used by these lifecycle tests.
"""
from __future__ import annotations

import copy
import json
import sys
from types import SimpleNamespace

import pytest

from kiss_cli import acquire, execution, flowgate, flowrun, obs_access, obs_subset, plan_review, setup as setup_flow


@pytest.fixture
def review_project(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    catalogue = {"datasets": [
        {"id": "source_a", "name": "Source A", "delivery": "served"},
        {"id": "source_b", "name": "Source B", "delivery": "served"},
    ]}
    monkeypatch.setattr(obs_access, "load_catalogue", lambda: copy.deepcopy(catalogue))
    monkeypatch.setattr(obs_access, "refresh_catalogue", lambda *a, **k: copy.deepcopy(catalogue))
    monkeypatch.setattr(acquire, "run", lambda *a, **k: {"status": "done", "items": {}})
    project = tmp_path / "project"
    (project / "runs").mkdir(parents=True)
    ki_root = tmp_path / "kis" / "M"
    (ki_root / "tools").mkdir(parents=True)
    (ki_root / "SKILL.md").write_text("# M\nUse the real model.\n", encoding="utf-8")
    (ki_root / "dag.yaml").write_text(
        "outputs:\n- var: discharge\n  validation_rank: 1\n  unit: m3/s\n"
        "processes:\n  modules:\n  - id: run\n    inputs: []\n    outputs: [discharge]\n",
        encoding="utf-8",
    )
    (ki_root / "tools" / "run.py").write_text("raise AssertionError('must not run')\n", encoding="utf-8")
    ki = SimpleNamespace(name="M", root=ki_root)
    cfg = SimpleNamespace(root=project, python=sys.executable, roles={"binaries": project / "bin"})
    return SimpleNamespace(project=project, ki=ki, cfg=cfg, catalogue=catalogue)


def _draft(env, *, with_data=False, revise=None):
    flowrun.pre(env.project, "Run M for 2003", ["M"], [env.ki], None, None)
    turn = flowrun.turn(env.project, [env.ki], env.cfg, "api", "deepseek", None, "Run M for 2003")
    plan, inventory = turn.session.flow.plan.read_artifacts(env.project)
    for step in plan["steps"]:
        step["kind"] = "run"
        step["tool"] = str(env.ki.root / "tools" / "run.py")
    for item in inventory["items"]:
        item.update(status="resolved", needs_user=False)
    plan["scientific_choices"] = [
        {"id": "routing", "kind": "routing_scheme", "options": ["lohmann", "cama"],
         "picked": "lohmann", "high_impact": True},
    ]
    if with_data:
        inventory["items"].append({
            "id": "forcing", "required_by": ["M"], "status": "resolved", "acceptable_sources": [],
            "chosen_source": "source_a", "dataset_id": "source_a", "local_paths": [],
            "agent_resolvable": True, "needs_user": False,
        })
        plan["steps"][0]["inputs"] = list(plan["steps"][0].get("inputs") or []) + ["forcing"]
        plan["scientific_choices"].append({
            "id": "select-data", "kind": "data_source", "item": "forcing",
            "options": ["source_a", "source_b"], "picked": "source_a", "high_impact": True,
        })
    if revise is not None:
        revise(plan, inventory)
    assert turn.session.write_plan(plan, inventory) == []
    result = flowrun.after(env.project, turn, "The draft is ready for review.", setup_ok=True)
    assert result.request and not result.continue_now
    return result.request


def _click(env, card, *, option="approve", choices=None, shown=None):
    action = {"request_id": card["id"], "option_id": option}
    if choices is not None:
        action["choices"] = choices
    if shown is not None:
        action["shown"] = shown
    return flowrun.pre(env.project, "Approved" if option == "approve" else "Revise the plan",
                       ["M"], [env.ki], action, card)


def _approval(env):
    return json.loads((env.project / "runs" / "approval.json").read_text(encoding="utf-8"))


def test_disk_loaded_review_retains_issued_baseline_when_catalogue_changes(review_project):
    """A new turn needs no in-memory card or freshly reconstructed recommendations."""
    env = review_project
    _draft(env, with_data=True)
    # Simulate a fresh desktop turn: retain only the persisted request, while the
    # catalogue has refreshed and no longer lists the previously displayed rows.
    env.catalogue["datasets"] = []
    persisted_card = json.loads((env.project / "setup-request.json").read_text(encoding="utf-8"))
    result = _click(env, persisted_card)
    assert result.message is None
    records = _approval(env)["decisions"]
    assert records["item:forcing"]["source"] == "ki_default"
    assert records["item:forcing"]["value"] == "source_a"
    assert "recommendation shown on the card" in records["item:forcing"]["rationale"]
    assert records["choice:routing"]["source"] == "ki_default"
    assert flowrun.current_state(env.project) == "EXECUTING"


@pytest.mark.parametrize("tamper_target", ["echo", "pending"])
def test_changed_displayed_card_cannot_approve_even_with_original_plan(review_project, tamper_target):
    env = review_project
    card = _draft(env)
    changed = copy.deepcopy(card)
    changed["plan_review"]["decisions"][0]["picked"] = "cama"
    result = _click(env, card if tamper_target == "echo" else changed,
                    shown=changed if tamper_target == "echo" else None)
    assert "card changed" in result.replan_reason
    assert not (env.project / "runs" / "approval.json").exists()
    assert flowrun.current_state(env.project) == "PLANNING"


@pytest.mark.parametrize("damage", ["missing", "invalid_json", "missing_baseline"])
def test_unverifiable_host_review_never_falls_back_to_request_copy(review_project, damage):
    env = review_project
    card = _draft(env)
    host_record = env.project / "runs" / "plan-review.json"
    if damage == "missing":
        host_record.unlink()
    elif damage == "invalid_json":
        host_record.write_text("{broken", encoding="utf-8")
    else:
        doc = json.loads(host_record.read_text(encoding="utf-8"))
        del doc["baseline"]
        host_record.write_text(json.dumps(doc), encoding="utf-8")
    assert card["review"]  # The intact request-side copy cannot authorize approval.
    result = _click(env, card)
    assert result.replan_reason
    assert not (env.project / "runs" / "approval.json").exists()
    assert flowrun.current_state(env.project) == "PLANNING"


def test_user_answers_survive_unsigned_repin_and_persisted_rereview(review_project):
    env = review_project
    card = _draft(env, with_data=True)
    result = _click(env, card, choices={"select-data": "source_b", "routing": "cama"})
    assert "re-pinned" in result.message
    assert not (env.project / "runs" / "approval.json").exists()
    reissued = setup_flow.request(env.project)
    assert reissued["plan_review"]["data_choices"][0]["picked"] == "source_b"
    assert reissued["plan_review"]["decisions"][0]["picked"] == "cama"
    # The second click looks unchanged, but these are the user's earlier answers,
    # not planner recommendations. Reloading from disk must retain that fact.
    result = _click(env, json.loads(json.dumps(reissued)),
                    choices={"select-data": "source_b", "routing": "cama"})
    assert result.message is None
    records = _approval(env)["decisions"]
    for key, value in (("item:forcing", "source_b"), ("choice:select-data", "source_b"),
                       ("choice:routing", "cama")):
        assert records[key]["source"] == "user"
        assert records[key]["value"] == value


def test_replanning_choice_for_another_input_does_not_transfer_user_answer(review_project):
    env = review_project
    card = _draft(env, with_data=True)
    _click(env, card, choices={"select-data": "source_b"})
    reissued = setup_flow.request(env.project)
    _click(env, reissued, option="modify")
    turn = flowrun.turn(env.project, [env.ki], env.cfg, "api", "deepseek", None, "Use a different input")
    plan, inventory = turn.session.flow.plan.read_artifacts(env.project)
    item = next(item for item in inventory["items"] if item["id"] == "forcing")
    item["id"] = "temperature"
    for step in plan["steps"]:
        step["inputs"] = ["temperature" if value == "forcing" else value for value in step.get("inputs") or []]
    choice = next(choice for choice in plan["scientific_choices"] if choice["id"] == "select-data")
    choice["item"] = "temperature"
    assert turn.session.write_plan(plan, inventory) == []
    revision = flowrun.after(env.project, turn, "The new input is ready for review.", setup_ok=True)
    assert revision.request
    result = _click(env, revision.request, choices={"select-data": "source_b"})
    assert result.message is None
    records = _approval(env)["decisions"]
    assert records["item:temperature"]["source"] == "ki_default"
    assert records["choice:select-data"]["source"] == "ki_default"
    answers = json.loads((env.project / ".geoforge" / "user-answers.json").read_text(encoding="utf-8"))["answers"]
    assert answers["item:forcing"]["value"] == "source_b"
    assert "item:temperature" not in answers


@pytest.mark.parametrize("contents", ["{broken", "[]", '{"schema":1,"answers":[]}'])
def test_corrupt_saved_answers_refuse_without_consuming_pending_review(review_project, contents):
    env = review_project
    card = _draft(env)
    pending_path = env.project / "setup-request.json"
    pending_before = pending_path.read_bytes()
    answers = env.project / ".geoforge" / "user-answers.json"
    answers.parent.mkdir(parents=True, exist_ok=True)
    answers.write_text(contents, encoding="utf-8")
    result = _click(env, card)
    assert "saved answers cannot be read" in result.message
    assert pending_path.read_bytes() == pending_before
    assert answers.read_text(encoding="utf-8") == contents
    assert not (env.project / "runs" / "approval.json").exists()
    assert flowrun.current_state(env.project) == "WAITING_FOR_USER"


def test_failed_approval_refresh_retains_pending_review_without_starting_work(review_project, monkeypatch):
    env = review_project
    card = _draft(env, with_data=True)
    pending_path = env.project / "setup-request.json"
    pending_before = pending_path.read_bytes()
    calls = []

    def fail_refresh(*args, **kwargs):
        calls.append("refresh")
        raise obs_access.ObsAccessError("connection_failed", "Dataset estimate connection is temporarily unavailable")

    monkeypatch.setattr(obs_subset, "refresh_inventory", fail_refresh)
    monkeypatch.setattr(obs_subset, "approve_inventory", lambda *a, **k: calls.append("remote_jobs") or [])
    monkeypatch.setattr(acquire, "run", lambda *a, **k: calls.append("acquire") or {"status": "done", "items": {}})
    error = None
    result = None
    try:
        result = _click(env, card)
    except obs_access.ObsAccessError as exc:
        error = exc

    assert calls == ["refresh"]
    assert not (env.project / "runs" / "approval.json").exists()
    assert flowrun.current_state(env.project) == "WAITING_FOR_USER"
    assert pending_path.exists(), "A failed estimate refresh must not consume the pending approval card"
    assert pending_path.read_bytes() == pending_before
    assert error is None, f"Approval must report a recoverable refresh failure, not propagate it: {error}"
    assert result.message and "unavailable" in result.message.lower()


@pytest.mark.parametrize("attack", [
    "off_menu_data", "catalogue_hidden_option", "unshown_data_choice", "low_impact_choice", "unknown_choice",
])
def test_unshown_or_off_menu_picks_cannot_change_the_reviewed_selection(review_project, attack):
    env = review_project
    picks = {"select-data": "not_offered"}

    def revise(plan, inventory):
        if attack == "catalogue_hidden_option":
            plan["scientific_choices"][-1]["options"].append("not_in_catalogue")
            picks["select-data"] = "not_in_catalogue"
        elif attack == "unshown_data_choice":
            plan["scientific_choices"].append({
                "id": "hidden-data", "kind": "data_source", "item": "forcing",
                "options": ["unlisted_a", "unlisted_b"], "picked": "unlisted_a", "high_impact": True,
            })
            picks.clear()
            picks["hidden-data"] = "unlisted_b"
        elif attack == "low_impact_choice":
            plan["scientific_choices"].append({
                "id": "quiet", "kind": "tuning", "options": ["original", "changed"],
                "picked": "original", "high_impact": False,
            })
            picks.clear()
            picks["quiet"] = "changed"
        elif attack == "unknown_choice":
            picks.clear()
            picks["not-a-choice"] = "changed"

    card = _draft(env, with_data=True, revise=revise)
    shown_choices = {
        row["id"]: [option["dataset_id"] for option in row["options"]]
        for row in card["plan_review"]["data_choices"]
    }
    # renderPlanReview displays only high-impact scientific decisions; the
    # serialized card also carries low-impact rows which the user never saw.
    shown_choices.update({row["id"]: row["options"] for row in card["plan_review"]["decisions"]
                          if row["high_impact"]})
    assert all(value not in shown_choices.get(key, []) for key, value in picks.items())
    plan_path = env.project / "runs" / "plan.json"
    inventory_path = env.project / "runs" / "data-inventory.json"
    before_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    before_inventory = json.loads(inventory_path.read_text(encoding="utf-8"))

    _click(env, card, choices=picks)

    after_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    after_inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    assert after_plan["scientific_choices"] == before_plan["scientific_choices"], (
        "An unshown/off-menu pick must not change a planned scientific choice"
    )
    assert after_inventory == before_inventory, "An unshown/off-menu pick must not re-pin data"
    answers_path = env.project / ".geoforge" / "user-answers.json"
    answers = json.loads(answers_path.read_text(encoding="utf-8"))["answers"] if answers_path.exists() else {}
    assert not answers


def test_failed_refresh_retains_scientific_answer_and_retry_signs_its_provenance(review_project, monkeypatch):
    env = review_project
    card = _draft(env, with_data=True)
    paths = [env.project / "setup-request.json", env.project / "runs" / "plan.json",
             env.project / "runs" / "data-inventory.json"]
    before = {path: path.read_bytes() for path in paths}
    events = []

    def refresh(*args, **kwargs):
        events.append("refresh")
        if events.count("refresh") == 1:
            raise obs_access.ObsAccessError("connection_failed", "Temporary estimate failure")
        return {}

    monkeypatch.setattr(obs_subset, "refresh_inventory", refresh)
    monkeypatch.setattr(obs_subset, "approve_inventory", lambda *a, **k: events.append("jobs") or [])
    monkeypatch.setattr(acquire, "run", lambda *a, **k: events.append("acquire") or {"status": "done", "items": {}})
    result = _click(env, card, choices={"routing": "cama"})
    assert result.message and "refresh" in result.message.lower()
    assert events == ["refresh"]
    assert not (env.project / "runs" / "approval.json").exists()
    assert all(path.read_bytes() == contents for path, contents in before.items())
    saved = json.loads((env.project / ".geoforge" / "user-answers.json").read_text(encoding="utf-8"))["answers"]
    assert saved["choice:routing"]["value"] == "cama"

    # Retry the same user action; old saved answers must not be confused with an
    # untouched recommendation or discarded because the refresh failed once.
    result = _click(env, setup_flow.request(env.project), choices={"routing": "cama"})
    assert result.message is None
    assert events == ["refresh", "refresh", "jobs", "acquire"]
    record = _approval(env)["decisions"]["choice:routing"]
    assert record["source"] == "user" and record["value"] == "cama"
    approved_plan = json.loads((env.project / "runs" / "plan.json").read_text(encoding="utf-8"))
    assert next(choice for choice in approved_plan["scientific_choices"] if choice["id"] == "routing")["decision"] == "cama"


def test_first_card_cannot_start_acquisition_after_another_review_is_issued(review_project, monkeypatch):
    env = review_project
    first = _draft(env, with_data=True)
    result = _click(env, first, choices={"select-data": "source_b"})
    assert "re-pinned" in result.message
    latest = setup_flow.request(env.project)
    assert latest["id"] != first["id"]
    events = []
    monkeypatch.setattr(obs_subset, "approve_inventory", lambda *a, **k: events.append("jobs") or [])
    monkeypatch.setattr(acquire, "run", lambda *a, **k: events.append("acquire") or {"status": "done", "items": {}})

    # A delayed click may carry the entire original card; it cannot consent to
    # the newer inventory just because a newer host review now exists.
    result = _click(env, first, choices={"select-data": "source_a"}, shown=first)
    assert result.replan_reason
    assert not (env.project / "runs" / "approval.json").exists()
    assert events == []
    inventory = json.loads((env.project / "runs" / "data-inventory.json").read_text(encoding="utf-8"))
    assert next(item for item in inventory["items"] if item["id"] == "forcing")["dataset_id"] == "source_b"


def test_review_interface_signs_without_creating_jobs_acquiring_or_executing(review_project, monkeypatch):
    env = review_project
    _draft(env, with_data=True)
    session = flowgate.FlowSession.open(env.project, {"M": env.ki.root}, database_access_mode="direct")
    plan, inventory = session.flow.plan.read_artifacts(env.project)
    inventory_bytes = (env.project / "runs" / "data-inventory.json").read_bytes()
    events = []

    def forbidden(name):
        def invoke(*args, **kwargs):
            events.append(name)
            raise AssertionError(f"Plan Review must not perform {name}")
        return invoke

    monkeypatch.setattr(obs_subset, "approve_inventory", forbidden("job creation"))
    monkeypatch.setattr(obs_subset, "bind_approved", forbidden("acquisition binding"))
    monkeypatch.setattr(acquire, "run", forbidden("data acquisition"))
    monkeypatch.setattr(execution, "execute_ki_tool", forbidden("scientific execution"))
    card = plan_review.issue(env.project, session, plan, inventory, "fixture policy")
    result = plan_review.respond(
        env.project,
        action={"request_id": card["id"], "option_id": "approve", "shown": card},
        pending=card,
        ki_roots={"M": env.ki.root},
    )
    assert result.disposition == "approved"
    assert result.inventory == inventory
    assert session.flow.approval.check(env.project) == "OK"
    assert (env.project / "runs" / "data-inventory.json").read_bytes() == inventory_bytes
    assert events == []
    # The caller, not signing, owns the transition into acquisition/execution.
    assert flowrun.current_state(env.project) == "WAITING_FOR_USER"
    assert not (env.project / "outputs").exists()


def test_estimate_io_failure_through_real_refresh_wrapper_reissues_unsigned(review_project, monkeypatch):
    env = review_project
    estimate = {
        "subsettable": True, "estimated_output_bytes": 4096, "over_output_cap": False,
        "coverage_complete": True, "missing": [], "transformations": [], "n_parts": 1,
        "snapped_output_bounds": [115, 37, 117, 39], "variables": ["prec"],
        "processing_version": "fixture/1", "source_version": "v1",
    }
    client = SimpleNamespace(_json=lambda *a, **k: copy.deepcopy(estimate))
    state = obs_subset.estimate(env.project, {
        "dataset_id": "source_a", "bbox": [115, 37, 117, 39], "variables": ["prec"],
        "start": "2003-01-01", "end": "2003-01-02",
    }, client=client)
    monkeypatch.setattr(obs_subset, "refresh_estimate", lambda project, ident, **k: obs_subset.read(project, ident))

    def revise(plan, inventory):
        item = next(item for item in inventory["items"] if item["id"] == "forcing")
        item.update(delivery="subset", acquisition_id=state["id"],
                    requirements={"bbox": "115,37,117,39", "variable": "prec",
                                  "start": "2003-01-01", "end": "2003-01-02"})

    first = _draft(env, with_data=True, revise=revise)
    events = []

    def fail_estimate(*args, **kwargs):
        events.append("estimate")
        raise OSError("Estimate state is temporarily unreadable")

    monkeypatch.setattr(obs_subset, "refresh_estimate", fail_estimate)
    monkeypatch.setattr(obs_subset, "approve_inventory", lambda *a, **k: events.append("jobs") or [])
    monkeypatch.setattr(acquire, "run", lambda *a, **k: events.append("acquire") or {"status": "done", "items": {}})
    result = _click(env, first)
    assert "changed since you reviewed" in result.message
    assert "temporarily unreadable" in result.message
    assert events == ["estimate"]
    assert not (env.project / "runs" / "approval.json").exists()
    assert flowrun.current_state(env.project) == "WAITING_FOR_USER"
    renewed = setup_flow.request(env.project)
    assert renewed and renewed["status"] == "waiting"
    assert "temporarily unreadable" in " ".join(renewed["plan_review"]["blockers"])


def test_answers_corrupted_during_estimate_are_rechecked_before_signing(review_project, monkeypatch):
    env = review_project
    card = _draft(env, with_data=True)
    paths = [env.project / "setup-request.json", env.project / "runs" / "plan.json",
             env.project / "runs" / "data-inventory.json"]
    before = {path: path.read_bytes() for path in paths}
    answers_path = env.project / ".geoforge" / "user-answers.json"
    events = []

    def corrupt_during_refresh(*args, **kwargs):
        events.append("refresh")
        # The answer was valid when the click began. A long-running estimate
        # cannot authorize signing from that now-stale in-memory copy.
        saved = json.loads(answers_path.read_text(encoding="utf-8"))["answers"]
        assert saved["choice:routing"]["value"] == "cama"
        answers_path.write_text("{broken-during-estimate", encoding="utf-8")
        return {}

    monkeypatch.setattr(obs_subset, "refresh_inventory", corrupt_during_refresh)
    monkeypatch.setattr(obs_subset, "approve_inventory", lambda *a, **k: events.append("jobs") or [])
    monkeypatch.setattr(acquire, "run", lambda *a, **k: events.append("acquire") or {"status": "done", "items": {}})
    result = _click(env, card, choices={"routing": "cama"})
    assert result.message and "saved answers cannot be read" in result.message
    assert events == ["refresh"]
    assert all(path.read_bytes() == contents for path, contents in before.items())
    assert answers_path.read_text(encoding="utf-8") == "{broken-during-estimate"
    assert not (env.project / "runs" / "approval.json").exists()
    assert flowrun.current_state(env.project) == "WAITING_FOR_USER"
