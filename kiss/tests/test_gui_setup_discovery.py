"""Bounded host discovery runs once and supplies the same evidence to providers."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from kiss_cli import api, cli, gui, install, install_locations, providers, setup, setup_discovery, setup_jobs
from .test_gui_setup_jobs import ready
from .test_setup_final_runtime import case

AGENT_TASK = setup.agent_task

def report(candidates=(), *, complete=True, state=None):
    state = state or ("complete" if complete else "limited")
    return {"schema_version": 1, "model": "Demo", "candidates": list(candidates),
            "state": state, "complete": state == "complete",
            "reason": "finite scope exhausted" if complete else "entry limit reached",
            "scope": {"recursive": False, "indexed": False, "hints": ["Demo"],
                      "sources": ["exact selected paths", "exact PATH names",
                                  "direct conventional-location entries"]},
            "limits": {"entries": 512, "results": 24, "timeout_seconds": 8},
            "stats": {"entries_checked": 20, "roots_checked": 2,
                      "candidates_found": len(candidates), "elapsed_seconds": 0.1},
            "checked_at": 123.0}


def existing(c):
    install_locations.select_mode(c.workroot, "Demo", "existing")


@pytest.mark.parametrize("kind", ["api", "cli"])
def test_host_report_is_job_bound_and_reaches_provider_once(ready, monkeypatch, kind):
    c = ready
    existing(c)
    candidate = c.workroot / "official-install"
    candidate.mkdir()
    discover = Mock(return_value=report([str(candidate)], complete=False))
    monkeypatch.setattr(setup_discovery, "discover", discover)
    # Restore the real task builder: the common GUI test fixture stubs it.
    monkeypatch.setattr(setup, "agent_task", AGENT_TASK)
    checks = iter([install.Step("preflight", False, "repair needed"),
                   install.Step("preflight", False, "still needs repair")])
    monkeypatch.setattr(install, "run_preflight", lambda *args, **kwargs: next(checks))
    monkeypatch.setattr(setup_discovery, "discover", discover)
    received = []
    def provider(*args, **kwargs):
        received.append(args[4] if kind == "api" else args[1])
        yield "Provider inspected supplied candidates.\n"
    if kind == "api":
        monkeypatch.setattr(api, "run", provider)
        want = "api:deepseek"
    else:
        fake = providers.Provider(name="fixture", binary="fixture", argv=["fixture"],
                                  output="text", label="Fixture CLI")
        monkeypatch.setitem(providers.PROVIDERS, "fixture", fake)
        monkeypatch.setattr(providers, "run", provider)
        want = "cli:fixture"
    c.handler._stream_agent_setup({"model": "Demo", "provider": want, "discover_existing": True})
    discover.assert_called_once()
    job = setup_jobs.status(c.workroot, "Demo")
    saved = json.loads((c.root / ".geoforge/setup-discovery.json").read_text(encoding="utf-8"))
    assert saved["job_id"] == job["id"] and saved["turn_id"] == job["turn_id"]
    assert discover.call_args.kwargs["turn_id"] == job["turn_id"]
    assert discover.call_args.kwargs["root"] == c.root
    assert json.dumps(str(candidate)) in received[0]
    assert "entry limit reached" in received[0]
    assert '"entries_checked": 20' in received[0]
    assert '"roots_checked": 2' in received[0]
    assert "direct conventional-location entries" in received[0]
    assert install_locations.info(c.workroot, "Demo")["discovery_report"] == saved
    assert not c.handler._status_for(c.ki)["can_run"]


@pytest.mark.parametrize("state", ["complete", "limited", "failed", "timeout"])
def test_empty_discovery_pauses_before_agent_and_does_not_prove_absence(ready, monkeypatch, state):
    c = ready
    existing(c)
    evidence = report(complete=state == "complete", state="limited" if state == "timeout" else state)
    if state in {"failed", "timeout"}:
        evidence["reason"] = "Discovery worker did not complete." if state == "failed" else "Discovery time limit reached."
        evidence["stats"] = {"entries_checked": 0, "roots_checked": 0,
                             "candidates_found": 0, "elapsed_seconds": 8.0}
    discovery = Mock(return_value=evidence)
    provider = Mock(side_effect=AssertionError("empty host search must not launch another agent search"))
    monkeypatch.setattr(setup_discovery, "discover", discovery)
    monkeypatch.setattr(api, "run", provider)
    c.handler._stream_agent_setup({"model": "Demo", "provider": "api:deepseek"})
    assert setup_jobs.status(c.workroot, "Demo")["state"] == "waiting_for_user"
    provider.assert_not_called()
    discovery.assert_called_once()
    request = setup.request(c.root)
    assert request["status"] == "waiting"
    assert "does not mean the software is absent" in request["message"]
    assert not c.handler._status_for(c.ki)["can_run"]


@pytest.mark.parametrize("search", [False, True])
@pytest.mark.parametrize("installation_only", [False, True])
def test_resumed_cli_receives_current_path_and_contract(ready, monkeypatch, search, installation_only):
    c = ready
    candidate = c.workroot / "newly selected installation"
    candidate.mkdir()
    install_locations.select_mode(c.workroot, "Demo", "existing",
                                  existing_path=None if search else candidate)
    discovery = Mock(return_value=report([str(candidate)], complete=False))
    monkeypatch.setattr(setup_discovery, "discover", discovery)
    setup.request_user(c.root, {"kind": "choice", "title": "Select a path",
                               "resume_hint": "Use the selected path."})
    setup.resume(c.root)
    setup.remember_cli_session(c.root, "fixture", "existing-session")
    fake = providers.Provider(name="fixture", binary="fixture", argv=["fixture"],
                              resume_argv=["fixture", "{resume}"], output="text", label="Fixture CLI")
    monkeypatch.setitem(providers.PROVIDERS, "fixture", fake)
    received = []
    def provider(*args, **kwargs):
        received.append(args[1])
        assert kwargs["resume"] == "existing-session"
        kwargs["session_out"].update(produced=True, returncode=0, session_id="existing-session")
        yield "Continued fixture session.\n"
    monkeypatch.setattr(providers, "run", provider)
    # This checks the resumed provider payload, not scientific readiness.
    if installation_only:
        monkeypatch.setattr(install, "run_preflight", lambda *args, **kwargs:
                            pytest.fail("installation-only must never run preflight"))
    c.handler._stream_agent_setup({"model": "Demo", "provider": "cli:fixture",
                                   "installation_only": installation_only})
    assert len(received) == 1
    assert str(candidate) in received[0] or json.dumps(str(candidate)) in received[0]
    if search:
        discovery.assert_called_once()
        assert "HOST DISCOVERY EVIDENCE" in received[0] and "entry limit reached" in received[0]
    else:
        discovery.assert_not_called()
    if installation_only:
        assert "finish the setup and run the KI preflight" not in received[0]
        assert "Do not run the KI preflight" in received[0]
        assert "INSTALLATION-ONLY" in received[0]


def test_stop_during_discovery_does_not_launch_provider_or_publish_report(ready, monkeypatch):
    c = ready
    existing(c)
    def discover(*args, **kwargs):
        job = setup_jobs.status(c.workroot, "Demo")
        setup_jobs.stop(c.workroot, "Demo", job["id"])
        raise install.InstallStopped("fixture discovery stopped")
    monkeypatch.setattr(setup_discovery, "discover", discover)
    provider = Mock(side_effect=AssertionError("cancelled discovery must not start an agent"))
    monkeypatch.setattr(api, "run", provider)
    c.handler._stream_agent_setup({"model": "Demo", "provider": "api:deepseek", "discover_existing": True})
    assert setup_jobs.status(c.workroot, "Demo")["state"] == "cancelled"
    assert not (c.root / ".geoforge/setup-discovery.json").exists()
    provider.assert_not_called()


def test_new_installation_does_not_run_discovery(ready, monkeypatch):
    c = ready
    discovery = Mock(side_effect=AssertionError("new installs do not need existing-install searches"))
    monkeypatch.setattr(setup_discovery, "discover", discovery)
    monkeypatch.setattr(api, "run", lambda *args, **kwargs: iter(["install complete\n"]))
    c.handler._stream_agent_setup({"model": "Demo", "provider": "api:deepseek"})
    assert setup_jobs.status(c.workroot, "Demo")["state"] == "completed"
    discovery.assert_not_called()


def test_frozen_worker_dispatch_never_opens_app_or_adopts_shell(tmp_path, monkeypatch):
    from kiss_cli import shellenv
    called = []
    monkeypatch.setattr(shellenv, "adopt", lambda: pytest.fail("worker must inherit prepared environment"))
    monkeypatch.setattr(cli, "cmd_app", lambda args: pytest.fail("worker must not open Desktop"))
    monkeypatch.setattr(setup_discovery, "worker_main", lambda source, target: called.append((source, target)) or 0)
    source, target = tmp_path / "request.json", tmp_path / "result.json"
    assert cli.main(["_setup-discovery-worker", str(source), str(target)]) == 0
    assert called == [(source, target)]
