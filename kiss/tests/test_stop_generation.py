"""Stopped turns cannot borrow a later turn's permission to start work.

Local provider and source-CLI subprocesses use the real execution/receipt path;
no provider service, scientific model, or user project is involved.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from kiss_cli import api, execution, flowrun, gui, projectrun, providers


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    spec = importlib.util.spec_from_file_location(
        "execution_fixture", Path(__file__).with_name("test_execution.py"))
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    ctx = fixtures._project(tmp_path, source=(
        "from pathlib import Path\nPath('model-launched').touch()\nprint('fixture executed')\n"))
    ctx.receipts = lambda: fixtures._receipt_docs(ctx)
    return ctx


def _provider_environment(project):
    # A stand-in provider displays only the non-secret turn identity inherited
    # by its shell tools. Keep all credentials out of fixture stdout.
    code = "import json, os; print(json.dumps({k:v for k,v in os.environ.items() if k.startswith('GEOFORGE_TURN_')}))"
    prov = providers.Provider(name="turn-fixture", binary=sys.executable,
                              argv=[sys.executable, "-c", code], output="text", label="Fixture")
    events = {"project": str(project), "_handle": api.TurnHandle()}
    result = "".join(providers.run(prov, "fixture", project, runtime_events=events))
    return json.loads(result)


def _source_run(ctx, captured_env):
    repo = Path(execution.__file__).resolve().parents[2]
    env = {**os.environ, **captured_env, "PYTHONPATH": os.pathsep.join(
        [str(repo / "kiss"), str(repo / "ki_tools_common")])}
    return subprocess.run([sys.executable, "-m", "kiss_cli", "run-tool", "--project",
                           str(ctx.project), "--step", "M:run", "M", "tools/run.py"],
                          env=env, cwd=ctx.project, capture_output=True, text=True, timeout=15)


def test_old_provider_command_stays_stopped_after_new_user_turn(case):
    projectrun.begin_turn(case.project, "Run the approved model")
    old_environment = _provider_environment(case.project)
    execution.request_stop(case.project)
    projectrun.begin_turn(case.project, "Continue with the next user turn")

    stale = _source_run(case, old_environment)
    assert stale.returncode == 3, stale.stdout + stale.stderr
    assert "stopped by the user" in stale.stderr
    assert not (case.project / "model-launched").exists()
    assert case.receipts() == []

    current = _source_run(case, _provider_environment(case.project))
    assert current.returncode == 0, current.stdout + current.stderr
    assert len(case.receipts()) == 1


def test_finished_stopped_turn_keeps_explicit_stop_status(case):
    projectrun.begin_turn(case.project, "Run the approved model")
    execution.request_stop(case.project)
    turn = flowrun.Turn(session=case.flow, execute=True, extra_prompt="", drop_scope_rules=False,
                        policy=None, fingerprint_extra="fixture", kind="execution")
    result = flowrun.after(case.project, turn, "[stopped by the user]")
    assert not result.continue_now
    assert projectrun.load(case.project)["summary"] == "Stopped by you — send a message to continue"

    state = projectrun.finish_turn(case.project)
    assert state["status"] == "idle"
    assert state["summary"] == "Stopped by you — send a message to continue"
    assert projectrun.load(case.project)["summary"] == state["summary"]


def test_direct_source_cli_without_desktop_turn_still_runs(case):
    current = _source_run(case, {})
    assert current.returncode == 0, current.stdout + current.stderr
    assert len(case.receipts()) == 1


def test_stop_status_survives_late_native_agent_progress(case):
    projectrun.begin_turn(case.project, "Run")
    execution.request_stop(case.project)
    projectrun.finish_turn(case.project, failed="Provider interrupted during Stop")
    agent = case.project / "runs" / projectrun.AGENT_FILE
    agent.write_text(json.dumps({"status": "working", "summary": "Running again"}))
    state = projectrun.load(case.project)
    assert state["status"] == "idle"
    assert state["summary"] == projectrun.STOPPED_SUMMARY
    resumed = projectrun.begin_turn(case.project, "Continue")
    assert resumed["status"] == "working"
    assert resumed["summary"] != projectrun.STOPPED_SUMMARY


def test_stop_and_new_turn_during_preparation_do_not_rebind_attempt(case, monkeypatch):
    from kiss_cli import flowgate
    projectrun.begin_turn(case.project, "Run")
    snapshot = flowgate._snapshot

    def next_turn(*args, **kwargs):
        result = snapshot(*args, **kwargs)
        execution.request_stop(case.project)
        projectrun.begin_turn(case.project, "Continue")
        return result

    monkeypatch.setattr(flowgate, "_snapshot", next_turn)
    with pytest.raises(flowgate.FlowDenied, match="no process was launched"):
        execution.execute_ki_tool(flow=case.flow, cfg=case.cfg, project=case.project, ki="M",
                                  ki_root=case.root, tool=case.tool, arguments=[], cwd=case.project,
                                  plan_step_id="M:run", python_tool=True)
    assert not (case.project / "model-launched").exists()
    assert case.receipts() == []


def test_running_process_cannot_miss_a_stop_cleared_between_polls(case):
    projectrun.begin_turn(case.project, "Run")
    flag = case.project / "started"
    code = "import pathlib, sys, time; pathlib.Path(sys.argv[1]).touch(); time.sleep(20)"
    results = {}
    worker = threading.Thread(target=lambda: results.update(run=execution.run_process(
        [sys.executable, "-c", code, str(flag)], cwd=case.project,
        env=execution.turn_environment(case.project), project=case.project, timeout=5)))
    worker.start()
    deadline = time.monotonic() + 5
    while not flag.exists() and time.monotonic() < deadline:
        time.sleep(.01)
    assert flag.exists(), "fixture process did not start"
    execution.request_stop(case.project)
    projectrun.begin_turn(case.project, "Continue")
    worker.join(10)
    assert not worker.is_alive()
    assert results["run"].status == "stopped"


def test_turn_identity_is_not_rebound_to_a_new_generation(case):
    projectrun.begin_turn(case.project, "Run")
    old = execution.turn_environment(case.project, env={})
    projectrun.begin_turn(case.project, "Next")
    assert execution.turn_environment(case.project, env=old) == old
    assert execution.stop_requested(case.project, env=old)
    assert not execution.stop_requested(case.project, env={})


def test_bound_turn_cannot_target_another_project(case, tmp_path):
    projectrun.begin_turn(case.project, "Run")
    origin = execution.turn_environment(case.project, env={})
    other = tmp_path / "other-project"
    other.mkdir()
    assert execution.stop_requested(other, env=origin)


def _bridge(case, body):
    handler = gui.Handler.__new__(gui.Handler)
    handler.workroot = case.project.parent
    handler.agent_database_token = "local-fixture-capability"
    handler.headers = {"X-GeoForge-Agent-Token": handler.agent_database_token}
    handler.rfile = io.BytesIO(body)
    response = {}
    handler._json = lambda value, code=200: response.update(value=value, code=code)
    handler._post_agent_flow_command(len(body))
    return response


def _bridge_command(case, environment, monkeypatch):
    """The exact shipped launcher submits to the real route and source CLI."""
    seen = []

    def urlopen(request, timeout=None):
        assert request.full_url == "http://127.0.0.1:12345/fixture-flow"
        seen.append(json.loads(request.data))
        response = _bridge(case, request.data)
        payload = io.BytesIO(json.dumps(response["value"]).encode())
        if response["code"] >= 400:
            raise urllib.error.HTTPError(request.full_url, response["code"], "rejected", {}, payload)
        return payload

    with monkeypatch.context() as patch:
        patch.chdir(case.project)
        patch.setenv("GEOFORGE_AGENT_FLOW_URL", "http://127.0.0.1:12345/fixture-flow")
        patch.setenv("GEOFORGE_AGENT_DATABASE_TOKEN", "local-fixture-capability")
        for key in (execution.TURN_PROJECT_ENV, execution.TURN_ID_ENV):
            patch.delenv(key, raising=False)
        for key, value in environment.items():
            patch.setenv(key, value)
        patch.setattr(urllib.request, "urlopen", urlopen)
        patch.setattr(sys, "argv", ["geoforge-flow", "run-tool", "--project", str(case.project),
                                  "--step", "M:run", "M", "tools/run.py"])
        namespace = {"__name__": "fixture_launcher"}
        exec(compile(flowrun._FLOW_HELPER, "fixture_launcher", "exec"), namespace)
        code = namespace["main"]()
    return code, seen


def test_shipped_bridge_preserves_originating_turn_after_stop_and_resume(case, monkeypatch):
    projectrun.begin_turn(case.project, "Run")
    old = _provider_environment(case.project)
    execution.request_stop(case.project)
    projectrun.begin_turn(case.project, "Continue")
    code, seen = _bridge_command(case, old, monkeypatch)
    assert code == 130
    assert seen[0]["turn_id"] == old[execution.TURN_ID_ENV]
    assert seen[0]["turn_project"] == str(case.project)
    assert not (case.project / "model-launched").exists()
    assert case.receipts() == []

    code, _ = _bridge_command(case, _provider_environment(case.project), monkeypatch)
    assert code == 0
    assert len(case.receipts()) == 1


@pytest.mark.parametrize("invalid", ["missing", "wrong-project", "missing-generation-file"])
def test_bridge_cannot_rebind_unidentified_or_invalid_command(case, monkeypatch, invalid):
    projectrun.begin_turn(case.project, "Run")
    env = _provider_environment(case.project)
    if invalid == "missing":
        env = {}
    elif invalid == "wrong-project":
        env[execution.TURN_PROJECT_ENV] = str(case.project.parent)
    else:
        (case.project / execution.TURN_FILE).unlink()
    code, _ = _bridge_command(case, env, monkeypatch)
    assert code == 130
    assert not (case.project / "model-launched").exists()
    assert case.receipts() == []
