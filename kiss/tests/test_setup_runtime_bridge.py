"""The API and every CLI use one fresh-turn, version-only host operation."""
import io
import json
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from kiss_cli import api, cli, gui, install, providers, setup, setup_bridge, setup_runtime
from .test_gui_setup_jobs import ready
from .test_setup_final_runtime import case


@pytest.fixture
def capability(tmp_path):
    calls = []
    cap = setup_bridge.Capability(tmp_path, "turn-a",
        lambda version, **kw: calls.append((version, kw)) or {"ok": True, "python_version": version},
        stopped=lambda: False)
    yield cap, calls
    cap.close()


def token(cap):
    return cap.environment("http://127.0.0.1:9876" + setup_bridge.ENDPOINT)["GEOFORGE_SETUP_RUNTIME_TOKEN"]


def test_host_accepts_only_version_and_keeps_root_in_host(capability, tmp_path):
    cap, calls = capability
    assert setup_bridge.invoke(token(cap), {"version": "3.12.9"})["ok"]
    assert calls[0][0] == "3.12.9" and set(calls[0][1]) == {"stop"}
    assert cap.root == tmp_path.resolve() and cap.turn_id == "turn-a"
    for payload in ({"version": "3.12.9", "root": str(tmp_path / "elsewhere")},
                    {"version": "3.12.9", "url": "https://example.invalid/runtime"},
                    {"version": "3.12.9", "argv": ["python", "-c", "evil"]},
                    {"version": "3"}, {"version": "3.12.9;evil"}, [], {}):
        with pytest.raises(ValueError):
            setup_bridge.invoke(token(cap), payload)
    assert len(calls) == 1
    assert setup_bridge.invoke(token(cap), {"version": "3.12"})["ok"]


def test_wrong_expired_and_stopped_capabilities_cannot_execute(capability):
    cap, calls = capability
    old = token(cap)
    with pytest.raises(PermissionError):
        setup_bridge.invoke("wrong", {"version": "3.12.9"})
    cap.close()
    with pytest.raises(PermissionError):
        setup_bridge.invoke(old, {"version": "3.12.9"})
    with pytest.raises(ValueError):
        cap.call("3.12.9")
    assert not calls


def test_only_one_operation_and_close_cancels_and_joins_it(tmp_path):
    entered, exited = threading.Event(), threading.Event()
    def operation(version, *, stop):
        entered.set()
        while not stop():
            exited.wait(.01)
        exited.set()
        return {"ok": False}
    cap = setup_bridge.Capability(tmp_path, "a", operation, stopped=lambda: False)
    worker = threading.Thread(target=cap.call, args=("3.12.9",))
    worker.start()
    assert entered.wait(2)
    with pytest.raises(ValueError, match="already running"):
        cap.call("3.12.9")
    cap.close()
    worker.join(2)
    assert exited.is_set() and not worker.is_alive()


def test_cli_uses_version_only_no_proxy_and_bound_current_directory(capability, monkeypatch, tmp_path):
    cap, _ = capability
    env = cap.environment("http://127.0.0.1:9876" + setup_bridge.ENDPOINT)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(tmp_path)
    requests = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return b'{"ok":true}'
    class Opener:
        def open(self, request, **kw):
            requests.append(request)
            return Response()
    def opener(*handlers):
        assert handlers[0].proxies == {}
        assert isinstance(handlers[1], setup_bridge._NoRedirect)
        return Opener()
    monkeypatch.setattr(setup_bridge, "build_opener", opener)
    assert cli.main(["prepare-python-runtime", "--version", "3.12.9"]) == 0
    assert json.loads(requests[0].data) == {"version": "3.12.9"}
    assert requests[0].get_header("X-geoforge-setup-token") == token(cap)
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    with pytest.raises(ValueError, match="exact workspace"):
        setup_bridge.request("3.12.9")
    assert len(requests) == 1


