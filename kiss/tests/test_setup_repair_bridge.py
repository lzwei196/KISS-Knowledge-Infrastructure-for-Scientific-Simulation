"""Provider handoff cannot adopt while a tool worker is using the KI."""
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import api, cli, gui, providers, setup, setup_repair_bridge as bridge
from .test_setup_final_runtime import case
from .test_gui_setup_jobs import ready


@pytest.fixture
def capability(tmp_path):
    calls = []
    cap = bridge.Capability(tmp_path, "turn", lambda issue: calls.append(issue) or
                            {"queued": True}, stopped=lambda: False)
    yield cap, calls
    cap.close()


def token(cap):
    return cap.environment("http://127.0.0.1:9876" + bridge.ENDPOINT)["GEOFORGE_SETUP_REPAIR_TOKEN"]


def test_only_issue_can_be_submitted_and_closed_turn_is_revoked(capability):
    cap, calls = capability
    tok = token(cap)
    assert bridge.invoke(tok, {"issue": "wrong Windows paths"})["queued"]
    for payload in ({"issue": "x", "candidate": "elsewhere"},
                    {"issue": "x", "verification_id": "invented"}, {}, [],
                    {"issue": ""}, {"issue": "x" * 2001}):
        with pytest.raises(ValueError):
            bridge.invoke(tok, payload)
    assert calls == ["wrong Windows paths"]
    cap.close()
    with pytest.raises(PermissionError):
        bridge.invoke(tok, {"issue": "again"})
    with pytest.raises(ValueError):
        cap.call("again")


def test_api_cannot_grant_itself_repair_authority(case):
    assert "request_ki_repair" not in {x["name"] for x in api.tool_schemas(case.live)}
    schema = next(x for x in api.tool_schemas(case.live, setup_mode=True)
                  if x["name"] == "request_ki_repair")
    assert schema["input_schema"]["additionalProperties"] is False
    with pytest.raises(api.ToolError, match="capability"):
        api.execute_tool("request_ki_repair", {"issue": "bad path"}, case.live,
                         case.cfg, setup_mode=True)
    calls = []
    context = {"request_ki_repair": lambda issue: calls.append(issue) or {"queued": True}}
    assert json.loads(api.execute_tool("request_ki_repair", {"issue": "bad path"},
        case.live, case.cfg, setup_mode=True, setup_context=context))["queued"]
    with pytest.raises(api.ToolError, match="only issue"):
        api.execute_tool("request_ki_repair", {"issue": "bad", "root": "elsewhere"},
                         case.live, case.cfg, setup_mode=True, setup_context=context)
    assert calls == ["bad path"]


def test_http_rejects_browser_and_wrong_token(capability):
    cap, calls = capability
    def invoke(headers):
        payload = json.dumps({"issue": "binary path mismatch"}).encode()
        responses = []
        handler = SimpleNamespace(headers=headers, rfile=io.BytesIO(payload),
            _json=lambda data, status=200: responses.append((status, data)))
        gui.Handler._post_agent_setup_repair(handler, len(payload))
        return responses[0]
    assert invoke({"X-GeoForge-Agent-Token": token(cap)})[0] == 401
    assert invoke({"X-GeoForge-Setup-Token": token(cap), "Origin": "http://127.0.0.1:9876"})[0] == 403
    assert not calls
    assert invoke({"X-GeoForge-Setup-Token": token(cap)}) == (200, {"queued": True})


def test_cli_transport_keeps_target_and_token_in_host_environment(capability, monkeypatch, tmp_path):
    cap, _ = capability
    for name, value in cap.environment("http://127.0.0.1:9876" + bridge.ENDPOINT).items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(tmp_path)
    requests = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return b'{"queued":true}'
    class Opener:
        def open(self, request, **kw):
            requests.append(request)
            return Response()
    def opener(*handlers):
        assert handlers[0].proxies == {} and isinstance(handlers[1], bridge._NoRedirect)
        return Opener()
    monkeypatch.setattr(bridge, "build_opener", opener)
    assert cli.main(["request-ki-repair", "--issue", "real defect"]) == 0
    assert json.loads(requests[0].data) == {"issue": "real defect"}
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    with pytest.raises(ValueError, match="exact workspace"):
        bridge.request("real defect")
    assert len(requests) == 1


@pytest.mark.parametrize("url", ["https://example.com" + bridge.ENDPOINT,
    "http://127.0.0.1:1234/wrong", "http://user@127.0.0.1:1234" + bridge.ENDPOINT,
    "http://127.0.0.1:1234" + bridge.ENDPOINT + "?token=x"])
