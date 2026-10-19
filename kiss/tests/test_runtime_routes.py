"""Real GUI route admission with a fake manager; no guest/model execution."""
import io
import json
from types import SimpleNamespace

import pytest

from kiss_cli import gui, runtime_context


class Manager:
    def __init__(self):
        self.calls = []

    def launch(self, **kwargs):
        self.calls.append(("launch", kwargs))
        return {"state": "starting", "detail": "Model installation remains separate"}

    def stop(self):
        self.calls.append(("stop",))
        return {"state": "stopping"}

    def describe(self):
        self.calls.append(("describe",))
        return {"available": True, "distributions": [{"distro": "Ubuntu"}]}

    def status(self):
        self.calls.append(("status",))
        return {"state": "ready", "url": "http://127.0.0.1:18880/"}


@pytest.fixture
def manager(monkeypatch):
    value = Manager()
    monkeypatch.setattr(gui.Handler, "linux_sidecar_manager", value, raising=False)
    monkeypatch.setattr(gui.settings, "load", lambda: {"api_keys": {"DEEPSEEK_API_KEY": "test-key"}})
    return value


def request(path, body=None, *, cookie="geoforge_csrf_8800=test-token", origin="http://127.0.0.1:8800",
            site="same-origin", length=None):
    raw = json.dumps(body if body is not None else {}).encode()
    handler = object.__new__(gui.Handler)
    handler.path = path
    handler.server = SimpleNamespace(server_port=8800)
    handler.csrf_token = "test-token"
    handler.headers = {"Content-Length": str(len(raw) if length is None else length),
                       "Cookie": cookie, "Origin": origin, "Host": "127.0.0.1:8800", "Sec-Fetch-Site": site}
    handler.rfile = io.BytesIO(raw)
    handler._json = lambda value, code=200: (code, value)
    return handler


@pytest.mark.parametrize("route", ["/api/runtime/start", "/api/runtime/stop"])
@pytest.mark.parametrize("headers", [
    {"cookie": ""}, {"cookie": "geoforge_csrf_18880=test-token"},
    {"cookie": "geoforge_csrf_8800=wrong"}, {"origin": "http://untrusted.example"},
    {"site": "cross-site"},
])
def test_runtime_mutation_requires_this_servers_browser_authority(manager, route, headers):
    code, result = request(route, {"distro": "Ubuntu", "user": "scientist"}, **headers).do_POST()
    assert code == 403 and "blocked unsafe local request" in result["error"]
    assert manager.calls == []


def test_start_passes_only_explicit_selection_to_host_manager(manager):
    code, result = request("/api/runtime/start", {"distro": "Ubuntu", "user": "scientist",
                                               "provider": "api:deepseek"}).do_POST()
    assert code == 200 and result["state"] == "starting"
    assert manager.calls == [("launch", {"distro": "Ubuntu", "user": "scientist",
        "provider_id": "api:deepseek", "provider_settings": {"api_keys": {"DEEPSEEK_API_KEY": "test-key"}}})]
    assert "test-key" not in json.dumps(result)
    assert not any(result.get(key) for key in ("installation_ready", "model_readiness", "can_run"))


@pytest.mark.parametrize("body", [
    [], {"distro": "Ubuntu", "user": "scientist", "command": "anything"},
    {"distro": "Ubuntu", "user": "scientist", "workspace": "/other"},
    {"distro": "Ubuntu", "user": "scientist", "provider": "cli:claude"},
    {"distro": "Ubuntu", "user": "scientist", "provider": "api:unknown"},
])
def test_runtime_start_rejects_injected_dispatch_and_provider_fields(manager, body):
    code, result = request("/api/runtime/start", body).do_POST()
    assert code == 409 and result["error"]
    assert manager.calls == []


def test_runtime_start_rejects_large_request_before_read(manager):
    handler = request("/api/runtime/start", length=8193)
    code, _ = handler.do_POST()
    assert code == 413 and handler.rfile.tell() == 0
    assert manager.calls == []


def test_stop_only_calls_this_hosts_manager(manager):
    assert request("/api/runtime/stop").do_POST() == (200, {"state": "stopping"})
    assert manager.calls == [("stop",)]


def test_linux_server_cannot_recursively_launch_wsl(monkeypatch):
    monkeypatch.setattr(gui.Handler, "linux_sidecar_manager", None, raising=False)
    code, body = request("/api/runtime/start").do_POST()
    assert code == 409 and "Windows host" in body["error"]


def test_identity_endpoint_matches_exact_supervisor_challenge(monkeypatch):
    identity = {"kind": "wsl", "platform": "Linux", "machine": "x86_64", "id": "a"*32,
                "distro": "Ubuntu", "user": "scientist", "workspace": "/home/scientist/runtime",
                "source_hash": "b"*64, "nonce": "private-startup-challenge"}
    monkeypatch.setattr(runtime_context, "identity", lambda: identity)
    code, body = request("/api/runtime/identity").do_GET()
    assert code == 200
    assert body == {key: identity[key] for key in ("id", "distro", "user", "workspace", "source_hash", "nonce")}


def test_native_linux_status_offers_no_recursive_distributions(monkeypatch):
    monkeypatch.setattr(gui.Handler, "linux_sidecar_manager", None, raising=False)
    monkeypatch.setattr(runtime_context, "binding", lambda: {"kind": "wsl", "platform": "Linux"})
    code, body = request("/api/runtime/status").do_GET()
    assert code == 200 and body["distributions"] == []
    assert body["identity"]["kind"] == "wsl"


@pytest.mark.parametrize("route, operation", [("choices", "describe"), ("status", "status")])
def test_runtime_get_uses_host_supervisor_status(manager, route, operation):
    code, _body = request("/api/runtime/" + route).do_GET()
    assert code == 200 and manager.calls == [(operation,)]
