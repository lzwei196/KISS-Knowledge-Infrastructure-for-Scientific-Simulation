"""Both CLI-agent helpers forward preparation plans through the host capability."""
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse

import pytest

from kiss_cli import flowrun
from .test_obs_access import json_response


@pytest.mark.parametrize("embedded", [True, False])
def test_prepare_request_uses_loopback_capability_without_database_token(tmp_path, monkeypatch, capsys, embedded):
    source = (flowrun._DATABASE_HELPER if embedded else
              (Path(__file__).parents[1] / "system_kis/GeoForge_Database/tools/search_catalogue.py").read_text(encoding="utf-8"))
    scope = {"__name__": "preparation_helper_test"}
    exec(compile(source, "<preparation-helper>", "exec"), scope)
    request = {"model": "shaw", "source": "cmfd", "mode": "daily", "lat": 47.43,
               "lon": 126.97, "start": "2003-10-01", "end": "2004-05-31"}
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(request), encoding="utf-8-sig")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEOFORGE_AGENT_DATABASE_URL", "http://127.0.0.1:12345/api/agent/obs/catalogue")
    monkeypatch.setenv("GEOFORGE_AGENT_DATABASE_TOKEN", "synthetic-loopback-capability")
    monkeypatch.setattr(sys, "argv", ["geoforge-db", "--prepare-request", str(request_file)])
    seen = []
    def open_request(req, timeout):
        seen.append(req)
        query = parse_qs(urlparse(req.full_url).query)
        assert json.loads(query["prepare_request"][0]) == request
        assert Path(query["cwd"][0]) == tmp_path
        assert req.get_header("X-geoforge-agent-token") == "synthetic-loopback-capability"
        assert req.get_header("Authorization") is None
        assert req.get_method() == "GET"
        return json_response({"kind": "prepare_estimate", "input_ready": False})
    monkeypatch.setattr("urllib.request.urlopen", open_request)
    assert scope["main"]() == 0
    assert json.loads(capsys.readouterr().out) == {"kind": "prepare_estimate", "input_ready": False}
    assert len(seen) == 1
    assert list(tmp_path.iterdir()) == [request_file]


@pytest.mark.parametrize("embedded", [True, False])
def test_oversized_request_is_refused_before_transport(tmp_path, monkeypatch, capsys, embedded):
    source = (flowrun._DATABASE_HELPER if embedded else
              (Path(__file__).parents[1] / "system_kis/GeoForge_Database/tools/search_catalogue.py").read_text(encoding="utf-8"))
    scope = {"__name__": "preparation_helper_test"}
    exec(compile(source, "<preparation-helper>", "exec"), scope)
    request_file = tmp_path / "request.json"
    request_file.write_text(" " * (60 * 1024 + 1), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["geoforge-db", "--prepare-request", str(request_file)])
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("must not contact host"))
    assert scope["main"]() == 2
    assert "too large" in capsys.readouterr().err
