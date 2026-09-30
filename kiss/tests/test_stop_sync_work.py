"""Real synchronous host work must end when the owning chat is stopped."""
import json
import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import api, calibration, cli, execution, gui, install, paths
from kiss_cli.catalog import KI
from kiss_cli.manifest import Acquire, Manifest


def _wait_file(path):
    deadline = time.monotonic() + 8
    while not path.exists():
        assert time.monotonic() < deadline, f"worker never reached {path}"
        time.sleep(.02)


@pytest.fixture
def worker_runtime(monkeypatch):
    """An optional real frozen binary exercises the same tests after packaging."""
    executable = os.environ.get("GEOFORGE_TEST_FROZEN_EXE")
    if executable:
        assert Path(executable).is_file()
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", executable)


@pytest.fixture
def stopped_chat(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    sid = "sync-stop-test"
    events = {"project": str(project), "_handle": api.TurnHandle()}
    gui._register_agent_run(sid, events)
    yield project, sid, events
    with gui._LIVE_AGENT_RUNS_LOCK:
        gui._LIVE_AGENT_RUNS.pop(sid, None)


def _stoppable_call(call, started, sid):
    result, errors = [], []
    def run():
        try:
            result.append(call())
        except BaseException as exc:
            errors.append(exc)
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    _wait_file(started)
    gui._stop_agent_run(sid)
    worker.join(1.8)
    try:
        assert not worker.is_alive(), "Stop left synchronous host work running"
        assert not errors, errors
        return result
    finally:
        worker.join(5)


def test_api_stop_ends_already_running_preflight(stopped_chat, tmp_path):
    project, sid, _ = stopped_chat
    ki_root = tmp_path / "ki"
    ki_root.mkdir()
    started = tmp_path / "preflight-started"
    late = tmp_path / "preflight-completed"
    (ki_root / "preflight_check.py").write_text(
        f"import pathlib,time\npathlib.Path({str(started)!r}).touch()\n"
        f"time.sleep(3)\npathlib.Path({str(late)!r}).touch()\n")
    cfg = paths.KissConfig.default(tmp_path / "setup")
    cfg.python = sys.executable
    result = _stoppable_call(lambda: api.execute_tool(
        "run_preflight", {}, KI("Demo", ki_root), cfg, project_mode=True,
        setup_context={"project_root": project}), started, sid)
    assert not late.exists(), "the preflight kept writing after Stop"
    assert "stop" in result[0].lower()


def test_stop_ends_calibration_engine(stopped_chat, tmp_path, monkeypatch, worker_runtime):
    project, sid, _ = stopped_chat
    framework = tmp_path / "framework"
    package = framework / "calibration_kit"
    package.mkdir(parents=True)
    started, late = tmp_path / "calibration-started", tmp_path / "calibration-completed"
    for name in ("__init__.py", "CALIBRATION_YAML_SCHEMA.md", "CALIBRATION_FRAMEWORK_DESIGN.md"):
        (package / name).write_text("")
    (package / "calib.py").write_text(
        "import pathlib,time\ndef calibrate(*a, **k):\n"
        f"    pathlib.Path({str(started)!r}).touch()\n    time.sleep(3)\n"
        f"    pathlib.Path({str(late)!r}).touch()\n"
        "    return {'status': 'completed', 'promotable': True}\n")
    monkeypatch.setenv("GEOFORGE_CALIBRATION_FRAMEWORK", str(framework))
    monkeypatch.syspath_prepend(str(framework))
    monkeypatch.setattr(calibration, "framework_status", lambda: {"ready": True})
    ki_root = tmp_path / "ki"
    (ki_root / "tools").mkdir(parents=True)
    (ki_root / "calibration.yaml").write_text("model_id: Demo\n")
    (ki_root / "tools" / "calib_run.py").write_text("")
    calibration.ensure_project(project, [KI("Demo", ki_root)])
    try:
        result = _stoppable_call(lambda: calibration.run_project(
            project=project, ki_name="Demo", ki_path=ki_root,
            obs_shape_by_var={"Q": "point_time_series"}), started, sid)[0]
        assert not late.exists(), "the calibration engine kept writing after Stop"
        assert result["report"]["status"] in ("stopped", "interrupted")
        assert result["report"]["promotable"] is False
    finally:
        for name in ("calibration_kit", "calibration_kit.calib"):
            sys.modules.pop(name, None)


def test_builtin_setup_stops_before_later_steps(stopped_chat, tmp_path, monkeypatch):
    project, sid, _ = stopped_chat
    ki_root = tmp_path / "ki"
    ki_root.mkdir()
    started, late = tmp_path / "installer-started", tmp_path / "installer-late"
    script = f"import pathlib,time;pathlib.Path({str(started)!r}).touch();time.sleep(3)"
    monkeypatch.setattr(gui.port, "materialise", lambda *a: SimpleNamespace(
        unresolved=[], corrupted=[], tokens_replaced=0, undeliverable_files=0))
    def python_env(cfg):
        rc, out = install._run([sys.executable, "-c", script])
        return install.Step("python-env", rc == 0, out)
    monkeypatch.setattr(install, "ensure_python_env", python_env)
    def later(*a, **k):
        late.touch()
        return install.Step("later", True)
    monkeypatch.setattr(install, "install_ki_tools_common", later)
    monkeypatch.setattr(install, "check_system_deps", later)
    monkeypatch.setattr(install, "install_python_deps", later)
    monkeypatch.setattr(install, "place_where_the_ki_expects", lambda *a: [])
    monkeypatch.setattr(install, "check_data", later)
    monkeypatch.setattr(gui.handoff, "write", lambda *a: [])
    monkeypatch.setattr(gui.install_locations, "record", lambda *a, **k: None)
    man = SimpleNamespace(acquire=None, system_deps=[], python_deps=[], install_dir=None, depends_on=[])
    result = _stoppable_call(lambda: api.execute_tool(
        "run_builtin_setup", {}, KI("Demo", ki_root), paths.KissConfig.default(project),
        setup_mode=True, setup_context={"project_root": project, "run_builtin": lambda:
            gui.run_install(KI("Demo", ki_root), man, project, lambda s: True, tmp_path)}),
        started, sid)
    assert not late.exists(), "installer started new steps after Stop"
    status = json.loads((project / "status.json").read_text(encoding="utf-8"))
    assert status["ok"] is False
    assert status.get("interrupted") is True


@pytest.mark.parametrize("frozen", [False, True])
def test_worker_routing_uses_the_current_source_or_packaged_runtime(monkeypatch, tmp_path, frozen):
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    request = tmp_path / "request.json"
    prefix = [sys.executable] if frozen else [sys.executable, "-m", "kiss_cli"]
    for command, handler in ((calibration.worker_command(request), cli.cmd_calibration_worker),
                             (install.download_worker_command(request), cli.cmd_install_download_worker)):
        assert command[:len(prefix)] == prefix
        parsed = cli.build_parser().parse_args(command[len(prefix):])
        assert parsed.fn is handler
        assert parsed.request_path == request


@pytest.mark.parametrize("raw", ["{", "[]", '{}', '{"status": null}'])
def test_invalid_calibration_worker_report_never_means_success(tmp_path, raw):
    report = tmp_path / "engine-report.json"
    report.write_text(raw)
    result = calibration._worker_report(execution.ProcessRun("succeeded", 0), report)
    assert result["status"] == "engine_error"
    assert result["promotable"] is False


@pytest.mark.parametrize("status,stopped", [("stopped", False), ("interrupted", False), ("succeeded", True), ("failed", False)])
def test_cancelled_or_failed_worker_cannot_reuse_written_success(tmp_path, status, stopped):
    report = tmp_path / "engine-report.json"
    report.write_text('{"status":"completed","promotable":true}')
    result = calibration._worker_report(execution.ProcessRun(status, 1), report, stopped=stopped)
    assert result["status"] in {"stopped", "engine_error"}
    assert result["promotable"] is False


def test_download_worker_succeeds_without_external_network(tmp_path, worker_runtime):
    source = tmp_path / "source.bin"
    source.write_bytes(b"local fixture")
    project = tmp_path / "project"
    project.mkdir()
    prefix = project / "binary"
    manifest = Manifest(model="Demo", acquire=Acquire(strategy="download", url=source.as_uri(), produces="source.bin"))
    with install.cancellation_context(project):
        step, binary = install.acquire(manifest, prefix, sys.executable)
    assert step.ok, step.detail
    assert binary.read_bytes() == b"local fixture"
    assert not list(prefix.glob(".download-*"))


def test_calibration_worker_success_round_trip(tmp_path, monkeypatch, worker_runtime):
    framework = tmp_path / "framework"
    package = framework / "calibration_kit"
    package.mkdir(parents=True)
    for name in ("__init__.py", "CALIBRATION_YAML_SCHEMA.md", "CALIBRATION_FRAMEWORK_DESIGN.md"):
        (package / name).write_text("")
    (package / "calib.py").write_text(
        "def calibrate(*args, **kwargs):\n"
        "    print('local calibration fixture')\n"
        "    return {'status': 'completed', 'promotable': False, 'best_loss': 0.25}\n")
    monkeypatch.setenv("GEOFORGE_CALIBRATION_FRAMEWORK", str(framework))
    monkeypatch.setattr(calibration, "framework_status", lambda: {"ready": True})
    ki_root = tmp_path / "ki"
    (ki_root / "tools").mkdir(parents=True)
    (ki_root / "calibration.yaml").write_text("model_id: Demo\n")
    (ki_root / "tools" / "calib_run.py").write_text("")
    project = tmp_path / "project"
    calibration.ensure_project(project, [KI("Demo", ki_root)])
    result = calibration.run_project(project=project, ki_name="Demo", ki_path=ki_root,
                                      obs_shape_by_var={"Q": "point_time_series"})
    assert result["report"]["status"] == "completed", result
    assert result["report"]["best_loss"] == .25
    assert "local calibration fixture" in result["log_tail"]
    assert json.loads((project / result["report_path"]).read_text(encoding="utf-8"))["report"] == result["report"]


@pytest.mark.parametrize("worker", ["calibration", "download"])
@pytest.mark.parametrize("identity", ["stale", "wrong_project"])
def test_private_worker_refuses_inherited_stale_identity(tmp_path, monkeypatch, worker_runtime, worker, identity):
    project = tmp_path / "project"
    project.mkdir()
    old = execution.begin_turn(project)
    execution.begin_turn(project)
    owner = project if identity == "stale" else tmp_path / "other-project"
    env = execution.turn_environment(owner, turn_id=old)
    env["PYTHONPATH"] = str(Path(api.__file__).resolve().parents[1])
    source = tmp_path / "source.bin"
    source.write_bytes(b"worker must not copy")
    request = project / "request.json"
    destination = project / "binary"
    destination.mkdir()
    if worker == "download":
        request.write_text(json.dumps({"project": str(project), "acquire": {
            "strategy": "download", "url": source.as_uri(), "produces": "source.bin"},
            "prefix": str(destination), "python": sys.executable}))
        command = install.download_worker_command(request)
    else:
        framework = tmp_path / "framework"
        package = framework / "calibration_kit"
        package.mkdir(parents=True)
        for name in ("__init__.py", "CALIBRATION_YAML_SCHEMA.md", "CALIBRATION_FRAMEWORK_DESIGN.md"):
            (package / name).write_text("")
        (package / "calib.py").write_text("def calibrate(*a, **k): return {'status':'completed'}\n")
        env["GEOFORGE_CALIBRATION_FRAMEWORK"] = str(framework)
        request.write_text(json.dumps({"project": str(project), "run_dir": str(project),
                                      "runtime_ki": str(destination), "shapes": {"Q":"point"}, "seed": 0}))
        command = calibration.worker_command(request)
    # No supervising project argument: exercise the private CLI admission itself.
    result = execution.run_process(command, cwd=project, env=env, timeout=10)
    assert result.returncode == 130, result
    assert not (destination / "source.bin").exists()
    assert not (project / "engine-report.json").exists()
    assert not (project / "result.json").exists()


@pytest.mark.skipif(os.name == "nt", reason="os.mkfifo is POSIX; the blocked HTTP read below covers Windows")
def test_stop_interrupts_download_blocked_fifo_read(stopped_chat, tmp_path, worker_runtime):
    project, sid, _ = stopped_chat
    started = tmp_path / "read-started"
    source = tmp_path / "model.zip"
    os.mkfifo(source)
    release = threading.Event()
    def hold_read():
        # A FIFO holds urllib's actual file response read blocked, without a
        # listening socket or external network. Stop must kill this worker.
        with source.open("wb", buffering=0):
            started.touch()
            release.wait(10)
    source_thread = threading.Thread(target=hold_read, daemon=True)
    source_thread.start()
    prefix = project / "binary"
    manifest = Manifest(model="Demo", acquire=Acquire(strategy="download", url=source.as_uri()))
    def download():
        try:
            with install.cancellation_context(project):
                return install.acquire(manifest, prefix, sys.executable)
        except install.InstallStopped:
            return "stopped"
    try:
        assert _stoppable_call(download, started, sid) == ["stopped"]
        assert not (prefix / "model.zip").exists(), "partial bytes were published as a complete archive"
        assert not list(prefix.glob(".download-*"))
    finally:
        release.set()
        source_thread.join(2)


def test_stop_interrupts_download_blocked_http_read(stopped_chat, tmp_path, worker_runtime):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    project, sid, _ = stopped_chat
    started = tmp_path / "http-started"
    release = threading.Event()
    class SlowResponse(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "100000")
            self.end_headers()
            self.wfile.flush()
            started.touch()
            release.wait(10)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowResponse)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    prefix = project / "binary"
    manifest = Manifest(model="Demo", acquire=Acquire(strategy="download", url=f"http://127.0.0.1:{server.server_port}/model.zip"))
    def download():
        try:
            with install.cancellation_context(project):
                return install.acquire(manifest, prefix, sys.executable)
        except install.InstallStopped:
            return "stopped"
    try:
        assert _stoppable_call(download, started, sid) == ["stopped"]
        assert not (prefix / "model.zip").exists()
        assert not list(prefix.glob(".download-*"))
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        server_thread.join(2)


