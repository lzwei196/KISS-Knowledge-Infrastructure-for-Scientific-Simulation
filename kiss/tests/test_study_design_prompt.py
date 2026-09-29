"""Check the actual intake adapter receives the shared study-question contract.

Transport is a capture fixture: no live provider, credentials or data downloads.
Provider compliance/scientific recommendation quality needs separate acceptance.
"""
from types import SimpleNamespace

import pytest

from kiss_cli import api, flowrun, gui, obs_access, providers, settings
from .test_flowrun import _ki, _project


@pytest.mark.parametrize("want", ["api:deepseek", "cli:kimi"])
@pytest.mark.parametrize("mode", ["off", "direct"])
def test_intake_also_separates_period_and_validation(tmp_path, monkeypatch, want, mode):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry.json"))
    monkeypatch.setattr(settings, "database_access_mode", lambda: mode)
    monkeypatch.setattr(obs_access, "token_state", lambda: "configured")
    monkeypatch.setattr(obs_access, "load_catalogue", lambda: {"ok": True, "datasets": []})
    project = _project(tmp_path)
    ki = _ki(tmp_path, "CropFixture")
    ki.meta = {"reference": "Fixture only"}

    class Catalogue(list):
        models_dir = tmp_path / "kis"

    catalogue = Catalogue([ki])
    pre = flowrun.pre(project, "Simulate local crop growth", [], catalogue, None, None)
    handler = object.__new__(gui.Handler)
    handler.catalog, handler.workroot = catalogue, tmp_path
    handler._status_for = lambda _ki: {"label": "Verified", "can_run": True}
    captured = []

    def capture_api(_provider, _ki, _cfg, system, task, **kwargs):
        captured.append(system)
        yield "Captured intake; no agent ran."

    def capture_cli(_provider, **kwargs):
        captured.append(kwargs["replay_prompt"])

    monkeypatch.setattr(api, "run", capture_api)
    monkeypatch.setattr(handler, "_cli_turn", capture_cli)
    fake_provider = SimpleNamespace(name="kimi")
    monkeypatch.setattr(providers, "available", lambda: [fake_provider])
    monkeypatch.setattr(providers, "get", lambda name: fake_provider)
    monkeypatch.setattr(flowrun, "wrapper_commands", lambda: {
        "obs_search": "geoforge-db", "request_user_action": "geoforge-request"})
    handler._chat_auto(want, "Simulate local crop growth", lambda _: True, project, flow_pre=pre)
    assert len(captured) == 1
    text = captured[0]
    assert text.count("[STUDY DESIGN — ONE DECISION]") == 1
    assert "Ask the simulation period separately from the validation method/source" in text
    assert "Do not infer earliest/latest available years from an example" in text
    assert "Offer GeoForge Database candidates only when the host says access is activated" in text
    assert "Do not fetch data to answer this question" in text
    if mode == "off":
        assert "[GEOFORGE DATABASE: DISABLED]" in text
