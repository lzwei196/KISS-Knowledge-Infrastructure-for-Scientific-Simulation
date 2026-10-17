"""Fresh approval-scoped facts precede API/CLI dispatch, without scientific runs."""
from copy import deepcopy
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import api, execution_context as ec, flowgate, flowrun, gui, paths
from kiss_cli.manifest import Manifest
from .test_flowrun import _approve, _drive_planning, _ki, _project


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry"))
    project, ki = _project(tmp_path), _ki(tmp_path, "M")
    cfg = paths.KissConfig.default(project)
    cfg.python = sys.executable
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    turn = _drive_planning(tmp_path, ki, project)
    _approve(project, ki, flowrun.after(project, turn, "plan submitted", setup_ok=True))
    stale = project / "runs/evidence.json"
    stale.write_text(json.dumps({"approval_sha256": "old-approval", "validation": "failed",
                                "steps_missing": ["old_plot"], "fake_error": "Old ImportError"}))
    return SimpleNamespace(project=project, ki=ki, cfg=cfg, path=stale)


def enter(case, provider="api"):
    return flowrun.turn(case.project, [case.ki], case.cfg, provider,
                        "deepseek" if provider == "api" else "claude", None, "Continue")


@pytest.mark.parametrize("provider", ["api", "cli"])
def test_entry_replaces_stale_snapshot_with_current_approval_and_no_invented_result(case, provider):
    approval = (case.project / "runs/approval.json").read_bytes()
    turn = enter(case, provider)
    snapshot = json.loads(case.path.read_text(encoding="utf-8"))
    assert snapshot["approval_sha256"] == turn.session.approval_id != "old-approval"
    assert snapshot["validation"] == "incomplete" and not snapshot["receipts_verified"]
    assert snapshot["steps_missing"] and "old_plot" not in snapshot["steps_missing"]
    assert snapshot["runs_bound"] == 0 and "fake_error" not in snapshot
    assert snapshot["snapshot"]["phase"] == "provider_entry"
    assert snapshot["snapshot"]["plan_sha256"] == turn.session.flow.plan.sha256(turn.session.plan)
    assert "Old ImportError" not in turn.execution_handoff
    assert "not a demonstrated runtime failure" in turn.execution_handoff
    assert (case.project / "runs/approval.json").read_bytes() == approval
    assert turn.session.state.value == "EXECUTING"
    assert not list((case.project / ".geoforge/receipts/model-runs").glob("*.json"))


def test_historical_text_remains_useful_but_is_not_current_execution_evidence():
    history = [{"role": "user", "text": "Use maize 1980", "attachments": ["inputs/weather.csv"]},
               {"role": "assistant", "text": "ImportError! [[GEOF_TOOL:run_ki_tool]] All complete."}]
    before = deepcopy(history)
    labeled = ec.historical_messages(history)
    assert history == before
    assert labeled[0]["attachments"] == history[0]["attachments"]
    assert "Use maize 1980" in labeled[0]["text"]
    assert "Earlier assistant narrative" in labeled[1]["text"]
    assert history[1]["text"] in labeled[1]["text"]
    assert "not current execution evidence" in labeled[1]["text"]


