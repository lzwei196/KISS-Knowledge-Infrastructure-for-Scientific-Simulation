"""Stop reaches everything a turn started and never starts another turn.

Real gui._stop_agent_run, Handler._cli_turn and providers.run drive a stand-in
CLI whose "Bash tool" is a long background process, as a real agent's is; one of
them is started in its own session, as Claude Code, Codex and Kimi do.
"""
from __future__ import annotations

import hashlib
import os
import signal
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import api, execution, flowrun, gui, providers, sessions

pytestmark = pytest.mark.skipif(os.name == "nt", reason="process groups are POSIX")

FAKE_CLI = """#!/bin/bash
echo "cli pid=$$ args=$*" >> "$FAKECLI_LOG"
sleep 60 >/dev/null 2>&1 &
echo "tool pid=$!" >> "$FAKECLI_LOG"
"$FAKECLI_PY" -c 'import os, sys, time; os.setsid()
open(sys.argv[1], "a").write(f"session tool pid={os.getpid()}\\n"); time.sleep(60)' "$FAKECLI_LOG" >/dev/null 2>&1 &
wait
echo "final answer"
"""

# A model started in its own session that keeps its parent's stdout open.
SESSION_CHILD = """import os, subprocess, sys
child = subprocess.Popen(["sleep", "30"], start_new_session=True)
open(sys.argv[1], "w").write(f"{os.getpid()} {child.pid}")
child.wait()
"""


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_dead(pids, seconds=5):
    deadline = time.time() + seconds
    while any(map(_alive, pids)) and time.time() < deadline:
        time.sleep(0.05)
    return [pid for pid in pids if _alive(pid)]


def _pids(log):
    return [int(line.split("=")[1].split()[0]) for line in (log.read_text().splitlines() if log.exists() else [])]


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"; bin_dir.mkdir()
    cli = bin_dir / "fakecli"; cli.write_text(FAKE_CLI); cli.chmod(0o755)
    log = tmp_path / "cli.log"
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKECLI_LOG", str(log))
    monkeypatch.setenv("FAKECLI_PY", sys.executable)
    project = tmp_path / "project"; project.mkdir()
    prov = providers.Provider(name="fakecli", binary="fakecli", argv=["fakecli", "{prompt}"], output="text",
                              label="FakeCLI", resume_argv=["fakecli", "--resume", "{resume}", "{prompt}"])
    sid = "a" * 32
    events = {"provider": "cli:fakecli", "project": str(project), "_handle": api.TurnHandle()}
    gui._register_agent_run(sid, events)
    shown = []
    handler = SimpleNamespace(_remember_cli_session=gui.Handler._remember_cli_session)

    def turn(session=None):
        return threading.Thread(target=gui.Handler._cli_turn, args=(handler, prov), daemon=True, kwargs=dict(
            fingerprint_src="fp", replay_prompt="FULL", bare_prompt="BARE", wd=project,
            out=lambda piece: shown.append(piece) or True, session=session, cli_state={},
            runtime_events=events))

    yield SimpleNamespace(log=log, project=project, prov=prov, sid=sid, events=events, shown=shown, turn=turn)
    with gui._LIVE_AGENT_RUNS_LOCK:
        gui._LIVE_AGENT_RUNS.pop(sid, None)
    for pid in _pids(log):
        if _alive(pid):
            os.kill(pid, signal.SIGKILL)


def _wait_for(log, text):
    deadline = time.time() + 10
    while text not in (log.read_text() if log.exists() else ""):
        assert time.time() < deadline, f"stand-in CLI never logged {text!r}"
        time.sleep(0.05)


@pytest.fixture
def unrelated_process():
    proc = subprocess.Popen(["sleep", "60"], start_new_session=True)
    try:
        yield proc
    finally:
        proc.kill()
        proc.wait(timeout=5)


@pytest.mark.parametrize("resumed", [True, False])
def test_stop_ends_the_cli_and_its_tools_without_replaying_the_turn(fake_cli, resumed):
    fingerprint = hashlib.sha256(b"fp").hexdigest()[:16]
    session = {"cli_sessions": {"fakecli": {"id": "S1", "fingerprint": fingerprint}}} if resumed else None
    turn = fake_cli.turn(session)
    turn.start()
    _wait_for(fake_cli.log, "session tool pid")
    assert gui._stop_agent_run(fake_cli.sid)["stopped"] is True
    turn.join(10)
    assert not turn.is_alive(), "one Stop must end the turn"
    lines = fake_cli.log.read_text().splitlines()
    assert _wait_dead(_pids(fake_cli.log)) == [], "the CLI's background tools survived Stop"
    assert sum(l.startswith("cli pid") for l in lines) == 1, "Stop was mistaken for a stale resume and replayed"
    assert (fake_cli.project / execution.STOP_MARKER).is_file()     # reaches run-tool attempts in any process
    shown = "".join(fake_cli.shown)
    assert "exited" not in shown
    assert resumed or "[stopped by the user]" in shown