@pytest.mark.parametrize("url", ["https://example.com/api/agent/setup-python-runtime",
    "http://127.0.0.1:1234/wrong", "http://user@127.0.0.1:1234/api/agent/setup-python-runtime",
    "http://127.0.0.1:1234/api/agent/setup-python-runtime?token=x"])
def test_capability_never_sent_to_another_endpoint(capability, url):
    with pytest.raises(ValueError):
        capability[0].environment(url)


def test_cli_cannot_issue_its_own_capability(monkeypatch):
    for name in ("URL", "TOKEN", "ROOT"):
        monkeypatch.delenv("GEOFORGE_SETUP_RUNTIME_" + name, raising=False)
    assert cli.main(["prepare-python-runtime", "--version", "3.12.9"]) == 3
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["prepare-python-runtime", "--version", "3.12.9", "--root", "elsewhere"])


def test_api_tool_is_setup_only_strict_and_does_not_grant_authority(case):
    assert "prepare_python_runtime" not in {s["name"] for s in api.tool_schemas(case.live)}
    schema = next(s for s in api.tool_schemas(case.live, setup_mode=True)
                  if s["name"] == "prepare_python_runtime")
    assert schema["input_schema"]["additionalProperties"] is False
    with pytest.raises(api.ToolError, match="active fresh"):
        api.execute_tool("prepare_python_runtime", {"version": "3.12.9"}, case.live, case.cfg, setup_mode=True)
    called = []
    context = {"prepare_python_runtime": lambda version: called.append(version) or {"ok": True}}
    result = api.execute_tool("prepare_python_runtime", {"version": "3.12.9"}, case.live,
                              case.cfg, setup_mode=True, setup_context=context)
    assert json.loads(result)["ok"] and called == ["3.12.9"]
    for payload in ({"version": "3.12.9", "path": "evil"}, {"version": "3.12;evil"}):
        with pytest.raises(api.ToolError):
            api.execute_tool("prepare_python_runtime", payload, case.live, case.cfg,
                             setup_mode=True, setup_context=context)
    assert called == ["3.12.9"]


def test_http_requires_separate_token_and_rejects_browser_origin(capability):
    cap, calls = capability
    def request(headers, payload):
        blob = json.dumps(payload).encode()
        response = []
        handler = SimpleNamespace(headers=headers, rfile=io.BytesIO(blob),
            _json=lambda data, status=200: response.append((status, data)))
        gui.Handler._post_agent_setup_runtime(handler, len(blob))
        return response[0]
    assert request({"X-GeoForge-Agent-Token": token(cap)}, {"version": "3.12.9"})[0] == 401
    assert request({"X-GeoForge-Setup-Token": token(cap), "Origin": "http://127.0.0.1:9876"},
                   {"version": "3.12.9"})[0] == 403
    assert not calls
    assert request({"X-GeoForge-Setup-Token": token(cap)}, {"version": "3.12.9"})[0] == 200


