"""Latest host diagnostics do not replay recovered installation failures."""
from __future__ import annotations

import hashlib
import json

import pytest

from kiss_cli import api, gui, install, providers, setup, setup_jobs, setup_status
from .test_gui_setup_jobs import ready
from .test_setup_final_runtime import case, finish, install_spies, saved_status


REAL_TASK = setup.agent_task


def old_build(case, *, passed=True):
    document = {"model": "Demo", "ok": passed, "checked_at": 123,
                "verified_at": 123 if passed else None,
                "primary_error": None if passed else {"name": "acquire[build]", "detail": "old compiler error"},
                "steps": [{"name": "acquire[build]", "ok": False, "recovered": passed,
                           "detail": "old compiler error", "commands": ["old build"],
                           "evidence": {"source_checkout": {"commit": "source bytes preserved"}}},
                          {"name": "preflight", "ok": passed, "detail": "old final check"}]}
    (case.root / "status.json").write_text(json.dumps(document), encoding="utf-8")
    return document


def history(case):
    result = []
    for entry in saved_status(case)["history"]:
        raw = (case.root / entry["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
        archived = json.loads(raw)
        assert archived["scope"] == entry["scope"] == "historical_only"
        result.append(archived["status"])
    return result


def test_final_pass_keeps_source_evidence_in_history_not_active_failed_rows(case, monkeypatch):
    prior = old_build(case)
    install_spies(monkeypatch)
    assert finish(case)
    current = saved_status(case)
    assert current["ok"] and current["primary_error"] is None
    assert [row["name"] for row in current["steps"]] == ["manifest-requirements", "preflight"]
    assert all(row["ok"] for row in current["steps"])
    assert history(case) == [prior]
    prompt = setup_status.guidance(case.root)
    assert "old compiler error" not in prompt
    assert "historical evidence, not current blockers or current readiness" in prompt


@pytest.mark.parametrize("kind", ["api", "cli"])
def test_failed_initial_check_is_published_before_provider_and_recovery_is_fresh(ready, monkeypatch, kind):
    c = ready
    prior = old_build(c)
    tasks = []
    def task(*args, **kwargs):
        text = REAL_TASK(*args, **kwargs)
        tasks.append(text)
        return text
    monkeypatch.setattr(setup, "agent_task", task)
    observed = []
    def provider(*args, **kwargs):
        current = saved_status(c)
        assert current["primary_error"] == {"name": "preflight", "detail": "repair needed"}
        assert current["steps"][0]["detail"] == "repair needed"
        assert not current["ok"] and current["verified_at"] is None
        assert "old compiler error" not in tasks[-1]
        assert "CURRENT HOST SETUP STATUS" in tasks[-1]
        observed.append(current)
        yield "Fixture provider completed.\n"
    if kind == "api":
        monkeypatch.setattr(api, "run", provider)
        want = "api:deepseek"
    else:
        fake = providers.Provider(name="fixture", binary="fixture", argv=["fixture"], output="text", label="Fixture CLI")
        monkeypatch.setitem(providers.PROVIDERS, "fixture", fake)
        monkeypatch.setattr(providers, "run", provider)
        want = "cli:fixture"
    c.handler._stream_agent_setup({"model": "Demo", "provider": want})
    assert observed
    assert setup_jobs.status(c.workroot, "Demo")["state"] == "completed"
    assert saved_status(c)["ok"]
    assert all(row["ok"] for row in saved_status(c)["steps"])
    assert prior in history(c)
    assert any(row.get("primary_error", {}).get("detail") == "repair needed" for row in history(c)
               if isinstance(row.get("primary_error"), dict))


def test_passed_script_but_failed_host_projection_is_the_actual_provider_blocker(ready, monkeypatch):
    c = ready
    prior = old_build(c)
    monkeypatch.setattr(install, "run_preflight", lambda *a, **k: install.Step("preflight", True, "script passes"))
    monkeypatch.setattr(gui, "_setup_projection_check", lambda *a, **k:
                        install.Step("runtime-projection", False, "current source identity changed"))
    tasks = []
    monkeypatch.setattr(setup, "agent_task", lambda *a, **k: tasks.append(REAL_TASK(*a, **k)) or tasks[-1])
    def provider(*args, **kwargs):
        current = saved_status(c)
        assert current["primary_error"]["name"] == "runtime-projection"
        assert "current source identity changed" in tasks[-1]
        assert "old compiler error" not in tasks[-1]
        yield "Current projection remains blocked.\n"
    monkeypatch.setattr(api, "run", provider)
    c.handler._stream_agent_setup({"model": "Demo", "provider": "api:deepseek"})
    assert tasks and not saved_status(c)["ok"]
    assert saved_status(c)["primary_error"]["detail"] == "current source identity changed"
    assert setup_jobs.status(c.workroot, "Demo")["state"] == "failed"
    assert prior in history(c)


def test_cancelled_next_attempt_cannot_promote_historical_pass(case):
    prior = old_build(case)
    job = setup_jobs.start(case.workroot, "Demo", case.root, "fixture")
    started = saved_status(case)
    assert not started["ok"] and started["verified_at"] is None and started["steps"] == []
    job.finish("cancelled", "user stopped")
    assert not saved_status(case)["ok"] and saved_status(case)["verified_at"] is None
    assert saved_status(case)["primary_error"]["detail"] == "user stopped"
    assert history(case) == [prior]
    assert "old compiler error" not in setup.resume_task({}, case.root)


def test_error_before_initial_check_does_not_replay_old_acquisition_failure(ready, monkeypatch):
    c = ready
    prior = old_build(c, passed=False)
    def fail(*args, **kwargs):
        raise ValueError("current preparation refused")
    monkeypatch.setattr(setup, "prepare", fail)
    monkeypatch.setattr(api, "run", lambda *a, **k: pytest.fail("provider must not launch"))
    c.handler._stream_agent_setup({"model": "Demo", "provider": "api:deepseek"})
    current = saved_status(c)
    assert not current["ok"] and current["steps"] == []
    assert "current preparation refused" in current["primary_error"]["detail"]
    assert "old compiler error" not in setup_status.guidance(c.root)
    assert history(c) == [prior]


def test_resume_guidance_uses_current_error_only(case):
    old_build(case)
    setup_status.precheck(case.root, model="Demo", check=install.Step("runtime-projection", False, "fresh blocker"))
    text = setup.resume_task({"resume_hint": "previous conversation"}, case.root)
    assert "CURRENT HOST SETUP STATUS" in text and "fresh blocker" in text
    assert "old compiler error" not in text
    assert "do not edit status records or restore an old PASS" in text


def test_host_exception_replaces_pending_verification_without_reviving_history(ready, monkeypatch):
    c = ready
    prior = old_build(c)
    monkeypatch.setattr(install, "run_preflight", lambda *a, **k: install.Step("preflight", True, "script passes"))
    def fail(*args, **kwargs):
        raise RuntimeError("current host verification failed unexpectedly")
    monkeypatch.setattr(gui, "_setup_projection_check", fail)
    monkeypatch.setattr(api, "run", lambda *a, **k: pytest.fail("provider must not launch"))
    c.handler._stream_agent_setup({"model": "Demo", "provider": "api:deepseek"})
    current = saved_status(c)
    assert not current["ok"] and current["primary_error"]["name"] == "setup-job"
    assert "current host verification failed unexpectedly" in current["primary_error"]["detail"]
    assert current["steps"] == [] and history(c) == [prior]