@pytest.mark.parametrize("boundary,expected", [("initialising", []), ("[2/8]", ["materialise", "python-env"]),
                                               ("[3/8]", ["materialise", "python-env", "common"])])
def test_installer_stop_from_emit_does_not_start_next_phase(tmp_path, monkeypatch, boundary, expected):
    project = tmp_path / "project"
    project.mkdir()
    (project / "status.json").write_text('{"ok":true,"verified_at":123,"installation_ready":true}')
    ki_root = tmp_path / "ki"
    ki_root.mkdir()
    invoked = []
    def materialise(*args):
        invoked.append("materialise")
        return SimpleNamespace(unresolved=[], corrupted=[], tokens_replaced=0, undeliverable_files=0)
    monkeypatch.setattr(gui.port, "materialise", materialise)
    def phase(name):
        def run(*args, **kwargs):
            invoked.append(name)
            return install.Step(name, True)
        return run
    monkeypatch.setattr(install, "ensure_python_env", phase("python-env"))
    monkeypatch.setattr(install, "install_ki_tools_common", phase("common"))
    monkeypatch.setattr(install, "check_system_deps", phase("system"))
    def emit(text):
        if boundary in text:
            execution.request_stop(project)
        return True
    gui.run_install(KI("Demo", ki_root), Manifest(model="Demo"), project, emit, tmp_path)
    assert invoked == expected, "a phase began after the Stop callback"
    status = json.loads((project / "status.json").read_text(encoding="utf-8"))
    assert status["ok"] is False and status["installation_ready"] is False
    assert status["verified_at"] is None and status["interrupted"] is True