@pytest.mark.parametrize("provider_name", ["api:deepseek", *["cli:" + name for name in providers.PROVIDERS]])
def test_every_provider_gets_same_live_host_operation_and_lifetime(ready, monkeypatch, provider_name):
    c, ticket, calls, retained = ready, object(), [], []
    monkeypatch.setattr(setup_runtime, "begin", lambda *a, **kw: ticket)
    monkeypatch.setattr(setup_runtime, "capture", lambda *a, **kw: None)
    monkeypatch.setattr(setup_runtime, "refresh", lambda *a, **kw: None)
    monkeypatch.setattr(setup_runtime, "close", lambda value: calls.append(("close", value)))
    # Import remains local to the callback, so this seam does not download or
    # replace a real interpreter in a GUI fixture.
    import sys
    def bootstrap(value, ki, live, cfg, **kw):
        context = install._CANCELLATION.get()
        assert value is ticket and cfg is c.cfg and Path(context[0]) == c.root
        assert context[2] and not context[1]()
        calls.append(("runtime", kw["version"], kw["library_root"]))
        return {"ok": True, "python_version": kw["version"]}
    import kiss_cli
    bootstrap_module = SimpleNamespace(prepare_python_runtime=bootstrap)
    monkeypatch.setitem(sys.modules, "kiss_cli.python_bootstrap", bootstrap_module)
    monkeypatch.setattr(kiss_cli, "python_bootstrap", bootstrap_module, raising=False)
    c.handler.agent_setup_url = "http://127.0.0.1:9876" + setup_bridge.ENDPOINT
    original_final = c.handler._record_agent_preflight
    def final(*args, **kwargs):
        with pytest.raises((ValueError, PermissionError)):
            retained[0]("3.12")
        return original_final(*args, **kwargs)
    c.handler._record_agent_preflight = final
    def provider(*args, **kw):
        if provider_name.startswith("api:"):
            callback = kw["setup_context"]["prepare_python_runtime"]
            result = callback("3.12")
            retained.append(callback)
            instruction = args[3]
        else:
            env = kw["extra_env"]
            assert Path(env["GEOFORGE_SETUP_RUNTIME_ROOT"]) == c.root
            capability_token = env["GEOFORGE_SETUP_RUNTIME_TOKEN"]
            replies, errors = [], []
            def http_worker():
                try:
                    replies.append(setup_bridge.invoke(capability_token, {"version": "3.12"}))
                except BaseException as error:
                    errors.append(error)
            worker = threading.Thread(target=http_worker)
            worker.start()
            worker.join(5)
            assert not worker.is_alive() and not errors
            result = replies[0]
            retained.append(lambda version: setup_bridge.invoke(capability_token, {"version": version}))
            instruction = args[1]
            assert "prepare-python-runtime" in instruction
            assert capability_token not in instruction
        assert result["ok"] and "Never retry" in instruction and "OS sandbox" in instruction
        yield "Fixture runtime prepared; host checks still required.\n"
    monkeypatch.setattr(api, "run", provider)
    monkeypatch.setattr(providers, "run", provider)
    c.handler._stream_agent_setup({"model": "Demo", "provider": provider_name})
    assert [row[0] for row in calls] == ["runtime", "close"], c.output
    assert calls[0][1:] == ("3.12", c.library)
    with pytest.raises((ValueError, PermissionError)):
        retained[0]("3.12.9")
    assert len(c.seen.preflight) >= 2, "bootstrap does not replace final preflight"


def test_guidance_preserves_kdt_and_does_not_claim_os_sandbox():
    text = setup.runtime_bootstrap_guidance(available=True, cli=True)
    for expected in ("KDT", "preflight", "wrapper", "child script", "OS sandbox", "prepare-python-runtime"):
        assert expected in text
    assert "No fresh runtime capability" in setup.runtime_bootstrap_guidance(available=False)


def test_cli_runtime_command_does_not_grant_all_host_python_arguments(ready, monkeypatch):
    import sys
    from kiss_cli import policy
    c = ready
    monkeypatch.setattr(setup_runtime, "begin", lambda *a, **kw: object())
    for name in ("capture", "refresh", "close"):
        monkeypatch.setattr(setup_runtime, name, lambda *a, **kw: None)
    # An empty initial policy exposes only grants added by the setup runner.
    # The normal fixture uses the host Python as its configured KI interpreter,
    # which would otherwise mask a duplicate broad host-executable grant.
    monkeypatch.setattr(policy.Policy, "derive", classmethod(lambda cls, *a, **kw: cls("Demo")))
    c.handler.agent_setup_url = "http://127.0.0.1:9876" + setup_bridge.ENDPOINT
    seen = []
    def provider(*args, **kwargs):
        seen.append(kwargs["pol"])
        assert "prepare-python-runtime" in args[1]
        assert kwargs["extra_env"]["GEOFORGE_SETUP_RUNTIME_TOKEN"]
        yield "Fixture CLI complete.\n"
    monkeypatch.setattr(providers, "run", provider)
    c.handler._stream_agent_setup({"model": "Demo", "provider": "cli:claude"})
    assert seen, c.output
    assert not any(grant.kind == "exec" and grant.path == str(Path(sys.executable))
                   for grant in seen[0].grants)
