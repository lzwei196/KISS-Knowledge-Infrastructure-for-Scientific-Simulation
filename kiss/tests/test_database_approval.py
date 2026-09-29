"""Database activation must still hold at the final approval click.

The issued review is real; only remote acquisition is a fixture. No live token,
catalogue, download or user project participates.
"""
import pytest

from kiss_cli import acquire, flowrun, obs_access, obs_subset, settings, setup as setup_flow
from .test_plan_review_lifecycle import review_project, _click, _draft

_REAL_ACQUIRE = acquire.run


@pytest.fixture
def database_review(review_project, monkeypatch):
    monkeypatch.setattr(settings, "database_access_mode", lambda: "direct")
    monkeypatch.setattr(obs_access, "token_state", lambda: "configured")
    return review_project


@pytest.mark.parametrize("loss", ["off", "missing", "revoked"])
def test_activation_lost_after_review_prevents_refresh_signing_and_download(database_review, monkeypatch, loss):
    env = database_review
    card = _draft(env, with_data=True)
    if loss == "off":
        monkeypatch.setattr(settings, "database_access_mode", lambda: "off")
    elif loss == "missing":
        monkeypatch.setattr(obs_access, "token_state", lambda: "missing")
    else:
        env.catalogue.update(ok=False, error={"code": "revoked_token"})
    assert obs_access.effective_mode(settings.database_access_mode()) == "off"
    calls = []
    monkeypatch.setattr(obs_subset, "refresh_inventory", lambda *a, **k: calls.append("estimate") or {})
    monkeypatch.setattr(acquire, "run", _REAL_ACQUIRE)
    monkeypatch.setattr(acquire, "_served", lambda *a, **k: calls.append("download") or {"status": "done"})

    result = _click(env, card)

    assert calls == [], "an old review must not authorize new Database operations"
    assert not (env.project / "runs" / "approval.json").exists()
    assert flowrun.current_state(env.project) == "WAITING_FOR_USER"
    assert "Database" in result.message and "Modify the plan" in result.message
    assert setup_flow.request(env.project)["plan_review"]["data_choices"] == []


def test_activation_lost_during_estimate_refresh_prevents_signing(database_review, monkeypatch):
    env = database_review
    card = _draft(env, with_data=True)
    state = {"mode": "direct"}
    monkeypatch.setattr(settings, "database_access_mode", lambda: state["mode"])

    def refresh(*args, **kwargs):
        state["mode"] = "off"     # settings changed while a remote estimate was outstanding
        return {}

    monkeypatch.setattr(obs_subset, "refresh_inventory", refresh)
    result = _click(env, card)
    assert not (env.project / "runs" / "approval.json").exists()
    assert flowrun.current_state(env.project) == "WAITING_FOR_USER"
    assert "Database" in result.message


def test_reactivation_allows_the_reissued_review_to_be_approved(database_review, monkeypatch):
    env = database_review
    card = _draft(env, with_data=True)
    state = {"mode": "off"}
    monkeypatch.setattr(settings, "database_access_mode", lambda: state["mode"])
    assert _click(env, card).message
    state["mode"] = "direct"
    assert _click(env, setup_flow.request(env.project)).message is None
    assert (env.project / "runs" / "approval.json").exists()


def test_public_source_plan_still_approves_with_database_off(database_review, monkeypatch):
    env = database_review
    card = _draft(env)
    monkeypatch.setattr(settings, "database_access_mode", lambda: "off")
    assert _click(env, card).message is None
    assert (env.project / "runs" / "approval.json").exists()