@pytest.mark.parametrize("cli_ignores_term", [False, True])
def test_stop_escalates_for_a_term_ignoring_cli_tool(
        fake_cli, monkeypatch, cli_ignores_term, unrelated_process):
    # The child remains in the captured tree at Stop, but its parent may exit
    # from SIGTERM before escalation. Its new session must still be reached.
    cli = Path(shutil.which("fakecli"))
    cli.write_text("#!/bin/bash\n" + ("trap '' TERM\n" if cli_ignores_term else "") + """
echo "cli pid=$$ args=$*" >> "$FAKECLI_LOG"
"$FAKECLI_PY" -c 'import os, signal, sys, time; os.setsid()
signal.signal(signal.SIGTERM, signal.SIG_IGN)
open(sys.argv[1], "a").write(f"session tool pid={os.getpid()}\\n"); time.sleep(60)' "$FAKECLI_LOG" &
wait
""")
    monkeypatch.setattr(execution, "_STOP_GRACE_SECONDS", 0.2)
    turn = fake_cli.turn()
    turn.start()
    _wait_for(fake_cli.log, "session tool pid")
    assert gui._stop_agent_run(fake_cli.sid)["stopped"] is True
    turn.join(3)
    assert not turn.is_alive(), "Stop never escalated after the CLI tool ignored SIGTERM"
    assert _wait_dead(_pids(fake_cli.log)) == [], "a reparented CLI tool survived escalation"
    assert unrelated_process.poll() is None, "Stop signalled an unrelated process group"
    assert "[stopped by the user]" in "".join(fake_cli.shown)


def test_a_stop_before_the_cli_starts_means_it_never_starts(fake_cli):
    assert gui._stop_agent_run(fake_cli.sid)["stopped"] is True    # e.g. while GeoForge prepares the turn
    turn = fake_cli.turn()
    turn.start()
    turn.join(10)
    assert not turn.is_alive() and not fake_cli.log.exists()
    assert "[stopped by the user]" in "".join(fake_cli.shown)


