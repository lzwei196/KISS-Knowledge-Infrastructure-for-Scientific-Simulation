"""Project status must distinguish activity, delivered bytes and scientific proof.

These are isolated source-level lifecycles: real shared Flow state/approval and
receipt interfaces, but fixture files only. No scientific executable, provider,
database client or download is launched.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from kiss_cli import acquire, flowgate, flowrun, obs_access, obs_subset, plan_review, projectrun
from kiss_cli import setup as setup_flow


@pytest.fixture
def status_project(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setattr(obs_access, "load_catalogue", lambda: {"datasets": []})
    monkeypatch.setattr(obs_access, "refresh_catalogue", lambda *a, **k: {"datasets": []})

    def no_network(*args, **kwargs):
        raise AssertionError("status reads must not contact the database")

    monkeypatch.setattr(obs_access, "Client", no_network)
    project = tmp_path / "project"
    (project / "runs").mkdir(parents=True)
    root = tmp_path / "kis" / "M"
    (root / "tools").mkdir(parents=True)
    (root / "dag.yaml").write_text("outputs: []\n", encoding="utf-8")
    tool = root / "tools" / "run.py"
    tool.write_text("raise AssertionError('fixture tool must not run')\n", encoding="utf-8")
    fs = flowgate.FlowSession.open(project, {"M": root})
    fs.move("task_received")
    fs.move("kis_resolved", {"selected_kis": ["M"]})
    plan = {
        "schema_version": "1.0", "goal": "Status lifecycle fixture", "created_at": "fixture",
        "selected_kis": ["M"], "unresolved_questions": [], "scientific_choices": [],
        "steps": [{"id": "M:run", "ki": "M", "tool": str(tool), "kind": "run",
                   "inputs": ["forcing"], "outputs": ["q"], "status": "planned"}],
    }
    inventory = {"schema_version": "1.0", "items": [{
        "id": "forcing", "required_by": ["M"], "status": "resolved",
        "acceptable_sources": ["source_a"], "chosen_source": "source_a",
        "dataset_id": "source_a", "delivery": "served", "local_paths": [],
        "agent_resolvable": True, "needs_user": False,
    }]}
    assert fs.write_plan(plan, inventory) == []
    return SimpleNamespace(project=project, fs=fs, flow=fs.flow, plan=plan,
                           inventory=inventory, tool=tool)


def _save(env):
    assert env.fs.write_plan(env.plan, env.inventory) == []


def _approve(env):
    env.flow.approval.approve(env.project, by="user")
    env.fs.reload_artifacts()
    env.fs.move("plan_written", {"plan_valid": True})
    env.fs.move("approved", {"approval": "OK"})


def _evidence(env):
    return env.flow.receipts.evidence(
        env.project, env.plan, env.flow.approval.read(env.project), inventory=env.inventory)


def _download(env, *, acquisition=None):
    raw = env.project / "inputs" / "forcing.dat"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(b"fixture downloaded bytes, scientific inspection still pending")
    receipt = env.flow.receipts.record_download(
        env.project, item_id="forcing", source="fixture", request_url="https://example.test/data",
        http_status=200, raw_files=[raw], approval_sha256=env.fs.approval_id,
        inventory_item=env.inventory["items"][0], acquisition=acquisition)
    return raw, receipt


def _run_receipt(env, *, passed):
    output = env.project / "outputs" / "q.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("t,q\n1,0.5\n", encoding="utf-8")
    return env.flow.receipts.record_run(
        env.project, ki="M", executable=str(env.tool), command=[str(env.tool)],
        cwd=str(env.project), started_at=1.0, finished_at=2.0,
        exit_code=0 if passed else 1, inputs=[], outputs=[output],
        approval_sha256=env.fs.approval_id, plan_step_id="M:run",
        execution_status="succeeded" if passed else "failed", process_started=True,
        validation={"status": "passed" if passed else "failed", "checks": []})


def test_pending_review_survives_idle_chat_and_remains_unsigned(status_project):
    env = status_project
    env.fs.move("plan_written", {"plan_valid": True})
    card = plan_review.issue(env.project, env.fs, env.plan, env.inventory, "fixture provider")
    projectrun.finish_turn(env.project, request=card)

    assert setup_flow.request(env.project)["id"] == card["id"]
    assert projectrun.load(env.project)["status"] == "waiting_for_user"
    assert flowrun.current_state(env.project) == "WAITING_FOR_USER"
    assert env.flow.approval.read(env.project) is None
    assert not _evidence(env)["receipts_verified"]


def test_manual_download_names_the_input_waiting_for_user(status_project):
    env = status_project
    env.inventory["items"][0]["delivery"] = "manual"
    _save(env)
    _approve(env)
    env.fs.move("acquire", {"approval": "OK"})
    card = setup_flow.request_user(env.project, {
        "kind": "download", "title": "Download source_a", "message": "Place the source files.",
        "expected_path": str(env.project / "inputs/raw/source_a"),
    })
    projectrun.finish_turn(env.project, request=card)

    row = flowrun.plan_data_status(env.project)["items"][0]
    assert row["id"] == "forcing" and row["status"] == "waiting_for_you"
    assert row["action"] == "manual_download"
    assert projectrun.load(env.project)["blocker"]["id"] == card["id"]
    assert not _evidence(env)["receipts_verified"]


@pytest.mark.parametrize("remote_status", ["pending", "failed"])
def test_remote_acquisition_state_does_not_become_success(status_project, remote_status):
    env = status_project
    env.inventory["items"][0]["delivery"] = "subset"
    _save(env)
    _approve(env)
    env.fs.move("acquire", {"approval": "OK"})
    state = {"approval_sha256": env.fs.approval_id, "status": remote_status, "items": {
        "forcing": {"status": remote_status, "job_id": "fixture-job",
                    "error": "fixture failure" if remote_status == "failed" else ""}}}
    path = env.project / acquire.STATUS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")

    assert acquire.status(env.project)["items"]["forcing"]["status"] == remote_status
    if remote_status == "failed":
        assert flowrun.plan_data_status(env.project)["items"][0]["status"] == "failed"
    assert _evidence(env)["downloads_bound"] == 0
    assert _evidence(env)["validation"] == "incomplete"


def test_local_file_presence_is_not_a_validated_scientific_run(status_project):
    env = status_project
    raw = env.project / "inputs" / "local.csv"
    raw.parent.mkdir()
    raw.write_text("t,value\n1,12\n", encoding="utf-8")
    env.inventory["items"][0].update(status="ready", local_paths=[str(raw)])
    _save(env)
    _approve(env)

    # The legacy display's `done` wording is intentionally not asserted here:
    # existing bytes prove presence, not acquisition integrity or scientific use.
    proof = _evidence(env)
    assert proof["downloads_bound"] == 0
    assert proof["steps_missing"] == ["M:run"]
    assert proof["validation"] == "incomplete" and not proof["receipts_verified"]


def test_acquired_input_stays_scientifically_unvalidated(status_project):
    env = status_project
    class EstimateClient:
        def _json(self, route, **kwargs):
            assert route == "/subsets/estimate"
            return {"subsettable": True, "estimated_output_bytes": 100,
                    "over_output_cap": False, "coverage_complete": True,
                    "missing": [], "transformations": [], "variables": ["prec"],
                    "snapped_output_bounds": [115, 37, 116, 38]}

    estimate = obs_subset.estimate(
        env.project, {"dataset_id": "source_a", "bbox": [115, 37, 116, 38],
                      "variables": ["prec"]}, client=EstimateClient())
    env.inventory["items"][0].update(delivery="subset", acquisition_id=estimate["id"])
    _save(env)
    _approve(env)
    _download(env, acquisition={"id": estimate["id"], "scientific_validation": "pending"})

    row = flowrun.plan_data_status(env.project)["items"][0]
    assert row["status"] == "acquired" and row["action"] == "agent_validate"
    assert row["scientific_validation"] == "pending"
    proof = _evidence(env)
    assert proof["downloads_bound"] == 1
    assert proof["validation"] == "incomplete" and not proof["receipts_verified"]


def test_failed_receipted_attempt_remains_failed_when_chat_finishes(status_project):
    env = status_project
    _approve(env)
    _download(env)
    env.fs.move("execution_started", {"setup_verified": True})
    projectrun.begin_turn(env.project, "Run the approved step", ["M"])
    _run_receipt(env, passed=False)
    projectrun.finish_turn(env.project)

    assert projectrun.load(env.project)["status"] == "idle"
    proof = _evidence(env)
    assert proof["runs_bound"] == 1 and proof["validation"] == "failed"
    assert proof["steps_missing"] == ["M:run"] and not proof["receipts_verified"]


def test_idle_chat_is_not_project_completion(status_project):
    env = status_project
    _approve(env)
    env.fs.move("execution_started", {"setup_verified": True})
    projectrun.begin_turn(env.project, "Continue", ["M"])
    projectrun.finish_turn(env.project)

    assert projectrun.load(env.project)["status"] == "idle"
    assert flowrun.current_state(env.project) == "EXECUTING"
    assert _evidence(env)["validation"] == "incomplete"


def test_completion_requires_current_approval_evidence(status_project):
    env = status_project
    _approve(env)
    _download(env)
    env.fs.move("execution_started", {"setup_verified": True})
    _run_receipt(env, passed=True)
    proof = _evidence(env)
    assert proof["validation"] == "passed" and proof["receipts_verified"]
    env.fs.move("run_finished")
    env.fs.move("validated", proof)
    assert flowrun.current_state(env.project) == "COMPLETED"

    # An old successful attempt cannot count toward a newly issued approval.
    env.flow.approval.approve(env.project, by="user")
    fresh = _evidence(env)
    assert fresh["runs_bound"] == 0 and fresh["validation"] == "incomplete"
    assert not fresh["receipts_verified"]


def _snapshot(env, **kwargs):
    from kiss_cli import project_status
    return project_status.snapshot(env.project, **kwargs)


def test_snapshot_does_not_accept_agent_claim_of_completion(status_project):
    env = status_project
    result = _snapshot(env, report={
        "status": "complete", "stage": "results", "summary": "Everything is complete",
        "selected_kis": ["M"],
    })

    assert result["progress"]["status"] != "complete"
    assert result["progress"]["stage"] == "preparing"
    assert result["progress"]["summary"] != "Everything is complete"
    assert result["request"] is None


def test_snapshot_uses_active_request_not_stale_report_blocker(status_project):
    env = status_project
    stale = {"status": "waiting_for_user", "summary": "Old download",
             "blocker": {"id": "stale-blocker", "status": "waiting", "title": "Old download"}}
    result = _snapshot(env, report=stale)
    assert result["request"] is None
    assert not result["progress"].get("blocker")

    active = setup_flow.request_user(env.project, {
        "kind": "download", "title": "Current source needed", "message": "Place the current input.",
    })
    result = _snapshot(env, report={"status": "working", "summary": "All fine"})
    assert result["request"]["id"] == active["id"]
    assert result["progress"]["status"] == "waiting_for_user"
    assert result["progress"]["blocker"]["id"] == active["id"]


def test_snapshot_local_files_are_present_not_scientifically_verified(status_project):
    env = status_project
    raw = env.project / "inputs" / "local.csv"
    raw.parent.mkdir()
    raw.write_text("t,value\n1,12\n", encoding="utf-8")
    env.inventory["items"][0].update(status="ready", local_paths=[str(raw)])
    _save(env)
    _approve(env)

    result = _snapshot(env)
    row = result["plan_data"]["items"][0]
    assert row["status"] == "present_unverified"
    assert result["progress"]["status"] != "complete"


def test_snapshot_served_receipt_means_acquired_not_scientifically_done(status_project):
    env = status_project
    _approve(env)
    _download(env)

    result = _snapshot(env)
    row = result["plan_data"]["items"][0]
    assert row["status"] == "acquired"
    assert result["progress"]["status"] != "complete"


def test_snapshot_does_not_trust_unsigned_generated_output_summary(status_project):
    env = status_project
    env.inventory["items"].append({
        "id": "q", "required_by": ["M"], "status": "resolved", "acceptable_sources": [],
        "local_paths": [], "agent_resolvable": True, "needs_user": False,
    })
    _save(env)
    _approve(env)
    (env.project / "runs/evidence.json").write_text(json.dumps({
        "steps_passed": ["M:run"], "validation": "passed", "receipts_verified": True,
    }), encoding="utf-8")

    result = _snapshot(env, report={"status": "complete", "summary": "All results verified"})
    generated = next(row for row in result["plan_data"]["items"] if row["id"] == "q")
    assert generated["status"] != "produced"
    assert result["progress"]["status"] != "complete"


def test_snapshot_generated_output_uses_current_signed_step_proof(status_project):
    env = status_project
    env.inventory["items"].append({
        "id": "q", "required_by": ["M"], "status": "resolved", "acceptable_sources": [],
        "local_paths": [], "agent_resolvable": True, "needs_user": False,
    })
    _save(env)
    _approve(env)
    _download(env)
    env.fs.move("execution_started", {"setup_verified": True})
    _run_receipt(env, passed=True)

    result = _snapshot(env)
    generated = next(row for row in result["plan_data"]["items"] if row["id"] == "q")
    assert generated["status"] == "produced"
    # Producing this output is not itself the authoritative COMPLETED transition.
    assert result["progress"]["status"] != "complete"


def test_snapshot_completed_flow_uses_fresh_approval_bound_evidence(status_project):
    env = status_project
    _approve(env)
    _download(env)
    env.fs.move("execution_started", {"setup_verified": True})
    _run_receipt(env, passed=True)
    env.fs.move("run_finished")
    env.fs.move("validated", _evidence(env))

    result = _snapshot(env, report={"status": "idle", "summary": "Ready to continue"})
    assert result["progress"]["status"] == "complete"
    assert result["progress"]["stage"] == "results"

    # The saved Flow label and stale unsigned evidence cannot hide re-issuance.
    env.flow.approval.approve(env.project, by="user")
    result = _snapshot(env, report={"status": "complete", "summary": "Everything done"})
    assert result["progress"]["status"] != "complete"


def test_snapshot_failed_attempt_overrides_finished_chat_claim(status_project):
    env = status_project
    _approve(env)
    _download(env)
    env.fs.move("execution_started", {"setup_verified": True})
    _run_receipt(env, passed=False)

    result = _snapshot(env, report={"status": "complete", "summary": "The chat finished"})
    assert result["progress"]["status"] == "failed"
    assert result["progress"]["summary"] != "The chat finished"


def test_snapshot_reads_do_not_write_or_advance_project(status_project):
    env = status_project
    _approve(env)
    _download(env)
    env.fs.move("acquire", {"approval": "OK"})

    def files():
        return {path.relative_to(env.project).as_posix(): path.read_bytes()
                for path in env.project.rglob("*") if path.is_file()}

    before = files()
    first = _snapshot(env)
    second = _snapshot(env)

    assert files() == before
    assert flowrun.current_state(env.project) == "ACQUIRING"
    assert first["request"] == second["request"]
    assert first["plan_data"] == second["plan_data"]


def test_session_data_reuses_one_status_projection(status_project, monkeypatch):
    """The real HTTP handler method can be checked without binding a socket."""
    from kiss_cli import gui, project_status, sessions

    env = status_project
    handler = object.__new__(gui.Handler)
    handler.workroot = env.project.parent
    handler._setup_ok_for = lambda _session: True
    report = {"status": "complete", "summary": "Unverified agent claim", "selected_kis": []}
    preparation = {"active": True, "lanes": []}
    activity = {"state": "running", "process_alive": True}
    projected = {
        "progress": {"status": "waiting_for_user", "summary": "Canonical request"},
        "request": {"id": "canonical", "status": "waiting"},
        "plan_data": {"items": [{"id": "forcing", "status": "pending"}]},
        "data_summary": {"severity": "warn"}, "technical": {}, "observations": [],
    }
    calls = []
    polls = []

    def snapshot(project, **kwargs):
        calls.append((project, kwargs))
        return projected

    def independent_status(*args, **kwargs):
        raise AssertionError("the handler must not reconstruct status outside its snapshot")

    monkeypatch.setattr(sessions, "project_path", lambda *a: env.project)
    monkeypatch.setattr(sessions, "input_files", lambda *a: [])
    monkeypatch.setattr(sessions, "reference_files", lambda *a: [])
    monkeypatch.setattr(sessions, "provenance_records", lambda *a: [])
    monkeypatch.setattr(projectrun, "load", lambda *a, **k: report)
    monkeypatch.setattr(gui.preparation, "build", lambda *a, **k: preparation)
    monkeypatch.setattr(gui.calibration, "project_state", lambda *a, **k: {})
    monkeypatch.setattr(gui, "_agent_run_snapshot", lambda _id: activity)
    monkeypatch.setattr(flowrun, "poll_acquisition", lambda *a, **k: polls.append((a, k)))
    monkeypatch.setattr(flowrun, "plan_data_status", independent_status)
    monkeypatch.setattr(setup_flow, "request", independent_status)
    monkeypatch.setattr(project_status, "snapshot", snapshot)

    result = handler._session_data({"id": "fixture-session", "models": []})

    assert len(calls) == 1 and len(polls) == 1
    assert calls[0][0] == env.project
    assert calls[0][1] == {"report": report, "plans": [], "preparation": preparation,
                           "activity": activity}
    assert result["project_status"] is projected
    assert result["project_run"] is projected["progress"]
    assert result["human_request"] is projected["request"]
    assert result["plan_data"] is projected["plan_data"]


def test_all_failed_inputs_block_data_summary(status_project):
    env = status_project
    _approve(env)
    env.fs.move("acquire", {"approval": "OK"})
    path = env.project / acquire.STATUS_FILE
    path.write_text(json.dumps({"approval_sha256": env.fs.approval_id, "status": "failed", "items": {
        "forcing": {"status": "failed", "error": "fixture server failure"}}}), encoding="utf-8")

    result = _snapshot(env)

    assert result["plan_data"]["counts"] == {"failed": 1}
    assert result["data_summary"]["severity"] == "block"
    assert result["data_summary"]["available"] == 0
    assert result["technical"]["overall"]["cls"] == "block"
    assert result["progress"]["status"] == "failed"


def test_failed_acquisition_is_not_hidden_by_leftover_local_bytes(status_project):
    env = status_project
    raw = env.project / "inputs" / "partial.dat"
    raw.parent.mkdir()
    raw.write_bytes(b"leftover bytes from an interrupted transfer")
    env.inventory["items"][0]["local_paths"] = [str(raw)]
    _save(env)
    _approve(env)
    env.fs.move("acquire", {"approval": "OK"})
    (env.project / acquire.STATUS_FILE).write_text(json.dumps({
        "approval_sha256": env.fs.approval_id, "status": "failed", "items": {
        "forcing": {"status": "failed", "error": "download integrity failed"}}}), encoding="utf-8")

    result = _snapshot(env)

    assert result["progress"]["status"] == "failed"
    assert result["plan_data"]["items"][0]["status"] != "acquired"
    assert result["data_summary"]["severity"] == "block"
    assert result["technical"]["overall"]["cls"] == "block"


def test_running_flow_does_not_make_declared_technical_lanes_ready(status_project):
    env = status_project
    _approve(env)
    env.fs.move("execution_started", {"setup_verified": True})
    result = _snapshot(env, report={"stage": "running", "status": "working"},
                       preparation={"lanes": [{"id": "source_data"}, {"id": "model_inputs"}]})

    assert result["progress"]["flow_state"] == "EXECUTING"
    assert result["technical"]["lanes"]["source_data"]["label"] == "Readiness unconfirmed"
    assert result["technical"]["lanes"]["model_inputs"]["label"] == "Readiness unconfirmed"
    assert all(lane["cls"] != "ready" for lane in result["technical"]["lanes"].values())
    assert not result["progress"]["science_complete"]


@pytest.mark.parametrize("alive", [True, False])
def test_activity_observation_is_not_scientific_completion(status_project, alive):
    env = status_project
    _approve(env)
    env.fs.move("execution_started", {"setup_verified": True})
    result = _snapshot(env, report={"status": "complete", "summary": "Agent claims success"},
                       activity={"state": "running", "process_alive": alive,
                                 "event_silence_seconds": 25, "activity_detail": "Provider heartbeat"})

    assert result["progress"]["status"] == ("working" if alive else "idle")
    assert not result["progress"]["science_complete"]
    observation = next(item for item in result["observations"] if "Provider activity" in item["source"])
    assert observation["age_seconds"] == 25
    assert "not model progress" in observation["source"]


@pytest.mark.parametrize("corruption", ["missing", "malformed", "forged"])
def test_unreadable_flow_state_never_reports_success(status_project, corruption):
    env = status_project
    path = env.project / "runs/flow-state.json"
    if corruption == "missing":
        path.unlink()
    elif corruption == "malformed":
        path.write_text("{broken", encoding="utf-8")
    else:
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["state"] = "COMPLETED"
        path.write_text(json.dumps(doc), encoding="utf-8")

    result = _snapshot(env, report={"status": "complete", "stage": "results"})

    assert result["errors"]
    assert result["data_summary"]["severity"] == "block"
    assert result["progress"]["status"] != "complete"
    assert not result["progress"]["science_complete"]


@pytest.mark.parametrize("answers", [None, "{broken"])
def test_missing_or_malformed_answers_do_not_approve_or_consume_review(status_project, answers):
    env = status_project
    env.fs.move("plan_written", {"plan_valid": True})
    card = plan_review.issue(env.project, env.fs, env.plan, env.inventory, "fixture provider")
    path = env.project / ".geoforge/user-answers.json"
    if answers is not None:
        path.write_text(answers, encoding="utf-8")

    result = _snapshot(env, report={"status": "complete", "summary": "The user approved"})

    assert result["request"]["id"] == card["id"]
    assert result["progress"]["status"] == "waiting_for_user"
    assert not result["progress"]["science_complete"]
    assert env.flow.approval.read(env.project) is None
    assert setup_flow.request(env.project)["id"] == card["id"]
    if answers is not None:
        assert path.read_text(encoding="utf-8") == answers


def test_status_read_does_not_archive_legacy_kimi_runtime_permission(status_project, monkeypatch):
    from kiss_cli import kimi_security

    env = status_project
    monkeypatch.setattr(kimi_security, "is_runtime_read_path", lambda _path: True)
    setup_flow.request_user(env.project, {
        "kind": "permission", "title": "Legacy runtime discovery permission",
        "message": "This runtime path is now handled without a permission popup.",
        "expected_path": "/fixture/runtime/skills",
    })
    before = {path.relative_to(env.project).as_posix(): path.read_bytes()
              for path in env.project.rglob("*") if path.is_file()}

    result = _snapshot(env)

    after = {path.relative_to(env.project).as_posix(): path.read_bytes()
             for path in env.project.rglob("*") if path.is_file()}
    assert after == before
    assert result["request"] is None


def test_invalid_utf8_human_request_is_reported_not_raised(status_project):
    env = status_project
    (env.project / setup_flow.REQUEST_FILE).write_bytes(b"\xff\xfe\x00corrupt request")

    result = _snapshot(env, report={"status": "complete", "summary": "Everything finished"})

    assert result["errors"]
    assert result["request"] is None
    assert result["progress"]["status"] != "complete"
    assert not result["progress"]["science_complete"]
    assert result["data_summary"]["severity"] == "block"


@pytest.mark.parametrize("old_binding", [True, False])
def test_old_or_unbound_acquisition_failure_is_historical_after_new_approval(status_project, old_binding):
    env = status_project
    _approve(env)
    old_approval = env.fs.approval_id
    stale = {"status": "failed", "items": {
        "forcing": {"status": "failed", "error": "historical source failed"}}}
    if old_binding:
        stale["approval_sha256"] = old_approval
    (env.project / acquire.STATUS_FILE).write_text(json.dumps(stale), encoding="utf-8")
    env.flow.approval.approve(env.project, by="user")
    env.fs.reload_artifacts()
    assert env.fs.approval_id != old_approval

    result = _snapshot(env)

    assert result["progress"]["status"] != "failed"
    assert result["data_summary"]["severity"] != "block"
    assert result["plan_data"]["items"][0]["status"] != "failed"
    assert result["acquisition"].get("status") != "failed"
    assert "historical source failed" in json.dumps(result["acquisition_history"])
    if old_binding:
        assert old_approval in json.dumps(result["acquisition_history"])
