"""A reused HTTP connection must not retain an obsolete setup destination."""
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest

from kiss_cli import gui


@pytest.fixture
def location_server(tmp_path, monkeypatch):
    ki = SimpleNamespace(name="DSSAT", root=tmp_path / "ki" / "DSSAT")
    setup_roots = []
    handlers = []

    class Handler(gui.Handler):
        workroot = tmp_path / "default-workroot"
        catalog = [ki]

        def setup(self):
            super().setup()
            handlers.append(self)

        def _ki(self, name):
            assert name == ki.name
            return ki

        def _status_for(self, model):
            # Keep this regression independent of model engines and KI gates.
            # Production /api/status uses this same cached path resolver.
            return {"workspace": str(self._workdir(model))}

        def _browser_write_allowed(self):
            return True, ""

        def _validate_binding(self, req):
            return None

    def waiting_at(root):
        # Exercise the real setup route, stopping before it opens an agent.
        setup_roots.append(root)
        return {"status": "waiting"}

    monkeypatch.setattr(gui.setup_flow, "request", waiting_at)
    monkeypatch.setattr(gui.install, "runtime_python", lambda value: value)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connections = []

    def connect():
        connection = HTTPConnection(*server.server_address, timeout=5)
        connections.append(connection)
        return connection

    yield SimpleNamespace(connect=connect, roots=setup_roots,
                          handlers=handlers, workroot=Handler.workroot)
    for connection in connections:
        connection.close()
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def request(connection, method, route, payload=None):
    body = json.dumps(payload) if payload is not None else None
    connection.request(method, route, body=body,
                       headers={"Content-Type": "application/json"})
    response = connection.getresponse()
    return response.status, json.loads(response.read())


@pytest.mark.parametrize("save_on_another_connection", [False, True])
def test_setup_uses_new_location_after_status_on_same_connection(
        location_server, tmp_path, save_on_another_connection):
    env = location_server
    connection = env.connect()
    status, before = request(connection, "GET", "/api/status")
    assert status == 200
    assert Path(before["DSSAT"]["workspace"]) == env.workroot / "dssat"
    original_socket = connection.sock
    original_handler = env.handlers[0]

    writer = env.connect() if save_on_another_connection else connection
    # Cover both first-time selection and relocation of an existing selection.
    for name in ("first-choice", "second-choice"):
        target = tmp_path / name / "DSSAT"
        status, saved = request(writer, "POST", "/api/setup-location", {
            "model": "DSSAT", "installation_mode": "new", "path": str(target),
        })
        assert status == 200
        assert Path(saved["install_location"]["path"]) == target

        status, _ = request(connection, "POST", "/api/setup-agent", {
            "model": "DSSAT", "provider": "api:fixture",
        })
        assert status == 409  # the harmless waiting sentinel, never an agent
        assert env.roots[-1] == target
        assert connection.sock is original_socket
        assert env.handlers[0] is original_handler

        status, after = request(connection, "GET", "/api/status")
        assert status == 200
        assert Path(after["DSSAT"]["workspace"]) == target
