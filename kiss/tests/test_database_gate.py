"""DB gating: GeoForge Database records reach an agent or a card only while the Database is
activated (mode not off, a token, and the server not rejecting it). Reproduced 2026-09-28: with
access off, the plan still stamped catalogue inputs and the card offered cached Database records.
"""
from __future__ import annotations

import pytest

from kiss_cli import obs_access


@pytest.fixture
def db(monkeypatch):
    state = {"token": "configured", "store": {"ok": True, "datasets": [{"id": "a"}]}}
    monkeypatch.setattr(obs_access, "token_state", lambda: state["token"])
    monkeypatch.setattr(obs_access, "load_catalogue", lambda *a, **k: state["store"])
    return state


def test_off_stays_off(db):
    assert obs_access.effective_mode("off") == "off"


@pytest.mark.parametrize("mode", ["direct", "snapshot"])
def test_an_activated_database_keeps_the_setting(db, mode):
    assert obs_access.effective_mode(mode) == mode


@pytest.mark.parametrize("token", ["missing", "error"])
def test_no_usable_token_means_off(db, token):
    db["token"] = token
    assert obs_access.effective_mode("direct") == "off"


@pytest.mark.parametrize("code", ["missing_token", "invalid_token", "expired_token", "revoked_token"])
def test_a_server_rejection_means_off_even_with_an_old_cache(db, code):
    db["store"] = {"ok": False, "datasets": [{"id": "a"}], "error": {"code": code}}
    assert obs_access.effective_mode("direct") == "off"


def test_token_not_read_yet_follows_the_cached_catalogue_like_settings_does(db):
    db["token"] = "unknown"
    assert obs_access.effective_mode("direct") == "direct"
    db["store"] = {}
    assert obs_access.effective_mode("direct") == "off"


def test_an_outage_does_not_switch_the_database_off(db):
    db["store"] = {"ok": True, "stale": True, "datasets": [{"id": "a"}], "error": {"code": "network"}}
    assert obs_access.effective_mode("direct") == "direct"


def test_every_chat_turn_uses_the_effective_mode():
    import inspect
    from kiss_cli import gui
    src = inspect.getsource(gui)
    assert src.count("database_mode = obs_access.effective_mode(settings.database_access_mode())") == 2
    assert "database_mode = settings.database_access_mode()" not in src


@pytest.mark.parametrize("code", ["invalid_token", "expired_token", "revoked_token"])
def test_status_separates_saved_token_from_rejected_database_access(db, monkeypatch, code):
    from kiss_cli import gui, settings
    db["store"] = {"ok": False, "datasets": [{"id": "cached"}],
                   "error": {"code": code, "message": "The token was rejected."}}
    monkeypatch.setattr(settings, "database_access_mode", lambda: "direct")
    monkeypatch.setattr(obs_access, "token", lambda: pytest.fail("status must never read credentials"))
    result = gui._database_status()
    assert result["configured"] is True and result["token_state"] == "configured"
    assert result["mode"] == "direct" and result["effective_mode"] == "off"
    assert result["records"] == 1 and "rejected" in result["error"]


@pytest.mark.parametrize("mode,token,store,effective,configured", [
    ("off", "configured", {"ok": True}, "off", True),
    ("direct", "missing", {"ok": True}, "off", False),
    ("snapshot", "configured", {"ok": True, "stale": True, "error": {"code": "network"}}, "snapshot", True),
])
def test_status_preserves_disabled_missing_token_and_offline_states(
        db, monkeypatch, mode, token, store, effective, configured):
    from kiss_cli import gui, settings
    db["token"], db["store"] = token, store
    monkeypatch.setattr(settings, "database_access_mode", lambda: mode)
    result = gui._database_status()
    assert result["mode"] == mode and result["effective_mode"] == effective
    assert result["configured"] is configured