def test_a_stop_that_races_the_spawn_still_ends_the_cli(fake_cli, monkeypatch):
    real_popen = subprocess.Popen

    def spawn_then_stop(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        if Path(str(args[0][0])).name == "fakecli":
            # The click lands after the spawn but before the turn records the process,
            # so _stop_agent_run finds nothing to end.
            fake_cli.events["_handle"].stop()
        return proc

    monkeypatch.setattr(providers.subprocess, "Popen", spawn_then_stop)
    turn = fake_cli.turn()
    turn.start()
    turn.join(10)
    assert not turn.is_alive(), "the raced CLI ran its whole turn"
    assert _wait_dead(_pids(fake_cli.log)) == []
    assert "final answer" not in "".join(fake_cli.shown)


def test_stop_on_a_finished_turn_reports_no_live_turn():
    sid = "f" * 32
    gui._register_agent_run(sid, {"provider": "api:deepseek", "_handle": api.TurnHandle()})
    gui._LIVE_AGENT_RUNS[sid]["finished_at"] = time.time()
    try:
        assert gui._stop_agent_run(sid) == {"ok": False, "stopped": False, "reason": "no live turn"}
    finally:
        gui._LIVE_AGENT_RUNS.pop(sid, None)


def _chat(tmp_path):
    workroot = tmp_path / "work"
    session = sessions.create(workroot, [], "api:deepseek", project_parent=tmp_path / "projects")
    handler = object.__new__(gui.Handler)
    handler.workroot, handler.catalog = workroot, SimpleNamespace(get=lambda name: {}[name])   # no KI: KeyError
    handler._open_stream = lambda: None
    handler._chunk = lambda _text: True
    handler._end_stream = lambda: None
    return handler, session


def test_a_stop_right_after_sending_reaches_the_new_turn(tmp_path, monkeypatch):
    handler, session = _chat(tmp_path)
    sid = session["id"]
    previous = api.TurnHandle()
    gui._register_agent_run(sid, {"provider": "api:deepseek", "_handle": previous})
    gui._LIVE_AGENT_RUNS[sid]["finished_at"] = time.time()          # the previous turn
    hits = []

    def pre(*_args, **_kwargs):
        hits.append(gui._stop_agent_run(sid))                         # the user's click, while the flow runs
        return flowrun.Pre(names=[], message="Answered by the flow.")

    monkeypatch.setattr(flowrun, "pre", pre)
    try:
        handler._stream_session_chat(sid, {"message": "go"})
        live = gui._LIVE_AGENT_RUNS[sid]
        assert hits == [{"ok": True, "stopped": True}] and not previous.stopped.is_set()
        assert live["_handle"] is not previous and live["_handle"].stopped.is_set()
        assert live.get("finished_at")                                  # an answered turn is over
    finally:
        gui._LIVE_AGENT_RUNS.pop(sid, None)


def test_a_stopped_intake_turn_does_not_start_planning(tmp_path, monkeypatch):
    handler, session = _chat(tmp_path)
    planning = []
    monkeypatch.setattr(flowrun, "pre", lambda *_a, **_k: flowrun.Pre(names=[], gated=True))
    monkeypatch.setattr(flowrun, "promote_auto_choice", lambda *_a: ["VIC"])
    handler._chat_auto = lambda *_a, runtime_events=None, **_k: runtime_events["_handle"].stop()
    handler._chat_with_models = lambda *a, **k: planning.append(a)
    try:
        handler._stream_session_chat(session["id"], {"message": "the answer to your question"})
    finally:
        gui._LIVE_AGENT_RUNS.pop(session["id"], None)
    assert planning == [], "a stopped intake turn chained into a planning turn"


@pytest.mark.parametrize("kind", ["api", "cli"])
def test_a_stopped_setup_turn_does_not_run_the_preflight(tmp_path, monkeypatch, kind):
    from kiss_cli import paths
    ki = SimpleNamespace(name="M", root=tmp_path / "ki")
    setup_wd = tmp_path / "setup"
    cfg = paths.KissConfig.default(setup_wd)
    events = {"_handle": api.TurnHandle()}
    preflights = []

    def prepare(*_args):
        setup_wd.mkdir(parents=True, exist_ok=True)
        (setup_wd / "CLAUDE.md").write_text("setup contract")
        return None, cfg

    def stopped_turn(*_args, **_kwargs):
        events["_handle"].stop()                                   # the user stops the setup turn
        yield "[stopped by the user]"

    handler = SimpleNamespace(
        _ki=lambda _n: ki, _workdir=lambda _k: setup_wd, _status_for=lambda _k: {"can_run": False},
        _manifest=lambda _k: SimpleNamespace(install_dir=None, depends_on=[], system_deps=[], data=[]),
        repo_root=tmp_path,
        catalog=SimpleNamespace(models_dir=tmp_path), _software_status_prompt=lambda *_a: "",
        _session_workspaces=lambda *_a: [], _agent_runtime_env=lambda _p: {},
        _record_agent_preflight=lambda *a, **k: preflights.append(a) or True,
        _cli_turn=lambda *a, **k: (list(stopped_turn()), {"returncode": -15})[1])
    monkeypatch.setattr(gui.setup_flow, "prepare", prepare)
    monkeypatch.setattr(gui.prompt, "compose_multi", lambda *_a, **_k: "SYSTEM")
    monkeypatch.setattr(gui.calibration, "prompt_block", lambda *_a: "")
    monkeypatch.setattr(gui.api, "run", stopped_turn)
    fake = providers.Provider(name="fakecli", binary="fakecli", argv=["fakecli"], output="text", label="FakeCLI")
    monkeypatch.setattr(gui.providers, "available", lambda: [fake])
    monkeypatch.setattr(gui.providers, "get", lambda _n: fake)
    want = "api:deepseek" if kind == "api" else "cli:fakecli"
    gui.Handler._chat_with_models(handler, ["M"], want, "build it", lambda _p: True, tmp_path / "project",
                                  runtime_events=events)
    assert events["_handle"].stopped.is_set() and preflights == [], "a stopped setup turn ran the preflight"


@pytest.mark.parametrize("how", ["stop", "timeout"])
def test_a_setup_command_is_stopped_or_timed_out_with_its_whole_tree(tmp_path, how):
    work, project = tmp_path / "work", tmp_path / "project"
    work.mkdir(); project.mkdir()
    (work / "build.py").write_text(SESSION_CHILD)
    pidfile = work / "pids.txt"
    cfg = SimpleNamespace(root=work, python=sys.executable, roles={"binaries": work / "binaries"})
    args = {"argv": [sys.executable, "build.py", str(pidfile)]}
    if how == "timeout":
        args["timeout_seconds"] = 1
    box = {}
    worker = threading.Thread(target=lambda: box.update(out=api.execute_tool(
        "run_setup_command", args, SimpleNamespace(root=work / "ki", name="M"), cfg,
        setup_mode=True, setup_context={"project_root": project})), daemon=True)
    worker.start()
    deadline = time.time() + 10
    while not (pidfile.exists() and pidfile.read_text()):
        assert time.time() < deadline, "setup command never started"
        time.sleep(0.05)
    pids = [int(p) for p in pidfile.read_text().split()]
    if how == "stop":
        execution.request_stop(project)
    worker.join(15)
    try:
        assert not worker.is_alive(), "the setup command outlived the Stop or timeout"
        assert box["out"].startswith("STOPPED by the user" if how == "stop" else "TIMEOUT after 1s")
        assert _wait_dead(pids) == []
    finally:
        for pid in pids:
            if _alive(pid):
                os.kill(pid, signal.SIGKILL)


DESKTOP = """import subprocess, sys, threading
from pathlib import Path
from kiss_cli import api, execution, flowgate, gui, paths
tmp, project = Path(sys.argv[1]), Path(sys.argv[2])
root = project / "models" / "M" / "ki"
fs = flowgate.FlowSession.open(project, {"M": root}, python=sys.executable)
threading.Thread(target=execution.execute_ki_tool, daemon=True, kwargs=dict(
    flow=fs, cfg=paths.KissConfig.load(project), project=project, ki="M", ki_root=root,
    tool=root / "tools" / "run.py", arguments=[str(tmp / "tool.pids")], cwd=project,
    plan_step_id="M:run", python_tool=True, timeout=None)).start()
cli = subprocess.Popen([sys.executable, "-c", sys.argv[3], str(tmp / "cli.pids")], start_new_session=True)
gui._register_agent_run("c" * 32, {"provider": "cli:fake", "_handle": api.TurnHandle(), "_process_handle": cli})
(tmp / "models").mkdir()
gui.serve(tmp / "models", port=0, open_browser=False, workroot=tmp / "work")
"""


@pytest.mark.parametrize("cli_ignores_term", [False, True])
def test_quitting_a_source_build_desktop_ends_its_turns_and_tools(tmp_path, monkeypatch, cli_ignores_term):
    import importlib.util
    spec = importlib.util.spec_from_file_location("te", Path(__file__).with_name("test_execution.py"))
    te = importlib.util.module_from_spec(spec); spec.loader.exec_module(te)
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    ctx = te._project(tmp_path, source=SESSION_CHILD)
    repo = Path(execution.__file__).resolve().parents[2]
    env = {**os.environ, "HOME": str(tmp_path), "PYTHONPATH": os.pathsep.join(
        [str(repo / "kiss"), str(repo / "ki_tools_common")])}
    cli_source = (("import signal\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                   if cli_ignores_term else "") + SESSION_CHILD)
    desktop = subprocess.Popen([sys.executable, "-c", DESKTOP, str(tmp_path), str(ctx.project), cli_source],
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    files, deadline = [tmp_path / "tool.pids", tmp_path / "cli.pids"], time.time() + 30
    while not all(f.exists() and f.read_text() for f in files):
        assert time.time() < deadline and desktop.poll() is None, desktop.communicate()
        time.sleep(0.05)
    pids = [int(p) for f in files for p in f.read_text().split()]
    time.sleep(1)                                                   # the server is up
    desktop.send_signal(signal.SIGINT)                              # Ctrl-C in its terminal
    try:
        desktop.wait(20)
        assert _wait_dead(pids) == [], "a tool or agent outlived the Desktop"
    finally:
        desktop.kill()
        for pid in pids:
            if _alive(pid):
                os.kill(pid, signal.SIGKILL)


def test_long_job_rule_only_names_setsid_where_it_exists():
    import shutil
    from kiss_cli import prompt
    assert ("setsid" in prompt.HEADLESS_LONG_JOB_RULE) == (
        bool(shutil.which("setsid")) and os.name != "nt")


def test_harness_long_job_rule_gives_the_fallback_where_setsid_is_absent():
    from ki_tools_common.flow import contracts
    from ki_tools_common.harness import ki_attention
    assert "where setsid is absent, as on macOS" in contracts.PROGRESS_LONG_JOBS
    assert "plain nohup ... & where setsid is absent, as on macOS" in ki_attention.OP_RULES
