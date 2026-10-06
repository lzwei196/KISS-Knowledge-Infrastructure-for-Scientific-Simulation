"""Prepared-input estimates cross the real Desktop entrypoints without acquisition.

Fake remote HTTP responses, synthetic KI/project, and an in-memory browser handler:
no Database credentials, provider calls, real network, or native model runs.
"""
from __future__ import annotations

import copy
import io
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from kiss_cli import api, cli, flowgate, flowrun, gui, obs_access, obs_subset, sessions
from .test_flowgate import _cfg, _ki, _session
from .test_obs_access import Opener, json_response
from .test_obs_subset import BODY as RAW_REQUEST, EST as RAW_ESTIMATE


SID = "123456abcdef"
COOKIE = "synthetic-preparation-cookie"
CAPABILITY = "synthetic-process-capability"
HOST_TOKEN = "synthetic-host-only-database-token"
SHAW_REQUEST = {
    "model": "shaw", "source": "cmfd", "mode": "daily", "lat": 47.43,
    "lon": 126.97, "start": "2003-10-01", "end": "2004-05-31",
}
CRHM_REQUEST = {
    "model": "crhm", "source": "nasa_power", "mode": "hourly", "lat": 49.17,
    "lon": 125.23, "start": "2003-10-01", "end": "2004-05-31",
}
VIC_REQUEST = {
    "model": "vic", "source": "cmfd", "mode": "3-hourly",
    "bbox": [115.25, 32.75, 115.75, 33.25], "grid_res": 0.25,
    "start": "2002-01-01", "end": "2003-12-31",
}


def _estimate(body, blockers=()):
    """Synthetic public server estimate; no scientific-data success is implied."""
    return {
        "contract_version": "ki_prepare/1", "preparable": True,
        "model": body["model"], "source": body["source"], "mode": body["mode"],
        "ki_version": "test-ki-v1", "tool_hash": "a" * 64,
        "blockers": list(blockers),
        "source_cadence": "hourly" if body["source"] == "nasa_power" else "3-hourly",
        "transforms": ["derive required weather fields from native samples"],
        "outputs": [{"name": "synthetic-forcing.dat", "role": "weather", "format": "test"}],
    }