def test_capability_never_sent_elsewhere(capability, url):
    with pytest.raises(ValueError):
        capability[0].environment(url)


def test_no_cli_capability_and_no_fake_complete_kdt_promise(monkeypatch):
    for name in ("URL", "TOKEN", "ROOT"):
        monkeypatch.delenv("GEOFORGE_SETUP_REPAIR_" + name, raising=False)
    assert cli.main(["request-ki-repair", "--issue", "real defect"]) == 3
    assert "request-ki-repair" in setup.ki_repair_guidance(available=True, cli=True)
    assert "No host KI repair" in setup.ki_repair_guidance(available=False)


def test_api_yields_host_handoff_before_any_later_tools(case, monkeypatch):
    from .test_api_handoff import PROV
    monkeypatch.setenv("DEMO_API_KEY", "test")
    turns, tools = [], []
    def response(*args, **kwargs):
        turns.append(True)
        return "", [("a", "request_ki_repair", {"issue": "bad path"}),
                    ("b", "run_command", {"command": ["unsafe"]})], {}
    def execute(name, *args, **kwargs):
        tools.append(name)
        return '{"queued":true}'
    monkeypatch.setattr(api, "_openai_turn", response)
    monkeypatch.setattr(api, "execute_tool", execute)
    out = "".join(api.run(PROV, case.live, case.cfg, "system", "task", setup_mode=True))
    assert tools == ["request_ki_repair"] and len(turns) == 1
    assert "host KDT workflow" in out


@pytest.mark.parametrize("provider_name", ["api:deepseek", *["cli:" + name for name in providers.PROVIDERS]])
def test_every_provider_queues_then_host_repairs_and_rechecks(ready, monkeypatch, provider_name):
    from kiss_cli import setup_ki_repair, setup_jobs
    c, events, retained = ready, [], []
    c.handler.agent_setup_url = "http://127.0.0.1:9876/api/agent/setup-python-runtime"
    monkeypatch.setattr(setup_ki_repair, "recipe_for", lambda name: "fixture_recipe")
    def provider(*args, **kw):
        events.append("provider")
        if provider_name.startswith("api:"):
            call = kw["setup_context"]["request_ki_repair"]
            instruction = args[3]
        else:
            env = kw["extra_env"]
            tok = env["GEOFORGE_SETUP_REPAIR_TOKEN"]
            call = lambda issue: bridge.invoke(tok, {"issue": issue})
            instruction = args[1]
            assert "request-ki-repair" in instruction and tok not in instruction
        retained.append(call)
        assert call("wrong runtime paths")["queued"]
        assert "HOST KI MAINTENANCE" in instruction
        yield "handoff queued\n"
        events.append("provider_drained")
    def repair(root, **kw):
        assert events == ["provider", "provider_drained"]
        with pytest.raises((ValueError, PermissionError)):
            retained[0]("late request")
        assert root == c.root and kw["source_root"] == c.ki.root
        kw["check_binding"]()
        events.append("repair")
        return {"status": "applied"}
    original = c.handler._record_agent_preflight
    def final(*args, **kwargs):
        if "repair" in events:
            events.append("fresh_preflight")
        return original(*args, **kwargs)
    monkeypatch.setattr(api, "run", provider)
    monkeypatch.setattr(providers, "run", provider)
    monkeypatch.setattr(setup_ki_repair, "run", repair)
    monkeypatch.setattr(setup_ki_repair, "finish_preflight", lambda *a, **kw: None)
    c.handler._record_agent_preflight = final
    c.handler._stream_agent_setup({"model": "Demo", "provider": provider_name})
    assert events == ["provider", "provider_drained", "repair", "fresh_preflight"], c.output
    assert setup_jobs.status(c.workroot, "Demo")["state"] == "completed", c.output


def test_failed_kdt_handoff_cannot_reach_success_preflight(ready, monkeypatch):
    from kiss_cli import setup_ki_repair, setup_jobs
    c = ready
    monkeypatch.setattr(setup_ki_repair, "recipe_for", lambda name: "fixture_recipe")
    def provider(*args, **kwargs):
        assert kwargs["setup_context"]["request_ki_repair"]("defect")["queued"]
        yield "handoff queued"
    monkeypatch.setattr(api, "run", provider)
    monkeypatch.setattr(setup_ki_repair, "run", lambda *args, **kwargs: {"status": "verification_failed"})
    c.handler._stream_agent_setup({"model": "Demo", "provider": "api:deepseek"})
    assert setup_jobs.status(c.workroot, "Demo")["state"] == "failed"
    assert len(c.seen.preflight) == 1
