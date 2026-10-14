"""Standalone setup must retain ownership across disconnects and Stop races."""
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from contextlib import contextmanager
import io
import json
from pathlib import Path
import threading

import pytest

from kiss_cli import api, gui, install, install_locations, providers, runnable, setup, setup_jobs
from .test_setup_final_runtime import case, install_spies, saved_status, seed_success


@pytest.fixture
def ready(case, monkeypatch):
    handler = case.handler
    case.output = []
    case.responses = []
    handler._open_stream = lambda: None
    handler._end_stream = lambda: None
    handler._chunk = lambda piece: case.output.append(piece) or True
    handler._json = lambda payload, status=200: case.responses.append((status, payload))
    handler._validate_binding = lambda _req: None
    handler._helper_repo_root = lambda: case.library
    (case.root / "CLAUDE.md").write_text("Fixture setup", encoding="utf-8")
    monkeypatch.setattr(setup, "prepare", lambda *args: (case.live, case.cfg))
    monkeypatch.setattr(gui.prompt, "compose", lambda *args, **kwargs: "Fixture prompt")
    monkeypatch.setattr(setup, "agent_task", lambda *args, **kwargs: "Fixture task")
    seen = install_spies(monkeypatch)
    original = install.run_preflight

    def preflight(*args, **kwargs):
        result = original(*args, **kwargs)
        if len(seen.preflight) == 1:
            return install.Step("preflight", False, "repair needed")
        return result

    monkeypatch.setattr(install, "run_preflight", preflight)
    case.seen = seen
    return case


@pytest.mark.parametrize("kind", ["api", "cli"])
def test_provider_and_final_check_share_one_cancellation_generation(ready, monkeypatch, kind):
    c = ready
    observed = []

    def provider(*args, **kwargs):
        if kind == "api":
            context, handle = kwargs["setup_context"], kwargs["handle"]
            root = context["project_root"]
        else:
            context = kwargs["runtime_events"]
            handle, root = context["_handle"], context["project"]
        observed.append((Path(root), context["_turn_id"], handle))
        # The heartbeat worker must inherit installer cancellation too.
        assert install._CANCELLATION.get()[2] == context["_turn_id"]
        yield "Fixture provider completed.\n"

    if kind == "api":
        monkeypatch.setattr(api, "run", provider)
        want = "api:deepseek"
    else:
        fake = providers.Provider(name="fixture", binary="fixture", argv=["fixture"],
                                  output="text", label="Fixture CLI")
        monkeypatch.setitem(providers.PROVIDERS, "fixture", fake)
        monkeypatch.setattr(providers, "run", provider)
        want = "cli:fixture"
    c.handler._stream_agent_setup({"model": "Demo", "provider": want})
    job = setup_jobs.status(c.workroot, "Demo")
    assert job["state"] == "completed", (job, c.output)
    assert observed[0][:2] == (c.root, job["turn_id"])
    for _, _, _, context in c.seen.preflight:
        assert context["project"] == c.root
        assert context["turn_id"] == job["turn_id"]
        assert not context["stop"]()
    assert saved_status(c)["ok"]


def test_stop_between_final_pass_and_terminal_commit_revokes_readiness(ready, monkeypatch):
    c = ready
    seed_success(c)
    monkeypatch.setattr(api, "run", lambda *args, **kwargs: iter(["repair done\n"]))
    original = c.handler._record_agent_preflight

    def racing_final(*args, **kwargs):
        result = original(*args, **kwargs)
        assert result and saved_status(c)["ok"]
        job = setup_jobs.status(c.workroot, "Demo")
        assert not c.handler._status_for(c.ki)["can_run"]
        setup_jobs.stop(c.workroot, "Demo", job["id"])
        return result

    c.handler._record_agent_preflight = racing_final
    c.handler._stream_agent_setup({"model": "Demo", "provider": "api:deepseek"})
    assert setup_jobs.status(c.workroot, "Demo")["state"] == "cancelled"
    assert not saved_status(c)["ok"]
    assert saved_status(c)["runtime_identity"] is None
    assert not c.handler._status_for(c.ki)["can_run"]


