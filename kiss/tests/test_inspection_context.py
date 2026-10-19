"""Current host facts follow historical conversation in both provider paths."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from kiss_cli import api, execution_context, flowrun, gui, paths, runtime_context, runtime_provenance
from .test_execution_context import _handler
from .test_readonly_followup import phase, documents  # noqa: F401


@pytest.fixture(autouse=True)
def fresh_provenance():
    runtime_provenance._startup.cache_clear()
    yield
    runtime_provenance._startup.cache_clear()


def runtime(digest="c"):
    return {"kind": "wsl", "platform": "Linux", "source_hash": digest * 64,
        "distro": "Ubuntu", "user": "scientist", "workspace": "/home/scientist/work",
        "id": "instance", "machine": "x86_64", "guest_identity": "d" * 64,
        "guest_path_identity": "e" * 64, "nonce": "SECRET-MUST-NOT-ENTER-PROMPT", "unexpected": "secret"}


@pytest.mark.parametrize("provider", ["api", "cli"])
def test_inspection_current_facts_follow_history_without_rewriting_saved_evidence(phase, monkeypatch, provider):
    project, _, ki = phase
    capture = {}
    handler = _handler(SimpleNamespace(project=project, ki=ki, cfg=paths.KissConfig.default(project)),
                       monkeypatch, provider, capture)
    monkeypatch.setattr(runtime_context, "identity", lambda: runtime())
    def read_api(_prov, _ki, _cfg, system, task, **kw):
        capture.update(task=task, history=kw["history"])
        yield "Existing records only."
    def read_cli(_prov, **kw):
        capture.update(kw)
        return {"returncode": 0}
    monkeypatch.setattr(api, "run", read_api)
    handler._cli_turn = read_cli
    prior = [{"role": "assistant", "text": "OLD DIAGNOSIS: rebuilt binary and REPLAN_REQUIRED"}]
    saved = deepcopy(prior)
    before = documents(project)
    t = gui.Handler._chat_with_models(handler, [ki.name],
        "api:deepseek" if provider == "api" else "cli:claude", "old history\nInspect now",
        lambda _x: True, project, prior=prior, bare_task="Inspect now",
        flow_pre=flowrun.Pre(names=[ki.name], readonly=True))
    current = capture["task"] if provider == "api" else capture["bare_prompt"]
    assert current.startswith("[CURRENT USER REQUEST]\nInspect now")
    assert '"saved_flow_state": "COMPLETED"' in current
    assert '"source_hash": "' + "c" * 64 in current
    assert '"setup_or_execution_authorized": false' in current
    assert '"readiness_rechecked": false' in current
    assert "SECRET" not in current and "unexpected" not in current
    if provider == "api":
        assert capture["history"][0]["text"].startswith("[HISTORICAL CONVERSATION]")
    else:
        replay = capture["replay_prompt"]
        assert replay.index("OLD DIAGNOSIS") < replay.index("CURRENT HOST INSPECTION CONTEXT")
        assert "HISTORICAL CONVERSATION" in replay
    assert prior == saved and documents(project) == before
    assert t.kind == "readonly"


def test_cli_inspection_fingerprint_changes_with_runtime_build_not_startup_nonce(phase, monkeypatch):
    project, _, ki = phase
    identity = runtime("a")
    monkeypatch.setattr(runtime_context, "identity", lambda: dict(identity))
    def turn():
        return flowrun.readonly_turn(project, [ki], paths.KissConfig.default(project), "cli", "claude")
    original = turn().fingerprint_extra
    identity["nonce"] = "two"
    assert turn().fingerprint_extra == original
    identity["source_hash"] = "b" * 64
    runtime_provenance._startup.cache_clear()  # a newly started host observes the new build
    assert turn().fingerprint_extra != original


def test_inspection_separates_current_host_legacy_checks_and_model_run_authority(phase, monkeypatch):
    from kiss_cli import project_verification as pv, software_history
    project, _, ki = phase
    monkeypatch.setattr(runtime_context, "identity", lambda: runtime("b"))
    legacy = {"receipt_sha256": "f" * 64, "location": "current", "authentication": "verified",
        "provenance": "legacy_unknown", "verification_context": None, "attempt_id": "old",
        "state": "verified", "checked_at": 10}
    monkeypatch.setattr(pv, "history", lambda *a, **kw: {"records": [legacy]})
    monkeypatch.setattr(software_history, "history", lambda *a, **kw: {"records": []})
    before = documents(project)
    turn = flowrun.readonly_turn(project, [ki], paths.KissConfig.default(project), "api", "deepseek")
    prompt = turn.inspection_handoff
    assert '"sha256": "' + "b" * 64 in prompt
    assert '"verification_context": null' in prompt
    assert '"build": "unknown"' in prompt
    assert '"scope": "project_preflight"' in prompt
    assert '"saved_plan_goal_is_historical": true' in prompt
    assert "not the identity or cause of the current update" in prompt
    assert "scientific_model_run_receipts_not_rechecked" in prompt
    assert documents(project) == before


@pytest.mark.parametrize("current_time", [20, 5])
def test_current_cancelled_observation_wins_over_archived_pass_regardless_clock(phase, monkeypatch, current_time):
    from kiss_cli import project_verification as pv, software_history
    project, _, ki = phase
    monkeypatch.setattr(runtime_context, "identity", lambda: runtime())
    base = {"authentication": "verified", "provenance": "legacy_unknown", "verification_context": None,
            "attempt_id": "same", "state": "verified", "checked_at": 20, "location": "history"}
    rows = [base, {**base, "state": "cancelled", "location": "current", "checked_at": current_time}]
    monkeypatch.setattr(pv, "history", lambda *a, **kw: {"records": rows})
    monkeypatch.setattr(software_history, "history", lambda *a, **kw: {"records": []})
    session = flowrun.readonly_turn(project, [ki], paths.KissConfig.default(project), "api", "deepseek").session
    records = execution_context.inspection_snapshot(session)["verification_history"]["records"]
    assert len(records) == 1 and records[0]["state"] == "cancelled"


def test_conflicting_historical_transitions_are_not_reported_as_final_pass(phase, monkeypatch):
    from kiss_cli import project_verification as pv, software_history
    project, _, ki = phase
    monkeypatch.setattr(runtime_context, "identity", lambda: runtime())
    row = {"authentication": "verified", "provenance": "legacy_unknown", "verification_context": None,
           "attempt_id": "old", "location": "history", "checked_at": 20}
    monkeypatch.setattr(pv, "history", lambda *a, **kw: {"records": [{**row, "state": "verified"}, {**row, "state": "cancelled"}]})
    monkeypatch.setattr(software_history, "history", lambda *a, **kw: {"records": []})
    session = flowrun.readonly_turn(project, [ki], paths.KissConfig.default(project), "api", "deepseek").session
    record = execution_context.inspection_snapshot(session)["verification_history"]["records"][0]
    assert record["outcome"] == "unknown_conflicting_retained_transitions" and "state" not in record
