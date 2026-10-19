"""Host boundaries only: synthetic completed fixtures; no scientific model runs."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import api, completed_phase, flowgate, flowrun
from .test_flowgate import _cfg, _ki, _review_plan, _session


@pytest.fixture
def phase(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    ki = _ki(tmp_path)
    project, fs = _session(tmp_path, ki, [("task_received", None),
        ("kis_resolved", {"selected_kis": [ki.name]})])
    plan, inventory = _review_plan(ki, ["outputs/q.csv"])
    assert fs.write_plan(plan, inventory) == []
    fs.flow.approval.approve(project, by="user")
    fs.reload_artifacts()
    # Lifecycle fixture, deliberately not claiming any native execution.
    fs.ctx.state = fs.flow.states.State.COMPLETED
    fs.ctx.save()
    return project, fs, ki


def documents(project):
    return {str(p.relative_to(project)): p.read_bytes()
            for p in (project / "runs").rglob("*") if p.is_file()}


def turn(phase, provider="api", name="deepseek"):
    project, _, ki = phase
    return flowrun.turn(project, [ki], _cfg(project), provider, name, None,
                        "Only read finished artifacts; no new plan, script, or model run")


@pytest.mark.parametrize("state", ["COMPLETED", "PLAN_REVIEW", "WAITING_FOR_USER"])
def test_readonly_followup_denies_all_mutation_without_changing_documents(phase, state):
    project, fs, ki = phase
    fs.ctx.state = fs.flow.states.State(state)
    fs.ctx.save()
    baseline = documents(project)
    t = turn(phase)
    assert t.kind == "readonly" and t.session.readonly
    names = {item["name"] for item in api.tool_schemas(ki, project_mode=True, flow=t.session)}
    assert names <= flowgate.READONLY_API_TOOLS
    assert {"list_project_files", "read_project_file"} <= names
    for name in ("request_replan", "write_plan", "write_project_data_tool", "write_project_file",
                 "run_ki_tool", "run_project_data_tool", "run_preflight", "fetch_data",
                 "create_project_plot", "publish_project_view", "report_project_progress",
                 "request_user_action"):
        with pytest.raises(api.ToolError, match="read-only"):
            api.execute_tool(name, {}, ki, _cfg(project), project_mode=True, flow=t.session)
    result = flowrun.after(project, t, "The existing results confirm native completion.")
    assert not result.request and not result.continue_now and not result.retry_planning
    assert documents(project) == baseline


def test_readonly_ceiling_survives_state_refresh_and_direct_method_calls(phase):
    project, fs, ki = phase
    t = turn(phase)
    # Another actor changing state must not widen this old provider turn.
    t.session.ctx.state = fs.flow.states.State.REPLAN_REQUIRED
    assert "write_plan" not in t.session.api_tools()
    with pytest.raises(flowgate.FlowDenied, match="read-only"):
        t.session.write_plan(fs.plan, fs.inventory)
    with pytest.raises(flowgate.FlowDenied):
        t.session.request_replan("write a new audit")
    with pytest.raises(flowgate.FlowDenied, match="read-only"):
        t.session.move("plan_written", {"plan_valid": True})
    assert not t.session.write_allowed(project / "runs" / "plan.json")
    with pytest.raises(api.ToolError, match="read-only"):
        api.execute_tool("write_project_data_tool", {}, ki, _cfg(project),
                         project_mode=True, flow=t.session)


def test_readonly_after_never_promotes_external_replan_or_plan_drift(phase, monkeypatch):
    project, fs, _ = phase
    t = turn(phase)
    fs.ctx.state = fs.flow.states.State.REPLAN_REQUIRED
    fs.ctx.save()
    (project / "runs" / "plan.json").write_text('{"goal":"changed elsewhere"}')
    monkeypatch.setattr(flowrun.plan_review, "issue", lambda *_a, **_k: pytest.fail("issued review"))
    before = documents(project)
    result = flowrun.after(project, t, "REPLAN_REQUIRED")
    assert "changed during this read-only" in result.message
    assert not result.request and documents(project) == before


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_cli_readonly_has_no_wrapper_or_write_grant(phase, provider):
    t = turn(phase, "cli", provider)
    policy = flowrun.policy_for_cli(t, provider, None)
    assert t.wrappers == {} and t.planning_worktree is None
    assert "PLAN HANDOFF" not in t.extra_prompt
    if provider == "codex":
        assert policy.argv_delta == ["--sandbox", "read-only"]
    else:
        assert policy.argv_extra[-2:] == ["--tools", "Read,Glob,Grep"]
        assert "Write(" not in str(policy.argv_delta) and "Bash(" not in str(policy.argv_delta)


@pytest.mark.parametrize("provider", ["kimi", "gemini", "qwen"])
def test_unsupported_cli_inspection_fails_before_any_provider_dispatch(phase, monkeypatch, provider):
    from kiss_cli import providers
    monkeypatch.setattr(providers, "run", lambda *_a, **_k: pytest.fail("provider started"))
    before = documents(phase[0])
    with pytest.raises(flowgate.FlowDenied, match="cannot enforce"):
        turn(phase, "cli", provider)
    assert documents(phase[0]) == before


def test_prompt_has_no_planning_or_execution_contract(phase):
    project, _, ki = phase
    prompt = flowrun.readonly_prompt(project, [ki])
    assert "READ-ONLY PROJECT" in prompt and str(ki.root) in prompt
    assert "MANDATORY EXECUTION" not in prompt and "PLAN HANDOFF" not in prompt


def test_common_readonly_prompt_locates_existing_logs_without_granting_authority(phase):
    project, _, ki = phase
    prompt = flowrun.readonly_prompt(project, [ki])
    for location in (".geoforge/receipts/model-runs/*.json", "stdout_log", "stderr_log", "runs/logs/"):
        assert location in prompt
    assert "Read the relevant receipt and logs before claiming" in prompt
    assert "does not approve or satisfy that newer plan" in prompt
    assert "does not itself verify authenticity or current binding" in prompt
    assert "do not infer scientific acceptance from exit code 0" in prompt


def test_plain_completed_or_pending_chat_preserves_workflow(phase):
    project, fs, ki = phase
    for state, pending in (("COMPLETED", None), ("PLAN_REVIEW", None),
                          ("WAITING_FOR_USER", {"id": flowrun.APPROVAL_REQUEST_ID_PREFIX + "fixture"})):
        fs.ctx.state = fs.flow.states.State(state)
        fs.ctx.save()
        baseline = documents(project)
        result = flowrun.pre(project, "Inspect M output only", [ki.name], [ki], None, pending)
        assert not result.replan_reason
        assert documents(project) == baseline


def test_explicit_next_phase_archives_exact_signed_documents_then_replans(phase):
    project, fs, ki = phase
    request = completed_phase.action(project, fs.flow)
    original = {name: (project / "runs" / name).read_bytes() for name in completed_phase.FILES}
    original_outputs = project / "outputs" / "existing.txt"
    original_outputs.parent.mkdir()
    original_outputs.write_text("finished result")
    result = flowrun.pre(project, "Investigate a new question", [ki.name], [ki], request, None)
    assert result.replan_reason == "Investigate a new question"
    assert fs.flow.states.FlowContext.load(project).state.value == "REPLAN_REQUIRED"
    assert fs.flow.approval.check(project) == "MISSING"
    archive = project / ".geoforge" / "phase-history" / request["phase"]["approval_id"]
    record = json.loads((archive / "record.json").read_text(encoding="utf-8"))
    assert record["historical_only"] is True and fs.flow.receipts.verify(project, record)
    assert record["phase"] == request["phase"]
    for name, raw in original.items():
        assert (archive / name).read_bytes() == raw
        assert record["files"][name] == {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    assert original_outputs.read_text() == "finished result"
    assert not list((project / "runs").glob("model-runs/*"))
    assert completed_phase.action(project, fs.flow) is None
    repeated = flowrun.pre(project, "Replay", [ki.name], [ki], request, None)
    assert repeated.message and not repeated.replan_reason
    assert fs.flow.approval.check(project) == "MISSING"  # historical approval is never replayed


@pytest.mark.parametrize("field", ["state", "approval_id", "plan_sha256", "data_inventory_sha256"])
def test_stale_bound_click_never_revokes(phase, field):
    project, fs, ki = phase
    request = completed_phase.action(project, fs.flow)
    request["phase"][field] = "stale"
    baseline = documents(project)
    result = flowrun.pre(project, "new work", [ki.name], [ki], request, None)
    assert "stale" in result.message and documents(project) == baseline
    assert fs.flow.approval.check(project) == "OK"


@pytest.mark.parametrize("operation", ["write", "rename"])
def test_archive_failure_happens_before_revoke(phase, monkeypatch, operation):
    project, fs, _ = phase
    request = completed_phase.action(project, fs.flow)
    baseline = documents(project)
    def fail(*_a, **_k):
        raise OSError("disk unavailable")
    if operation == "write":
        monkeypatch.setattr(Path, "write_bytes", fail)
    else:
        monkeypatch.setattr(completed_phase.os, "rename", fail)
    with pytest.raises(OSError, match="disk unavailable"):
        completed_phase.begin(project, fs.flow, request, reason="new phase")
    assert documents(project) == baseline and fs.flow.approval.check(project) == "OK"


def test_corrupt_existing_history_blocks_revocation(phase, monkeypatch):
    project, fs, _ = phase
    request = completed_phase.action(project, fs.flow)
    real_revoke = fs.flow.approval.revoke
    monkeypatch.setattr(fs.flow.approval, "revoke", lambda *_a, **_k: (_ for _ in ()).throw(OSError("stop")))
    with pytest.raises(OSError, match="stop"):
        completed_phase.begin(project, fs.flow, request, reason="new phase")
    monkeypatch.setattr(fs.flow.approval, "revoke", real_revoke)
    archive = project / ".geoforge" / "phase-history" / request["phase"]["approval_id"]
    (archive / "plan.json").write_text("tampered")
    with pytest.raises(ValueError, match="not authentic"):
        completed_phase.begin(project, fs.flow, request, reason="new phase")
    assert fs.flow.approval.check(project) == "OK"


def test_snapshot_source_drift_before_revoke_is_rejected(phase, monkeypatch):
    project, fs, _ = phase
    request = completed_phase.action(project, fs.flow)
    original_capture = completed_phase._capture
    calls = []
    def capture(*args):
        calls.append(1)
        if len(calls) == 2:
            path = project / "runs" / "plan.json"
            path.write_bytes(path.read_bytes() + b"\n")
        return original_capture(*args)
    monkeypatch.setattr(completed_phase, "_capture", capture)
    with pytest.raises(ValueError, match="changed while"):
        completed_phase.begin(project, fs.flow, request, reason="new phase")
    assert (project / "runs" / "approval.json").exists()
    assert fs.flow.states.FlowContext.load(project).state.value == "COMPLETED"


def test_completed_session_cannot_replan_without_gui_action(phase):
    project, fs, ki = phase
    baseline = documents(project)
    assert "request_replan" not in fs.api_tools()
    with pytest.raises(api.ToolError):
        api.execute_tool("request_replan", {"reason": "audit"}, ki, _cfg(project), project_mode=True, flow=fs)
    assert documents(project) == baseline


@pytest.mark.parametrize("provider", ["api", "cli"])
@pytest.mark.parametrize("state", ["COMPLETED", "PLAN_REVIEW", "WAITING_FOR_USER"])
def test_actual_gui_dispatch_uses_inspection_contract_and_preserves_documents(phase, monkeypatch, provider, state):
    from kiss_cli import gui, paths
    from .test_execution_context import _handler
    project, fs, ki = phase
    fs.ctx.state = fs.flow.states.State(state)
    fs.ctx.save()
    cfg = paths.KissConfig.default(project)
    cfg.python = sys.executable
    capture = {}
    case = SimpleNamespace(project=project, ki=ki, cfg=cfg)
    handler = _handler(case, monkeypatch, provider, capture)
    def inspect_api(_prov, _ki, _cfg, system, task, **kwargs):
        capture.update(prompt=system, tools=kwargs["flow"].api_tools())
        assert kwargs["flow"].readonly
        with pytest.raises(api.ToolError, match="read-only"):
            api.execute_tool("request_replan", {"reason": "new audit"}, ki, cfg,
                             project_mode=True, flow=kwargs["flow"])
        yield "Existing results inspected."
    def inspect_cli(_prov, **kwargs):
        capture.update(prompt=kwargs["replay_prompt"], policy=kwargs["flow_policy"])
        return {"returncode": 0}
    monkeypatch.setattr(api, "run", inspect_api)
    handler._cli_turn = inspect_cli
    baseline = documents(project)
    t = gui.Handler._chat_with_models(handler, [ki.name],
        "api:deepseek" if provider == "api" else "cli:claude",
        "Read finished artifacts only", lambda _piece: True, project,
        bare_task="Read finished artifacts only", flow_pre=flowrun.Pre(names=[ki.name]))
    assert t.kind == "readonly"
    assert "READ-ONLY PROJECT" in capture["prompt"]
    assert "[EXISTING RUN EVIDENCE]" in capture["prompt"]
    assert "stdout_log and stderr_log" in capture["prompt"]
    assert "PLANNING PROJECT" not in capture["prompt"]
    assert "PLAN HANDOFF" not in capture["prompt"]
    assert "PROJECT PREPARATION" not in capture["prompt"]
    if provider == "cli":
        assert capture["policy"].argv_extra[-1] == "Read,Glob,Grep"
    flowrun.after(project, t, "Read finished artifacts only")
    assert documents(project) == baseline


def test_fresh_archive_corrupt_record_never_revokes(phase, monkeypatch):
    project, fs, _ = phase
    request = completed_phase.action(project, fs.flow)
    real_write = Path.write_text
    def corrupt_record(path, data, *args, **kwargs):
        if path.name == "record.json":
            data = '{"policy":"corrupt"}'
        return real_write(path, data, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", corrupt_record)
    with pytest.raises(ValueError, match="not authentic"):
        completed_phase.begin(project, fs.flow, request, reason="new phase")
    assert fs.flow.approval.check(project) == "OK"
    assert fs.flow.states.FlowContext.load(project).state.value == "COMPLETED"


def test_real_api_loop_cannot_repeat_live_completed_to_replan_escape(phase, monkeypatch):
    from .test_api_handoff import PROV, _call, _prose
    project, _, ki = phase
    t = turn(phase)
    baseline = documents(project)
    monkeypatch.setenv("DEMO_API_KEY", "fixture")
    answers = iter([_call("request_replan", {"reason": "read-only reference checks"}),
                    _call("write_plan", {"plan": {}, "data_inventory": {}}),
                    _call("write_project_data_tool", {"path": "audit.py", "source": "print(1)"}),
                    _prose("I can inspect the existing files without changing the plan.")])
    exposed = []
    def respond(_prov, _model, _system, _messages, tools, _key, **_kwargs):
        exposed.append({item["name"] for item in tools})
        return next(answers)
    monkeypatch.setattr(api, "_openai_turn", respond)
    text = "".join(api.run(PROV, ki, _cfg(project), t.extra_prompt, "Read results only",
                            project_mode=True, flow=t.session, max_steps=5))
    assert len(exposed) == 4 and all(names <= flowgate.READONLY_API_TOOLS for names in exposed)
    assert "without changing" in text and "asking Demo API" not in text
    assert t.session.state.value == "COMPLETED" and documents(project) == baseline
    assert not list(project.rglob("audit.py"))


def test_readonly_api_does_not_demand_planning_handoff_after_external_state_change(phase, monkeypatch):
    from .test_api_handoff import PROV, _prose
    project, fs, ki = phase
    t = turn(phase)
    t.session.ctx.state = fs.flow.states.State.REPLAN_REQUIRED
    monkeypatch.setenv("DEMO_API_KEY", "fixture")
    calls = []
    def respond(*_args, **_kwargs):
        calls.append(1)
        return _prose("Existing records only.")
    monkeypatch.setattr(api, "_openai_turn", respond)
    result = "".join(api.run(PROV, ki, _cfg(project), t.extra_prompt, "read",
                              project_mode=True, flow=t.session, max_steps=2))
    assert len(calls) == 1 and "asking Demo API" not in result


def test_gui_kimi_readonly_is_refused_before_cli_turn(phase, monkeypatch):
    from kiss_cli import gui, paths
    from .test_execution_context import _handler
    project, _, ki = phase
    cfg = paths.KissConfig.default(project)
    capture = {}
    handler = _handler(SimpleNamespace(project=project, ki=ki, cfg=cfg), monkeypatch, "cli", capture)
    handler._cli_turn = lambda *_a, **_k: pytest.fail("CLI process launched")
    baseline = documents(project)
    with pytest.raises(flowgate.FlowDenied, match="Kimi cannot enforce"):
        gui.Handler._chat_with_models(handler, [ki.name], "cli:kimi", "Inspect only",
            lambda _piece: True, project, bare_task="Inspect only", flow_pre=flowrun.Pre(names=[ki.name]))
    assert not capture and documents(project) == baseline