def test_prepare_exception_is_durable_and_does_not_leave_an_active_owner(ready, monkeypatch):
    c = ready
    seed_success(c)

    def fail(*args):
        raise OSError("fixture disk failure")

    monkeypatch.setattr(setup, "prepare", fail)
    for _ in range(2):
        c.handler._stream_agent_setup({"model": "Demo", "provider": "api:deepseek"})
        job = setup_jobs.status(c.workroot, "Demo")
        assert job["state"] == "failed" and "fixture disk failure" in job["detail"]
        assert not saved_status(c)["ok"]
    assert not c.responses, "retry should reserve a new attempt rather than return 409"


def request(connection, method, route, payload=None):
    connection.request(method, route, body=json.dumps(payload) if payload else None,
                       headers={"Content-Type": "application/json"})
    response = connection.getresponse()
    return response.status, json.loads(response.read())


def test_http_disconnect_reconnect_conflicts_and_stop_without_intact_ki(ready, monkeypatch):
    c = ready
    entered, stopped = threading.Event(), threading.Event()

    def provider(*args, **kwargs):
        handle = kwargs["handle"]
        entered.set()
        yield "Waiting fixture provider.\n"
        assert handle.stopped.wait(10), "Stop must reach the API handle"
        stopped.set()
        yield "Provider stopped.\n"

    monkeypatch.setattr(api, "run", provider)
    class Handler(gui.Handler):
        workroot, repo_root, library_root = c.workroot, c.library, c.library
        catalog = type("Catalog", (), {"models_dir": c.library / "models",
                                      "get": lambda self, name: c.ki})()
        _ki = lambda self, name: c.ki
        _validate_binding = lambda self, req: None
        _helper_repo_root = lambda self: c.library
        _browser_write_allowed = lambda self: (True, "")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    stream = HTTPConnection(*server.server_address, timeout=10)
    control = HTTPConnection(*server.server_address, timeout=10)
    try:
        stream.request("POST", "/api/setup-agent", body=json.dumps({
            "model": "Demo", "provider": "api:deepseek"}))
        response = stream.getresponse()
        assert response.status == 200 and entered.wait(5)
        response.close()
        stream.close()
        code, state = request(control, "GET", "/api/setup/Demo")
        job = state["job"]
        assert code == 200 and job["state"] == "running"
        for route, payload in [
            ("/api/setup-agent", {"model": "Demo", "provider": "api:deepseek"}),
            ("/api/setup-location", {"model": "Demo", "path": str(c.workroot / "other")}),
            ("/api/setup-resume", {"model": "Demo"}),
            ("/api/setup-upload?model=Demo&name=fixture.txt", {"fixture": "bytes"}),
            ("/api/init", {"model": "Demo"}),
            ("/api/setup-stop", {"model": "Demo", "job_id": "obsolete"}),
        ]:
            code, conflict = request(control, "POST", route, payload)
            assert code == 409, (route, conflict)
            assert conflict["job"]["id"] == job["id"]
        # A source-integrity failure must not remove the status or Stop control.
        monkeypatch.setattr(Handler, "_ki", lambda self, name: (_ for _ in ()).throw(KeyError("KI draft")))
        (c.ki.root / "kiss.yaml").write_text("model: [invalid yaml", encoding="utf-8")
        code, state = request(control, "GET", "/api/setup/Demo")
        assert code == 200 and state["job"]["id"] == job["id"]
        code, result = request(control, "POST", "/api/setup-stop", {
            "model": "Demo", "job_id": job["id"]})
        assert code == 200 and result["job"]["state"] in {"stopping", "cancelled"}
        assert stopped.wait(5)
        # HTTP stream completion and job finalization occur on separate threads.
        import time
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            code, state = request(control, "GET", "/api/setup/Demo")
            if state["job"]["state"] == "cancelled":
                break
            threading.Event().wait(0.05)
        assert state["job"]["state"] == "cancelled"
        assert not state["software"]["can_run"]
        assert "Waiting fixture provider" in state["log_tail"]
    finally:
        setup_jobs.stop_all()
        stream.close()
        control.close()
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_source_changed_during_setup_cannot_claim_completed(ready, monkeypatch):
    c = ready
    def provider(*args, **kwargs):
        (c.ki.root / "SKILL.md").write_text("Changed source", encoding="utf-8")
        yield "Provider returned.\n"
    monkeypatch.setattr(api, "run", provider)
    c.handler._stream_agent_setup({"model": "Demo", "provider": "api:deepseek"})
    assert setup_jobs.status(c.workroot, "Demo")["state"] == "failed"
    assert not c.handler._status_for(c.ki)["can_run"]
    assert not any("verified and ready" in piece for piece in c.output)


