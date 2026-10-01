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
from ._acquisition_fixtures import approved_result as _acq_result


@pytest.fixture
def review_project(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    catalogue = {"ok": True, "datasets": [     # a fetched catalogue, as load_catalogue returns it
        {"id": "source_a", "name": "Source A", "delivery": "served"},
        {"id": "source_b", "name": "Source B", "delivery": "served"},
    ]}
    monkeypatch.setattr(obs_access, "load_catalogue", lambda: copy.deepcopy(catalogue))
    monkeypatch.setattr(obs_access, "refresh_catalogue", lambda *a, **k: copy.deepcopy(catalogue))
    monkeypatch.setattr(acquire, "run", lambda project, **k: _acq_result(project, {"status": "done", "items": {}}))
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
    monkeypatch.setattr(acquire, "run", lambda project, **k: calls.append("acquire") or _acq_result(project, {"status": "done", "items": {}}))
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


# Two earlier cases are gone by design (issue #1, 2026-10-01): an option outside the catalogue
# is now SHOWN as external (test_a_source_outside_the_database_is_shown_…), and a second
# data-source choice that disagrees with its pinned input is refused at submission
# (test_a_choice_that_disagrees_with_its_input_goes_back_to_the_agent).
@pytest.mark.parametrize("attack", ["off_menu_data", "low_impact_choice", "unknown_choice"])
def test_unshown_or_off_menu_picks_cannot_change_the_reviewed_selection(review_project, attack):
    env = review_project
    picks = {"select-data": "not_offered"}

    def revise(plan, inventory):
        if attack == "low_impact_choice":
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
    monkeypatch.setattr(acquire, "run", lambda project, **k: events.append("acquire") or _acq_result(project, {"status": "done", "items": {}}))
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
    monkeypatch.setattr(acquire, "run", lambda project, **k: events.append("acquire") or _acq_result(project, {"status": "done", "items": {}}))

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
    monkeypatch.setattr(acquire, "run", lambda project, **k: events.append("acquire") or _acq_result(project, {"status": "done", "items": {}}))
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
    monkeypatch.setattr(acquire, "run", lambda project, **k: events.append("acquire") or _acq_result(project, {"status": "done", "items": {}}))
    result = _click(env, card, choices={"routing": "cama"})
    assert result.message and "saved answers cannot be read" in result.message
    assert events == ["refresh"]
    assert all(path.read_bytes() == contents for path, contents in before.items())
    assert answers_path.read_text(encoding="utf-8") == "{broken-during-estimate"
    assert not (env.project / "runs" / "approval.json").exists()
    assert flowrun.current_state(env.project) == "WAITING_FOR_USER"


# ── Issue #4: a file the user places for a "you provide" input is bound to it at approval ──

def _needs_upload(plan, inventory):
    inventory["items"].append({
        "id": "site", "required_by": ["M"], "status": "missing", "decision": "user",
        "acceptable_sources": [], "local_paths": [], "agent_resolvable": False, "needs_user": True,
    })
    plan["steps"][0]["inputs"] = list(plan["steps"][0].get("inputs") or []) + ["site"]


def _upload(env, name="harbin_yield_2003_2005.csv", body="year,yield\n2003,6.1\n"):
    folder = env.project / "inputs" / "user" / "site"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(body, encoding="utf-8")
    return f"inputs/user/site/{name}"


def test_a_you_provide_input_with_nothing_uploaded_blocks_approval(review_project):
    """Reproduced: the approval signed site = KI default "user" with no file at all."""
    env = review_project
    card = _draft(env, revise=_needs_upload)
    result = _click(env, card)
    assert not (env.project / "runs" / "approval.json").exists()
    assert "site" in result.message and "inputs/user/site" in result.message


def test_an_uploaded_file_is_bound_shown_and_signed_as_the_users(review_project):
    env = review_project
    card = _draft(env, revise=_needs_upload)
    rel = _upload(env)
    result = _click(env, card)
    assert rel in result.message                           # bound, card re-issued: nothing signed yet
    assert not (env.project / "runs" / "approval.json").exists()
    reissued = setup_flow.request(env.project)
    assert rel in reissued["message"]                      # the card you approve names the file
    _plan, inventory = flowgate.load().plan.read_artifacts(env.project)
    site = next(it for it in inventory["items"] if it["id"] == "site")
    assert site["local_paths"] == [rel] and site["status"] == "ready"
    result = _click(env, json.loads(json.dumps(reissued)))
    assert result.message is None
    record = _approval(env)["decisions"]["item:site"]
    digest = flowgate.load().receipts.sha256_file(env.project / rel)
    assert record["source"] == "user" and record["value"] == rel
    assert digest[:12] in record["rationale"]


def test_an_upload_replaced_after_binding_is_rebound_before_signing(review_project):
    env = review_project
    card = _draft(env, revise=_needs_upload)
    rel = _upload(env)
    _click(env, card)
    _upload(env, body="year,yield\n2003,5.9\n")            # corrected file, same name
    result = _click(env, json.loads(json.dumps(setup_flow.request(env.project))))
    assert rel in result.message and not (env.project / "runs" / "approval.json").exists()
    _click(env, json.loads(json.dumps(setup_flow.request(env.project))))
    digest = flowgate.load().receipts.sha256_file(env.project / rel)
    assert digest[:12] in _approval(env)["decisions"]["item:site"]["rationale"]


def test_an_upload_removed_after_binding_blocks_approval(review_project):
    env = review_project
    card = _draft(env, revise=_needs_upload)
    rel = _upload(env)
    _click(env, card)  # first click binds the file and issues the review naming it
    (env.project / rel).unlink()
    result = _click(env, setup_flow.request(env.project))
    assert not (env.project / "runs" / "approval.json").exists()
    assert flowrun.current_state(env.project) == "WAITING_FOR_USER"
    assert "inputs/user/site" in result.message
    assert "upload:site" not in plan_review.load_user_answers(env.project)
    _plan, inventory = flowgate.load().plan.read_artifacts(env.project)
    site = next(it for it in inventory["items"] if it["id"] == "site")
    assert site["local_paths"] == [] and site["status"] == "missing"
    # Re-uploading uses the same binding/review cycle and remains approvable.
    _upload(env)
    _click(env, setup_flow.request(env.project))
    _click(env, setup_flow.request(env.project))
    assert _approval(env)["decisions"]["item:site"]["source"] == "user"


@pytest.mark.parametrize("change", ["delete", "replace"])
def test_upload_changes_during_estimate_refresh_are_checked_before_signing(review_project, monkeypatch, change):
    env = review_project
    card = _draft(env, revise=_needs_upload)
    rel = _upload(env)
    _click(env, card)

    def change_file_during_refresh(*args, **kwargs):
        if change == "delete":
            (env.project / rel).unlink()
        else:
            (env.project / rel).write_text("year,yield\n2003,5.9\n", encoding="utf-8")
        return {}

    monkeypatch.setattr(obs_subset, "refresh_inventory", change_file_during_refresh)
    result = _click(env, setup_flow.request(env.project))
    assert not (env.project / "runs" / "approval.json").exists()
    assert flowrun.current_state(env.project) == "WAITING_FOR_USER"
    answers = plan_review.load_user_answers(env.project)
    if change == "delete":
        assert "upload:site" not in answers and "inputs/user/site" in result.message
    else:
        digest = flowgate.load().receipts.sha256_file(env.project / rel)
        assert answers["upload:site"]["sha256"][rel] == digest and rel in result.message


def test_an_agent_named_missing_path_does_not_satisfy_you_provide(review_project):
    env = review_project

    def missing_path(plan, inventory):
        _needs_upload(plan, inventory)
        inventory["items"][-1]["local_paths"] = ["inputs/user/site/missing.csv"]

    card = _draft(env, revise=missing_path)
    result = _click(env, card)
    assert not (env.project / "runs" / "approval.json").exists()
    assert flowrun.current_state(env.project) == "WAITING_FOR_USER"
    assert "inputs/user/site" in result.message


def test_an_upload_symlink_cannot_bind_a_file_outside_its_input_folder(review_project):
    env = review_project
    card = _draft(env, revise=_needs_upload)
    unrelated = env.project / "unrelated.csv"
    unrelated.write_text("year,yield\n2003,6.1\n", encoding="utf-8")
    upload_folder = env.project / "inputs" / "user" / "site"
    upload_folder.mkdir(parents=True)
    (upload_folder / "site.csv").symlink_to(unrelated)
    result = _click(env, card)
    assert "outside its input folder" in result.message
    assert not (env.project / "runs" / "approval.json").exists()
    assert "upload:site" not in plan_review.load_user_answers(env.project)


def test_local_paths_written_by_the_agent_are_not_credited_to_the_user(tmp_path):
    inv = {"items": [{"id": "site", "decision": "user", "needs_user": True,
                      "local_paths": ["inputs/user/site/x.csv"], "status": "ready"}]}
    recs, _ = plan_review.decision_records(flowrun._flow(), {}, inv, {})
    assert recs["item:site"]["source"] != "user"


def test_a_binding_failure_notice_ends_with_the_approval_it_belongs_to(review_project, monkeypatch):
    """Issue #6b: after Modify the plan, a fresh plan still said "Data needs attention"."""
    from kiss_cli import project_status
    env = review_project
    card = _draft(env)

    def binding_fails(project):
        raise ValueError("the selected scope changed")

    monkeypatch.setattr(obs_subset, "bind_approved", binding_fails)
    _click(env, card)
    snap = project_status.snapshot(env.project)
    assert snap["plan_data"]["binding_status"]["status"] == "needs_review"     # its approval: shown
    assert snap["data_summary"]["label"] == "Data needs attention"
    flowgate.load().approval.revoke(env.project, "user asked to modify the plan")
    snap = project_status.snapshot(env.project)
    assert snap["plan_data"]["binding_status"] == {}
    assert snap["data_summary"]["label"] != "Data needs attention"


# ── DB gating: nothing from the GeoForge Database while access is off or not activated ──

def _db_off_draft(env, revise):
    flowrun.pre(env.project, "Run M for 2003", ["M"], [env.ki], None, None)
    turn = flowrun.turn(env.project, [env.ki], env.cfg, "api", "deepseek", None, "Run M for 2003",
                        database_access_mode="off")
    plan, inventory = turn.session.flow.plan.read_artifacts(env.project)
    for step in plan["steps"]:
        step["kind"] = "run"
        step["tool"] = str(env.ki.root / "tools" / "run.py")
    for item in inventory["items"]:
        item.update(status="resolved", needs_user=False)
    plan["scientific_choices"] = []
    revise(plan, inventory)
    assert turn.session.write_plan(plan, inventory) == []
    return flowrun.after(env.project, turn, "The draft is ready for review.", setup_ok=True)


def test_database_off_refuses_a_plan_that_pins_a_database_dataset(review_project):
    def pins(plan, inventory):
        inventory["items"].append({"id": "forcing", "required_by": ["M"], "status": "resolved",
                                   "acceptable_sources": [], "chosen_source": "source_a",
                                   "dataset_id": "source_a", "local_paths": [],
                                   "agent_resolvable": True, "needs_user": False})
        plan["steps"][0]["inputs"] = list(plan["steps"][0].get("inputs") or []) + ["forcing"]

    result = _db_off_draft(review_project, pins)
    assert result.request is None and result.retry_planning
    assert "forcing" in result.message and "GeoForge Database access is off" in result.message


def test_database_off_card_offers_no_cached_database_records(review_project):
    def external_with_a_cached_alternative(plan, inventory):
        inventory["items"].append({"id": "forcing", "required_by": ["M"], "status": "resolved",
                                   "acceptable_sources": [], "local_paths": [], "chosen_source": "nasa_power",
                                   "agent_resolvable": True, "needs_user": False})
        plan["steps"][0]["inputs"] = list(plan["steps"][0].get("inputs") or []) + ["forcing"]
        plan["scientific_choices"].append({"id": "select-data", "kind": "data_source", "item": "forcing",
                                           "options": ["nasa_power", "source_a"], "picked": "nasa_power",
                                           "high_impact": True})

    result = _db_off_draft(review_project, external_with_a_cached_alternative)
    [row] = result.request["plan_review"]["data_choices"]
    assert [o["dataset_id"] for o in row["options"]] == ["nasa_power"]      # the cached record is not offered


def test_database_off_refuses_a_choice_that_recommends_a_database_record(review_project):
    def recommends_cached(plan, inventory):
        inventory["items"].append({"id": "forcing", "required_by": ["M"], "status": "missing",
                                   "acceptable_sources": [], "local_paths": [],
                                   "agent_resolvable": True, "needs_user": False})
        plan["steps"][0]["inputs"] = list(plan["steps"][0].get("inputs") or []) + ["forcing"]
        plan["scientific_choices"].append({"id": "select-data", "kind": "data_source", "item": "forcing",
                                           "options": ["source_a", "source_b"], "picked": "source_a",
                                           "high_impact": True})

    result = _db_off_draft(review_project, recommends_cached)
    assert result.request is None and "select-data" in result.message


def test_a_reissued_card_follows_the_database_setting_not_direct(review_project, monkeypatch):
    from kiss_cli import settings
    env = review_project
    card = _draft(env, with_data=True, revise=_needs_upload)
    assert card["plan_review"]["data_choices"]                     # activated: records shown
    monkeypatch.setattr(settings, "database_access_mode", lambda *a: "off")
    _upload(env)
    _click(env, card)                                              # binds the upload → re-issue
    assert setup_flow.request(env.project)["plan_review"]["data_choices"] == []


# ── Bug #2 (live Mac test, 2026-09-29): inputs marked resolved with no source reached the card ──

def _submit(env, revise):
    flowrun.pre(env.project, "Run M for 2003", ["M"], [env.ki], None, None)
    turn = flowrun.turn(env.project, [env.ki], env.cfg, "api", "deepseek", None, "Run M for 2003")
    plan, inventory = turn.session.flow.plan.read_artifacts(env.project)
    for step in plan["steps"]:
        step["kind"] = "run"
        step["tool"] = str(env.ki.root / "tools" / "run.py")
    for item in inventory["items"]:
        item.update(status="resolved", needs_user=False)
    plan["scientific_choices"] = []
    revise(plan, inventory)
    assert turn.session.write_plan(plan, inventory) == []
    return flowrun.after(env.project, turn, "The draft is ready for review.", setup_ok=True)


def _stripped(item_id):
    # exactly the shape the live DeepSeek plan left for its CMFD forcing
    return {"id": item_id, "status": "resolved", "needs_user": False, "agent_resolvable": True,
            "required_by": ["M"]}


def test_a_resolved_input_with_no_source_goes_back_to_the_agent(review_project):
    def strip(plan, inventory):
        inventory["items"].append(_stripped("cmfd_3hr_point_2003"))
        plan["steps"][0]["inputs"] = list(plan["steps"][0].get("inputs") or []) + ["cmfd_3hr_point_2003"]

    result = _submit(review_project, strip)
    assert result.request is None and result.retry_planning
    assert "cmfd_3hr_point_2003" in result.message and "names no source" in result.message


@pytest.mark.parametrize("source", [
    {"dataset_id": "source_a", "delivery": "served"}, {"chosen_source": "NASA POWER daily API"},
    {"decision": "the user's station file"}, {"ki_default": {"source_kind": "parameter"}},
])
def test_a_resolved_input_that_names_its_source_is_accepted(review_project, source):
    def sourced(plan, inventory):
        inventory["items"].append({**_stripped("forcing"), **source})
        plan["steps"][0]["inputs"] = list(plan["steps"][0].get("inputs") or []) + ["forcing"]

    assert _submit(review_project, sourced).request is not None


def test_an_input_produced_by_a_step_needs_no_other_source(review_project):
    def produced(plan, inventory):
        inventory["items"].append(_stripped("crop_object"))
        plan["steps"][0]["outputs"] = list(plan["steps"][0].get("outputs") or []) + ["crop_object"]

    assert _submit(review_project, produced).request is not None


# ── Issue #1 (Windows known issue 1; seen on Mac 2026-10-01): the data list decides what is
#    downloaded, the data-source choice is what the card shows and the approval signs ──

def _forcing(plan, inventory, *, item, choice):
    inventory["items"].append({"id": "forcing", "required_by": ["M"], "status": "resolved",
                               "acceptable_sources": [], "local_paths": [],
                               "agent_resolvable": True, "needs_user": False, **item})
    plan["steps"][0]["inputs"] = list(plan["steps"][0].get("inputs") or []) + ["forcing"]
    plan["scientific_choices"].append({"id": "select-data", "kind": "data_source", "item": "forcing",
                                       "high_impact": True, **choice})


def test_a_choice_that_disagrees_with_its_input_goes_back_to_the_agent(review_project):
    """The reproduced shape: the choice recommends NASA POWER, the data list pins CMFD."""
    result = _submit(review_project, lambda p, i: _forcing(
        p, i, item={"dataset_id": "source_a", "chosen_source": "source_a"},
        choice={"options": ["nasa_power", "source_a"], "picked": "nasa_power"}))
    assert result.request is None and result.retry_planning
    assert "select-data" in result.message and "nasa_power" in result.message and "source_a" in result.message


def test_a_pick_that_is_not_one_of_its_options_goes_back_to_the_agent(review_project):
    result = _submit(review_project, lambda p, i: _forcing(
        p, i, item={"dataset_id": "source_a", "chosen_source": "source_a"},
        choice={"options": ["source_a", "source_b"], "picked": "source_c"}))
    assert result.request is None and "not one of its options" in result.message


def _external_first(p, i):
    _forcing(p, i, item={"chosen_source": "nasa_power"},
             choice={"options": ["nasa_power", "source_a"], "picked": "nasa_power"})


def test_a_source_outside_the_database_is_shown_selected_and_signed_as_accepted(review_project):
    env = review_project
    card = _submit(env, _external_first).request
    [row] = card["plan_review"]["data_choices"]
    shown = {o["dataset_id"]: o["delivery"] for o in row["options"]}
    assert shown == {"nasa_power": "external", "source_a": "served"} and row["picked"] == "nasa_power"
    assert _click(env, card).message is None                       # plain Approve, nothing sent
    records = _approval(env)["decisions"]
    assert records["choice:select-data"]["value"] == "nasa_power"
    assert plan_review.is_accepted_suggestion(records["choice:select-data"]["rationale"])
    assert records["item:forcing"]["value"] == "nasa_power"


def test_picking_the_database_option_over_an_external_one_repins_the_input(review_project):
    env = review_project
    card = _submit(env, _external_first).request
    assert "re-pinned" in _click(env, card, choices={"select-data": "source_a"}).message
    _plan, inventory = flowgate.load().plan.read_artifacts(env.project)
    forcing = next(it for it in inventory["items"] if it["id"] == "forcing")
    assert forcing["dataset_id"] == "source_a"
    assert setup_flow.request(env.project)["plan_review"]["data_choices"][0]["picked"] == "source_a"


def test_picking_an_external_option_does_not_pin_it_as_a_database_dataset(review_project):
    env = review_project
    card = _submit(env, lambda p, i: _forcing(
        p, i, item={"dataset_id": "source_a", "chosen_source": "source_a"},
        choice={"options": ["source_a", "nasa_power"], "picked": "source_a"})).request
    assert "re-pinned" in _click(env, card, choices={"select-data": "nasa_power"}).message
    _plan, inventory = flowgate.load().plan.read_artifacts(env.project)
    forcing = next(it for it in inventory["items"] if it["id"] == "forcing")
    assert not forcing.get("dataset_id") and forcing["chosen_source"] == "nasa_power"


def test_a_data_source_decision_with_no_options_is_shown_and_not_called_a_ki_default(review_project):
    """Mac FSM2 run: `output_data_use` was signed as a "KI protocol default" and never shown."""
    env = review_project

    def optionless(plan, inventory):
        plan["scientific_choices"].append({"id": "output_data_use", "kind": "data_source",
                                           "picked": "Shipped example files only", "high_impact": True})

    card = _submit(env, optionless).request
    assert "output_data_use" in [d["id"] for d in card["plan_review"]["decisions"]]
    _click(env, card)
    record = _approval(env)["decisions"]["choice:output_data_use"]
    assert plan_review.is_accepted_suggestion(record["rationale"])


def test_signing_refuses_a_choice_that_differs_from_its_input():
    plan = {"scientific_choices": [{"id": "data:forcing", "kind": "data_source", "item": "forcing",
                                    "options": ["source_a", "source_b"], "decision": "source_b"}]}
    inv = {"items": [{"id": "forcing", "dataset_id": "source_a"}]}
    _recs, invalid = plan_review.decision_records(flowrun._flow(), plan, inv, {})
    assert any("data:forcing" in problem and "source_a" in problem for problem in invalid)


def test_the_card_does_not_call_an_answered_choice_a_default(review_project):
    env = review_project
    plan_review.record_interview_answer(env.project, {"id": "q1", "title": "Scope?"}, {"id": "a", "label": "lohmann"})

    def answered(plan, inventory):
        plan["scientific_choices"].append({"id": "routing", "kind": "routing_scheme", "options": ["lohmann", "cama"],
                                           "picked": "lohmann", "high_impact": True, "answered_by": "interview:q1"})

    card = _submit(env, answered).request
    assert not any("routing" in line and "defaults to" in line for line in card["plan_review"]["blockers"])


def test_approving_the_preselected_external_source_is_not_a_repin(review_project):
    """Mac FSM2 rerun 2026-10-01: the browser sends the pre-checked radio with Approve. The
    input described its source in words ("shipped example forcing …"), the option was an id,
    and accepting the recommendation was treated as a change and the card re-issued."""
    env = review_project
    card = _submit(env, lambda p, i: _forcing(
        p, i, item={"chosen_source": "Shipped example forcing in the installed source tree"},
        choice={"options": ["source_tree_shipped_forcing"], "picked": "source_tree_shipped_forcing"})).request
    before = (env.project / "runs" / "data-inventory.json").read_text(encoding="utf-8")
    result = _click(env, card, choices={"select-data": "source_tree_shipped_forcing"})
    assert result.message is None                                  # approved, no re-issue
    assert (env.project / "runs" / "data-inventory.json").read_text(encoding="utf-8") == before
    assert _approval(env)["decisions"]["choice:select-data"]["value"] == "source_tree_shipped_forcing"