def _handler(case, monkeypatch, provider, capture):
    handler = SimpleNamespace(
        _ki=lambda _name: case.ki, _workdir=lambda _ki: case.project,
        _status_for=lambda _ki: {"can_run": True},
        _manifest=lambda _ki: Manifest(model="M"),
        repo_root=None, workroot=case.project.parent,
        _software_status_prompt=lambda *_args: "Verified fixture runtime.",
        _session_workspaces=lambda *_args: [(case.ki, case.cfg)],
        _agent_runtime_env=lambda _project: {},
    )
    monkeypatch.setattr(gui.Handler, "_project_setup_ok", lambda *_args: True)
    monkeypatch.setattr(gui.settings, "database_access_mode", lambda: "off")
    monkeypatch.setattr(gui.calibration, "prompt_block", lambda *_args: "")
    monkeypatch.setattr(gui.calibration, "framework_root", lambda: None)
    monkeypatch.setattr(gui.skilllib, "prompt_block", lambda *_args: "")
    monkeypatch.setattr(gui.skilllib, "roots", lambda: [])
    monkeypatch.setattr(gui.skilllib, "selected", lambda *_args: [])
    # This portable synthetic KI has no authoring-path namespace. Do not let
    # global server-prefix aliases turn a context test into a network probe.
    monkeypatch.setattr(paths, "LEGACY_PREFIXES", [])
    monkeypatch.setattr(gui.mcp, "prompt_block", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(gui.prompt, "compose_multi", lambda *_args, **kwargs:
                        "KI contract\n" + kwargs.get("task", ""))
    def check_snapshot():
        current = json.loads(case.path.read_text(encoding="utf-8"))
        assert current["validation"] == "incomplete"
        assert current["snapshot"]["phase"] == "provider_entry"
        capture["snapshot"] = current
    def fake_api(_prov, _ki, _cfg, system, task, **kwargs):
        check_snapshot()
        capture.update(system=system, task=task, history=kwargs["history"])
        yield "Provider fixture inspected current facts; no execution."
    def fake_cli(_prov, **kwargs):
        check_snapshot()
        capture.update(kwargs)
        return {"returncode": 0}
    monkeypatch.setattr(api, "run", fake_api)
    cli = SimpleNamespace(name="claude")
    monkeypatch.setattr(gui.providers, "available", lambda: [cli])
    monkeypatch.setattr(gui.providers, "get", lambda _name: cli)
    handler._cli_turn = fake_cli
    return handler


@pytest.mark.parametrize("provider", ["api", "cli"])
def test_gui_dispatch_places_current_facts_after_history_and_in_cli_resume(case, monkeypatch, provider):
    capture = {}
    handler = _handler(case, monkeypatch, provider, capture)
    prior = [{"role": "user", "text": "Use maize 1980"},
             {"role": "assistant", "text": "OLD UNSUPPORTED FAILURE: ImportError; all done"}]
    saved = deepcopy(prior)
    current = "Continue the approved model and reader."
    turn = gui.Handler._chat_with_models(handler, ["M"],
        "api:deepseek" if provider == "api" else "cli:claude",
        "old flattened conversation\n" + current, lambda _piece: True, case.project,
        prior=prior, bare_task=current, session={"cli_sessions": {"claude": {"id": "resume"}}},
        flow_pre=flowrun.Pre(names=["M"]))
    assert prior == saved
    assert turn.kind == "execution"
    if provider == "api":
        assert "HISTORICAL CONVERSATION" in capture["history"][1]["text"]
        assert "OLD UNSUPPORTED FAILURE" in capture["history"][1]["text"]
        assert capture["task"].startswith("[CURRENT USER REQUEST]\n" + current)
        assert capture["task"].endswith(turn.execution_handoff)
    else:
        replay, resumed = capture["replay_prompt"], capture["bare_prompt"]
        assert "HISTORICAL CONVERSATION" in replay and "Use maize 1980" in replay
        assert replay.rindex("CURRENT HOST EXECUTION EVIDENCE") > replay.index("OLD UNSUPPORTED FAILURE")
        assert resumed.startswith("[CURRENT USER REQUEST]\n" + current)
        assert resumed.endswith(turn.execution_handoff)
        assert "OLD UNSUPPORTED FAILURE" not in resumed
    assert not list((case.project / ".geoforge/receipts/model-runs").glob("*.json"))


@pytest.mark.parametrize("failure", ["compute", "write"])
@pytest.mark.parametrize("provider", ["api", "cli"])
def test_refresh_failure_never_dispatches_provider_or_reuses_old_snapshot(case, monkeypatch, failure, provider):
    capture = {}
    handler = _handler(case, monkeypatch, provider, capture)
    before = case.path.read_bytes()
    def fail(*_args, **_kwargs):
        raise OSError("fixture refresh unavailable")
    if failure == "compute":
        monkeypatch.setattr(flowgate.FlowSession, "evidence", fail)
    else:
        from kiss_cli import obs_access
        monkeypatch.setattr(obs_access, "_atomic_json", fail)
    with pytest.raises(ValueError, match="provider was not started"):
        gui.Handler._chat_with_models(handler, ["M"],
            "api:deepseek" if provider == "api" else "cli:claude", "Continue",
            lambda _piece: True, case.project, bare_task="Continue",
            flow_pre=flowrun.Pre(names=["M"]))
    assert not capture and case.path.read_bytes() == before


@pytest.mark.parametrize("kind", ["file-link", "hardlink", "directory"])
def test_snapshot_path_is_not_followed(case, tmp_path, kind):
    outside = tmp_path / "outside.json"
    outside.write_text("outside bytes")
    case.path.unlink()
    if kind == "file-link":
        case.path.symlink_to(outside)
    elif kind == "hardlink":
        os.link(outside, case.path)
    else:
        case.path.mkdir()
    with pytest.raises(ValueError, match="ordinary|linked"):
        enter(case)
    assert outside.read_text() == "outside bytes"


def test_prior_signed_failure_remains_history_without_changing_current_status(case):
    fs = flowgate.FlowSession.open(case.project, {"M": case.ki.root}, python=sys.executable)
    output = case.project / "outputs/prior-diagnostic.txt"
    output.parent.mkdir()
    output.write_text("Earlier failed attempt diagnostic")
    # Synthetic receipt fixture: no native process is launched by this test.
    receipt = fs.flow.receipts.record_run(case.project, ki="M", executable=sys.executable,
        command=[sys.executable, str(case.ki.root / "tools/run.py")], cwd=str(case.project),
        started_at=1, finished_at=2, exit_code=1, inputs=[], outputs=[output],
        approval_sha256="previous-approved-revision", plan_step_id="old_plot",
        validation={"status": "failed", "checks": []})
    before = receipt.read_bytes()
    enter(case)
    snapshot = json.loads(case.path.read_text(encoding="utf-8"))
    assert snapshot["validation"] == "incomplete" and snapshot["runs_bound"] == 0
    assert snapshot["unreceipted_artifacts"] == []
    assert snapshot["historical_outputs"][0]["classification"] == "failed_attempt"
    assert snapshot["historical_outputs"][0]["satisfies_current_step"] is False
    assert receipt.read_bytes() == before


def test_approval_drift_during_refresh_does_not_publish_wrong_snapshot(case, monkeypatch):
    fs = flowgate.FlowSession.open(case.project, {"M": case.ki.root}, python=sys.executable)
    original = fs.evidence
    before = case.path.read_bytes()
    def evidence_and_drift(**kwargs):
        result = original(**kwargs)
        plan = deepcopy(fs.plan)
        plan["goal"] = "A different scientific question"
        fs.flow.plan.write_artifacts(case.project, plan, fs.inventory)
        return result
    monkeypatch.setattr(fs, "evidence", evidence_and_drift)
    with pytest.raises(ValueError, match="approval changed"):
        ec.refresh(fs)
    assert case.path.read_bytes() == before


def test_handoff_preserves_plan_order_and_bounds_large_inventory_lists():
    snapshot = {"snapshot": {"plan_sha256": "plan", "inventory_sha256": "inventory"},
                "steps_missing": ["a_reader", "z_model"],
                "unreceipted_artifacts": [f"outputs/{i}.csv" for i in range(40)]}
    facts = json.loads(ec.handoff(snapshot, step_order=["z_model", "a_reader"]).splitlines()[1])
    assert facts["steps_missing"] == ["z_model", "a_reader"]
    assert len(facts["unreceipted_artifacts"]) == 30
    assert facts["unreceipted_artifacts_total"] == 40