@pytest.mark.parametrize("stop_write_fails", [False, True])
def test_consumer_failure_keeps_lease_until_provider_really_exits(ready, monkeypatch, stop_write_fails):
    c = ready
    entered, observed_stop, release = (threading.Event() for _ in range(3))
    def provider(*args, **kwargs):
        entered.set()
        yield "provider piece\n"
        assert kwargs["handle"].stopped.wait(5)
        observed_stop.set()
        assert release.wait(5)
    monkeypatch.setattr(api, "run", provider)
    if stop_write_fails:
        def fail_stop(*args, **kwargs):
            raise OSError("fixture stop persistence failure")
        monkeypatch.setattr(setup_jobs, "stop", fail_stop)
    def broken_display(piece):
        if "provider piece" in piece:
            raise OSError("fixture consumer failure")
        return True
    c.handler._chunk = broken_display
    worker = threading.Thread(target=c.handler._stream_agent_setup,
                              args=({"model": "Demo", "provider": "api:deepseek"},))
    worker.start()
    try:
        assert entered.wait(5) and observed_stop.wait(5)
        assert setup_jobs.status(c.workroot, "Demo")["state"] == (
            "running" if stop_write_fails else "stopping")
        assert worker.is_alive()
        with pytest.raises(setup_jobs.BusyError):
            setup_jobs.start(c.workroot, "Demo", c.root, "builtin")
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert setup_jobs.status(c.workroot, "Demo")["state"] == "cancelled"
    assert not saved_status(c)["ok"]


@pytest.mark.parametrize("route", ["/api/setup-location", "/api/setup-resume",
                                    "/api/setup-upload?model=Demo&name=fixture.txt"])
def test_location_change_before_reservation_rejects_stale_mutation(ready, monkeypatch, route):
    c = ready
    changed = c.workroot / "replacement"
    original_guard = setup_jobs.idle_guard
    writes = []

    @contextmanager
    def interleaved_guard(*args, **kwargs):
        # The other location request commits after this request resolved its
        # root, but before it acquired the model lease.
        install_locations.select(c.workroot, "Demo", changed)
        with original_guard(*args, **kwargs):
            yield

    monkeypatch.setattr(setup_jobs, "idle_guard", interleaved_guard)
    monkeypatch.setattr(install_locations, "record", lambda *args, **kwargs: writes.append("record"))
    monkeypatch.setattr(setup, "resume", lambda *args, **kwargs: writes.append("resume"))
    monkeypatch.setattr(setup, "save_upload", lambda *args, **kwargs: writes.append("upload"))
    body = json.dumps({"model": "Demo", "installation_mode": "existing"}).encode()
    c.handler.path = route
    c.handler.headers = {"Content-Length": str(len(body))}
    c.handler.rfile = io.BytesIO(body)
    c.handler._browser_write_allowed = lambda: (True, "")
    c.handler.do_POST()
    assert c.responses[-1][0] == 409
    assert "changed" in c.responses[-1][1]["error"]
    assert writes == []


@pytest.mark.parametrize("stage", ["initial", "final", "installation-only"])
def test_stop_during_host_check_cannot_publish_pass(ready, monkeypatch, stage):
    c = ready
    provider_calls = []
    def provider(*args, **kwargs):
        provider_calls.append(True)
        yield "Provider finished\n"
    monkeypatch.setattr(api, "run", provider)
    original = install.run_preflight

    def cancel():
        job = setup_jobs.status(c.workroot, "Demo")
        setup_jobs.stop(c.workroot, "Demo", job["id"])

    def preflight(*args, **kwargs):
        if stage == "initial" or provider_calls:
            cancel()
            return install.Step("preflight", True, "check returned just after Stop")
        return original(*args, **kwargs)

    def probe(*args, **kwargs):
        cancel()
        return runnable.Verdict("Demo", present=True, shaped=True, linked=True, responds=True)

    monkeypatch.setattr(install, "run_preflight", preflight)
    if stage == "installation-only":
        monkeypatch.setattr(runnable, "check", probe)
    c.handler._stream_agent_setup({"model": "Demo", "provider": "api:deepseek",
                                    "installation_only": stage == "installation-only"})
    assert setup_jobs.status(c.workroot, "Demo")["state"] == "cancelled"
    assert not saved_status(c)["ok"]
    if stage == "initial":
        assert provider_calls == []
    if stage == "installation-only":
        assert not (c.root / "installation-test.json").exists()
