"""Mixed data acquisition remains visible without promoting file/science evidence."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import acquire, flowgate, flowrun, obs_access, project_status, projectrun
from kiss_cli import setup as setup_flow


@pytest.fixture
def mixed_project(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setattr(obs_access, "load_catalogue", lambda: {"datasets": []})
    monkeypatch.setattr(obs_access, "refresh_catalogue", lambda *a, **k: {"datasets": []})
    def no_network(*args, **kwargs):
        raise AssertionError("status reads must not contact the database")
    monkeypatch.setattr(obs_access, "Client", no_network)
    project = tmp_path / "project"
    (project / "runs").mkdir(parents=True)
    root = tmp_path / "ki" / "M"
    (root / "tools").mkdir(parents=True)
    (root / "dag.yaml").write_text("outputs: []\n")
    tool = root / "tools" / "run.py"
    tool.write_text("raise AssertionError('fixture must not execute')\n")
    fs = flowgate.FlowSession.open(project, {"M": root})
    fs.move("task_received")
    fs.move("kis_resolved", {"selected_kis": ["M"]})
    plan = {"schema_version": "1.0", "goal": "Mixed acquisition fixture", "created_at": "fixture",
            "selected_kis": ["M"], "unresolved_questions": [], "scientific_choices": [],
            "steps": [{"id": "M:run", "ki": "M", "tool": str(tool), "kind": "run",
                       "inputs": ["forcing", "yearbook"], "outputs": ["q"], "status": "planned"}]}
    inventory = {"schema_version": "1.0", "items": [
        {"id": iid, "required_by": ["M"], "status": "resolved", "acceptable_sources": [dataset],
         "chosen_source": dataset, "dataset_id": dataset, "delivery": delivery,
         "local_paths": [], "agent_resolvable": True, "needs_user": False}
        for iid, dataset, delivery in (("forcing", "cmfd_fixture", "subset"),
                                       ("yearbook", "yearbook_fixture", "manual"))]}
    assert fs.write_plan(plan, inventory) == []
    fs.flow.approval.approve(project, by="user")
    fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True})
    fs.move("approved", {"approval": "OK"})
    fs.move("acquire", {"approval": "OK"})
    card = setup_flow.request_user(project, {
        "kind": "download", "title": "Place yearbook_fixture", "message": "Place the selected file.",
        "rows": [{"item_id": "yearbook", "expected_path": "inputs/raw/yearbook_fixture"}],
        "expected_path": "inputs/raw/yearbook_fixture",
    })
    state = {"approval_sha256": fs.approval_id, "status": "waiting", "items": {
        "forcing": {"status": "pending", "delivery": "subset", "dataset_id": "cmfd_fixture",
                    "job_id": "synthetic-job", "job_status": "running"},
        "yearbook": {"status": "waiting", "delivery": "manual", "dataset_id": "yearbook_fixture",
                     "expected_path": "inputs/raw/yearbook_fixture"},
    }}
    acquire._write(project, state)
    return SimpleNamespace(project=project, fs=fs, plan=plan, inventory=inventory, state=state, card=card)


def test_chat_message_displays_automatic_and_manual_work(mixed_project):
    message = flowrun._acquisition_message(mixed_project.state)
    assert "forcing" in message and "running" in message
    assert "inputs/raw/yearbook_fixture" in message
    assert "Nothing runs until" not in message
    assert "model execution" in message.lower()


def test_mixed_projection_preserves_blocker_and_job_observation(mixed_project):
    env = mixed_project
    before = {p.relative_to(env.project): p.read_bytes() for p in env.project.rglob("*") if p.is_file()}
    result = project_status.snapshot(env.project)
    assert not result["errors"]
    progress = result["progress"]
    assert progress["status"] == "working"
    assert progress["next_actor"] == "host_and_user"
    assert "forcing" in progress["summary"] and "yearbook" in progress["summary"]
    assert progress["blocker"] == result["request"]
    assert progress["blocker"]["id"] == env.card["id"]
    view = progress["acquisition"]
    assert view["active"] and view["status"] == "waiting"
    assert view["automatic"] == [{"id": "forcing", "dataset_id": "cmfd_fixture", "status": "pending",
                                  "job_status": "running", "error": None}]
    assert view["manual"] == [{"id": "yearbook", "dataset_id": "yearbook_fixture", "status": "waiting",
                               "expected_path": "inputs/raw/yearbook_fixture"}]
    assert view["counts"] == {"automatic_pending": 1, "automatic_failed": 0,
                               "automatic_acquired": 0, "manual_waiting": 1}
    assert "automatically" in result["data_summary"]["label"]
    assert result["execution"]["downloads_bound"] == 0
    assert not progress["science_complete"]
    assert before == {p.relative_to(env.project): p.read_bytes() for p in env.project.rglob("*") if p.is_file()}


@pytest.mark.parametrize("gate", ["old_approval", "approval_changed", "not_acquiring"])
def test_stale_or_unapproved_acquisition_is_not_active(mixed_project, gate):
    env = mixed_project
    if gate == "old_approval":
        env.state["approval_sha256"] = "previous-approval"
        acquire._write(env.project, env.state)
    elif gate == "approval_changed":
        env.plan["goal"] = "Changed after approval"
        (env.project / "runs/plan.json").write_text(json.dumps(env.plan))
    else:
        env.fs.move("acquired", {"data_receipted": True})
    view = project_status.snapshot(env.project)["progress"]["acquisition"]
    assert not view["active"]
    assert not view["automatic"] and not view["manual"]
    assert not any(view["counts"].values())


def test_done_without_receipt_is_not_acquired(mixed_project):
    env = mixed_project
    env.state["items"]["forcing"].update(status="done", receipt="unverified-path")
    acquire._write(env.project, env.state)
    view = project_status.snapshot(env.project)["progress"]["acquisition"]
    assert view["automatic"][0]["status"] == "unconfirmed"
    assert view["counts"]["automatic_acquired"] == view["counts"]["automatic_pending"] == 0


def _receipt_forcing(env, index=0):
    iid = env.inventory["items"][index]["id"]
    raw = env.project / f"inputs/{iid}.dat"
    raw.parent.mkdir(exist_ok=True)
    raw.write_bytes(b"synthetic data, no scientific validation")
    env.fs.flow.receipts.record_download(
        env.project, item_id=iid, source="fixture", request_url="https://example.test/data",
        http_status=200, raw_files=[raw], approval_sha256=env.fs.approval_id,
        inventory_item=env.inventory["items"][index])
    env.state["items"][iid].update(status="done", error=None)
    acquire._write(env.project, env.state)
    return raw


def _write_during_inspection(monkeypatch, path):
    """Files keep changing while the shared receipt inspector hashes (a copy or download)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    project_status._EVIDENCE_CACHE.clear()
    receipts = flowgate.load().receipts
    real = receipts.inspect_downloads

    def inspect(*args, **kwargs):
        with path.open("ab") as handle:
            handle.write(b"more bytes")
        return real(*args, **kwargs)
    monkeypatch.setattr(receipts, "inspect_downloads", inspect)