@pytest.fixture(autouse=True)
def _isolated_host(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry.json"))
    monkeypatch.setattr(gui.settings, "load", lambda: {})
    monkeypatch.setattr(gui.Handler, "agent_database_token", CAPABILITY)


def _client(monkeypatch, *payloads):
    opener = Opener(*(json_response(value) for value in payloads))
    client = obs_access.Client(opener=opener, token_getter=lambda: HOST_TOKEN)
    monkeypatch.setattr(obs_access, "Client", lambda: client)
    return client, opener


def _planning(tmp_path):
    ki = _ki(tmp_path)
    project, flow = _session(tmp_path, ki, [
        ("task_received", None), ("kis_resolved", {"selected_kis": [ki.name]}),
    ])
    return ki, project, flow


def _snapshot(project):
    return {str(path.relative_to(project)): path.read_bytes()
            for path in project.rglob("*") if path.is_file()}


def _forbid_acquisition(monkeypatch, flow=None):
    def forbidden(*_args, **_kwargs):
        pytest.fail("a preparation estimate must not approve, download, or advance Flow")
    for name in ("approve", "download", "approve_inventory", "bind_approved", "advance_approved"):
        monkeypatch.setattr(obs_subset, name, forbidden)
    monkeypatch.setattr(flowgate.FlowSession, "fetch", forbidden)
    if flow is not None:
        monkeypatch.setattr(flow, "move", forbidden)


def _assert_estimate_only(result, status="estimate_available"):
    assert result["kind"] == "prepare_estimate"
    assert result["status"] == status
    assert result["plan_available"] is (status == "estimate_available")
    for key in ("acquisition_approved", "input_ready", "model_ready"):
        assert result[key] is False
    assert not result.get("job_id") and not result.get("receipt")
    assert not result.get("acquisition_id") and not result.get("eligible")
    assert HOST_TOKEN not in json.dumps(result)


def _assert_unchanged(project, before):
    for rel, data in before.items():
        assert (project / rel).read_bytes() == data, rel
    assert flowrun.current_state(project) == "PLANNING"
    assert not (project / "inputs").exists()
    assert not (project / "runs" / "approval.json").exists()
    assert obs_subset.list_states(project) == []


@pytest.mark.parametrize("body,blockers,status", [
    (SHAW_REQUEST, [], "estimate_available"),
    (CRHM_REQUEST, [], "estimate_available"),
    (VIC_REQUEST, ["SOIL_PARAM_COMPLETE.txt is required"], "blocked"),
])
def test_api_estimate_uses_host_token_without_changing_plan_or_acquiring(
        tmp_path, monkeypatch, body, blockers, status):
    ki, project, flow = _planning(tmp_path)
    before = _snapshot(project)
    _forbid_acquisition(monkeypatch, flow)
    _, opener = _client(monkeypatch, _estimate(body, blockers))

    names = {tool["name"] for tool in api.tool_schemas(ki, project_mode=True, flow=flow)}
    assert "estimate_preparation" in names
    assert "run_ki_tool" not in names and "fetch_data" not in names
    result = json.loads(api.execute_tool("estimate_preparation", copy.deepcopy(body),
        ki, _cfg(project), project_mode=True, flow=flow))

    _assert_estimate_only(result, status)
    _assert_unchanged(project, before)
    assert len(opener.requests) == 1
    request, _ = opener.requests[0]
    assert request.get_method() == "POST"
    assert request.full_url.endswith("/prepare/estimate")
    assert json.loads(request.data) == body
    assert request.get_header("Authorization") == "Bearer " + HOST_TOKEN
    assert HOST_TOKEN not in request.full_url
    assert HOST_TOKEN not in "\n".join(
        path.read_text(encoding="utf-8") for path in project.rglob("*.json"))


def test_api_estimate_honors_disabled_database_and_requires_project_scope(tmp_path, monkeypatch):
    ki, project, flow = _planning(tmp_path)
    _, opener = _client(monkeypatch)
    flow.database_access_mode = "off"
    assert "estimate_preparation" not in flow.api_tools()
    names = {tool["name"] for tool in api.tool_schemas(ki, project_mode=True, flow=flow)}
    assert "estimate_preparation" not in names
    with pytest.raises(api.ToolError):
        api.execute_tool("estimate_preparation", SHAW_REQUEST, ki, _cfg(project),
                         project_mode=True, flow=flow)
    with pytest.raises(api.ToolError):
        api.execute_tool("estimate_preparation", SHAW_REQUEST, ki, _cfg(project),
                         project_mode=True, flow=None)
    assert not opener.requests


@pytest.mark.parametrize("with_project", [False, True])
def test_cli_reads_request_without_creating_raw_acquisition(
        tmp_path, monkeypatch, capsys, with_project):
    from kiss_cli import obs_prepare
    _, project, flow = _planning(tmp_path)
    before = _snapshot(project)
    _forbid_acquisition(monkeypatch, flow)
    request_file = tmp_path / "preparation-request.json"
    request_file.write_text(json.dumps(SHAW_REQUEST), encoding="utf-8")
    _, opener = _client(monkeypatch, _estimate(SHAW_REQUEST))
    command = ["obs-prepare-estimate", "--request", str(request_file)]
    if with_project:
        command += ["--project", str(project)]
    assert cli.main(command) == 0
    _assert_estimate_only(json.loads(capsys.readouterr().out))
    _assert_unchanged(project, before)
    assert len(obs_prepare.list_estimates(project)) == int(with_project)
    assert len(opener.requests) == 1


def _handler(monkeypatch, project, route, payload=None, headers=None):
    handler = object.__new__(gui.Handler)
    handler.server = SimpleNamespace(server_port=8877)
    handler.workroot = project.parent / "desktop"
    handler.path = route
    data = json.dumps(payload or {}).encode()
    handler.headers = {
        "Content-Length": str(len(data)), "Content-Type": "application/json",
        "Host": "127.0.0.1:8877", "Origin": "http://127.0.0.1:8877",
        "Sec-Fetch-Site": "same-origin", "Cookie": f"geoforge_csrf_8877={COOKIE}",
    }
    handler.headers.update(headers or {})
    handler.csrf_token = COOKIE
    handler.rfile = io.BytesIO(data)
    responses = []
    handler._json = lambda body, code=200: responses.append((body, code))
    monkeypatch.setattr(sessions, "load", lambda _root, ident:
        {"id": SID, "models": ["M"]} if ident == SID else None)
    monkeypatch.setattr(sessions, "project_path", lambda _root, _session: project)
    monkeypatch.setattr(sessions, "registered_project_for_path", lambda _root, cwd:
        project if Path(cwd).resolve() == project.resolve() else None)
    return handler, responses


def test_gui_estimate_and_list_keep_preparation_separate_from_raw_states(tmp_path, monkeypatch):
    _, project, flow = _planning(tmp_path)
    before = _snapshot(project)
    _forbid_acquisition(monkeypatch, flow)
    _, opener = _client(monkeypatch, _estimate(SHAW_REQUEST), RAW_ESTIMATE)
    handler, replies = _handler(monkeypatch, project,
        f"/api/session/{SID}/preparations/estimate", {"request": SHAW_REQUEST})
    handler.do_POST()
    result, status = replies.pop()
    assert status == 200
    _assert_estimate_only(result)
    handler.path = f"/api/session/{SID}/preparations"
    handler.do_GET()
    listing, status = replies.pop()
    assert status == 200 and len(listing["items"]) == 1
    _assert_estimate_only(listing["items"][0])
    assert len(opener.requests) == 1  # listing is local
    _assert_unchanged(project, before)

    # The unchanged raw path still uses only the original raw request contract.
    raw = obs_subset.estimate(project, RAW_REQUEST)
    assert raw["status"] == "awaiting_approval"
    assert [item["id"] for item in obs_subset.list_states(project)] == [raw["id"]]
    assert len(opener.requests) == 2
    assert opener.requests[1][0].full_url.endswith("/subsets/estimate")
    assert json.loads(opener.requests[1][0].data) == RAW_REQUEST
    assert flowrun.current_state(project) == "PLANNING"


@pytest.mark.parametrize("sid,headers,expected", [
    (SID, {"Cookie": ""}, 403),
    (SID, {"Origin": "https://other.invalid"}, 403),
    ("000000000000", {}, 404),
    ("invalid-session", {}, 404),
])
def test_gui_rejects_unsafe_browser_and_unknown_session_before_remote_call(
        tmp_path, monkeypatch, sid, headers, expected):
    _, project, _ = _planning(tmp_path)
    _, opener = _client(monkeypatch)
    handler, replies = _handler(monkeypatch, project,
        f"/api/session/{sid}/preparations/estimate", {"request": SHAW_REQUEST}, headers)
    handler.do_POST()
    assert replies[-1][1] == expected
    assert not opener.requests


@pytest.mark.parametrize("action", ["jobs", "approve", "download"])
def test_gui_has_no_preparation_job_or_download_action(tmp_path, monkeypatch, action):
    _, project, flow = _planning(tmp_path)
    before = _snapshot(project)
    _forbid_acquisition(monkeypatch, flow)
    _, opener = _client(monkeypatch)
    handler, replies = _handler(monkeypatch, project,
        f"/api/session/{SID}/preparations/{action}", {"request": SHAW_REQUEST})
    handler.do_POST()
    assert replies[-1][1] == 404
    assert not opener.requests
    _assert_unchanged(project, before)


def test_agent_bridge_requires_capability_and_registered_project(tmp_path, monkeypatch):
    _, project, flow = _planning(tmp_path)
    before = _snapshot(project)
    _forbid_acquisition(monkeypatch, flow)
    _, opener = _client(monkeypatch, _estimate(SHAW_REQUEST))
    query = {"prepare_request": json.dumps(SHAW_REQUEST), "cwd": str(project)}
    handler, replies = _handler(monkeypatch, project,
        "/api/agent/obs/catalogue?" + urlencode(query))
    handler.do_GET()
    assert replies.pop()[1] == 401 and not opener.requests

    handler.headers["X-GeoForge-Agent-Token"] = CAPABILITY
    for wrong in ({**query, "cwd": str(tmp_path / "not-a-chat")},
                  {**query, "describe_dataset_id": "cmfd_china_3hr_010"},
                  {**query, "subset_dataset_id": "cmfd_china_3hr_010"}):
        handler.path = "/api/agent/obs/catalogue?" + urlencode(wrong)
        handler.do_GET()
        assert replies.pop()[1] == 400 and not opener.requests

    handler.path = "/api/agent/obs/catalogue?" + urlencode(query)
    handler.do_GET()
    result, status = replies.pop()
    assert status == 200
    _assert_estimate_only(result)
    _assert_unchanged(project, before)
    assert len(opener.requests) == 1
    request = opener.requests[0][0]
    assert request.get_header("Authorization") == "Bearer " + HOST_TOKEN
    assert request.get_header("X-geoforge-agent-token") is None