def test_receipted_automatic_input_stays_visible_while_manual_input_waits(mixed_project):
    env = mixed_project
    _receipt_forcing(env)
    result = project_status.snapshot(env.project)
    progress = result["progress"]
    assert progress["status"] == "waiting_for_user" and progress["next_actor"] == "user"
    assert progress["acquisition"]["automatic"][0]["status"] == "done"
    assert progress["acquisition"]["counts"]["automatic_acquired"] == 1
    assert progress["acquisition"]["counts"]["manual_waiting"] == 1
    assert not progress["science_complete"]


@pytest.mark.parametrize("job_status", ["https://private.test/?token=SECRET", {"token": "SECRET"}])
def test_acquisition_projection_does_not_forward_remote_secrets(mixed_project, job_status):
    env = mixed_project
    env.state["items"]["forcing"].update(status="failed", job_status=job_status,
        error="Authorization: Bearer SECRET; https://private.test/?X-Amz-Signature=SIGNED",
        url="https://private.test/?token=SECRET", code="PAN-CODE")
    acquire._write(env.project, env.state)
    view = project_status.snapshot(env.project)["progress"]["acquisition"]
    encoded = json.dumps(view)
    assert all(value not in encoded for value in ("SECRET", "SIGNED", "PAN-CODE", "private.test"))
    assert view["automatic"][0]["error"]
    assert view["counts"]["automatic_failed"] == 1


def test_unrelated_question_is_not_replaced_by_mixed_acquisition(mixed_project):
    env = mixed_project
    setup_flow.request_user(env.project, {"kind": "choice", "title": "Choose a scientific assumption",
        "message": "A scientific decision is needed.", "options": [{"id": "one", "label": "Option"}]})
    progress = project_status.snapshot(env.project)["progress"]
    assert progress["status"] == "waiting_for_user" and progress["next_actor"] == "user"
    assert progress["summary"] == "Choose a scientific assumption"


def test_acquisition_pass_summary_does_not_hide_automatic_work(mixed_project, monkeypatch):
    env = mixed_project
    monkeypatch.setattr(acquire, "run", lambda project: env.state)
    recorded = []
    monkeypatch.setattr(flowrun.projectrun, "set_stage", lambda project, stage, summary: recorded.append(summary))
    flowrun._acquire_pass(env.fs.flow, env.fs.ctx, env.project, False)
    assert "forcing" in recorded[0] and "yearbook" in recorded[0]


@pytest.mark.parametrize("growing", [
    "inputs/raw/yearbook_fixture/yearbook.csv",          # manual copy awaiting the user's handoff
    "inputs/geoforge_subsets/.subset-job/part.nc",       # the host's own subset download (obs_subset)
    "inputs/observations/.cmfd_fixture-x1.part",         # the host's own served download (obs_access)
])
def test_unreceipted_work_in_progress_under_inputs_keeps_status_readable(mixed_project, monkeypatch, growing):
    env = mixed_project
    _receipt_forcing(env)
    _write_during_inspection(monkeypatch, env.project / growing)
    result = project_status.snapshot(env.project)
    assert not result["errors"], "an unreceipted file in progress is not evidence yet"
    progress = result["progress"]
    assert progress["status"] == "waiting_for_user"
    assert progress["acquisition"]["automatic"][0]["status"] == "done"
    assert progress["acquisition"]["counts"]["automatic_pending"] == 0


def test_evidence_stamp_filters_waiting_destinations_only_under_inputs(mixed_project, monkeypatch):
    # A per-file Path.is_relative_to over every tree added ~60% to a 30k-file stamp.
    env = mixed_project
    (env.project / "outputs").mkdir()
    for n in range(20):
        (env.project / "outputs" / f"q{n}.nc").write_bytes(b"model output")
    checked, real = [], Path.is_relative_to
    monkeypatch.setattr(Path, "is_relative_to", lambda self, *a: checked.append(self) or real(self, *a))
    stamp = project_status._evidence_stamp(env.project, flowgate.load())
    assert sum("q0.nc" in str(entry[0]) for entry in stamp) == 1
    assert not [p for p in checked if "outputs" in p.parts]


def test_recorded_delivery_is_unconfirmed_not_pending_while_evidence_changes(mixed_project, monkeypatch):
    env = mixed_project
    _receipt_forcing(env)
    _write_during_inspection(monkeypatch, env.project / "outputs/run-1/q.nc")
    result = project_status.snapshot(env.project)
    assert result["errors"]
    view = result["progress"]["acquisition"]
    assert view["automatic"][0]["status"] == "unconfirmed" and view["automatic"][0]["job_status"] is None
    assert view["counts"]["automatic_pending"] == 0, "an acquired input must not restart acquisition ticks"


@pytest.mark.parametrize("observed", ["nothing", "agent_turn", "finished_turn", "run_attempt",
                                      "failed_turn", "failed_report", "manual_file_changed"])
def test_acquired_data_waits_for_an_explicit_start(mixed_project, observed):
    env = mixed_project
    _receipt_forcing(env)
    manual = _receipt_forcing(env, 1)
    setup_flow.clear_request(env.project)
    env.fs.move("acquired", {"data_receipted": True})
    env.fs.move("execution_started", {"setup_verified": True})
    activity = {"state": "running", "process_alive": True} if observed == "agent_turn" else None
    if observed in {"finished_turn", "run_attempt", "failed_turn"}:
        # An execution turn ran after acquisition finished (preparing inputs, asking in prose).
        projectrun.begin_turn(env.project, "Start the approved run.", ["M"])
        if observed == "run_attempt":
            tool = env.plan["steps"][0]["tool"]
            env.fs.flow.receipts.record_run(
                env.project, ki="M", executable=tool, command=[tool], cwd=str(env.project),
                started_at=1.0, finished_at=2.0, exit_code=1, inputs=[], outputs=[],
                approval_sha256=env.fs.approval_id, plan_step_id="M:run")
        projectrun.finish_turn(env.project, failed="Synthetic agent failure" if observed == "failed_turn" else None)
    if observed == "manual_file_changed":                  # never "data acquired" over a broken receipt
        manual.write_bytes(b"replaced after signing")
    # An agent-reported failure outranks "ready to start", even one with no timestamp.
    report = {"status": "failed"} if observed == "failed_report" else None
    progress = project_status.snapshot(env.project, report=report, activity=activity)["progress"]
    assert progress["flow_state"] == "EXECUTING"
    assert progress["ready_to_start"] is (observed == "nothing")
    if observed == "nothing":
        assert (progress["status"], progress["next_actor"]) == ("waiting_for_user", "user")
        assert "Start the approved run" in progress["summary"]
    elif observed in {"failed_turn", "failed_report"}:
        assert (progress["status"], progress["next_actor"]) == ("failed", "agent")
    else:
        assert progress["next_actor"] == "agent"
