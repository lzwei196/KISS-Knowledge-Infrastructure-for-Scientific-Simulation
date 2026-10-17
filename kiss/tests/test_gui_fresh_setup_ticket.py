"""Fresh-runtime authority exists only around the host-owned setup attempt."""
import pytest

from kiss_cli import api, gui, providers, setup, setup_jobs, setup_runtime
from .test_gui_setup_jobs import ready
from .test_setup_final_runtime import case


@pytest.mark.parametrize("kind", ["api", "cli"])
def test_ticket_surrounds_prepare_provider_and_final_check(ready, monkeypatch, kind):
    c, order, ticket = ready, [], object()
    original_prepare = setup.prepare
    original_final = c.handler._record_agent_preflight
    monkeypatch.setattr(setup_runtime, "begin", lambda root, **kw:
                        order.append(("begin", root, kw["allowed"])) or ticket)
    monkeypatch.setattr(setup_runtime, "capture", lambda value, *args, **kw:
                        order.append(("capture", value)))
    monkeypatch.setattr(setup_runtime, "refresh", lambda value, *args, **kw:
                        order.append(("refresh", value)))
    monkeypatch.setattr(setup_runtime, "close", lambda value: order.append(("close", value)))

    def prepare(*args, **kwargs):
        order.append(("prepare",))
        return original_prepare(*args, **kwargs)

    def final(*args, **kwargs):
        order.append(("final",))
        return original_final(*args, **kwargs)

    def provider(*args, **kwargs):
        order.append(("provider",))
        if kind == "api":
            kwargs["setup_context"]["run_builtin"]()
        yield "Fixture provider complete.\n"

    monkeypatch.setattr(setup, "prepare", prepare)
    monkeypatch.setattr(gui, "run_install", lambda *args, **kwargs: order.append(("builtin",)))
    c.handler._record_agent_preflight = final
    if kind == "api":
        monkeypatch.setattr(api, "run", provider)
        want = "api:deepseek"
    else:
        fake = providers.Provider(name="fixture", binary="fixture", argv=["fixture"],
                                  output="text", label="Fixture CLI")
        monkeypatch.setitem(providers.PROVIDERS, "fixture", fake)
        monkeypatch.setattr(providers, "run", provider)
        want = "cli:fixture"
    c.handler._stream_agent_setup({"model": "Demo", "provider": want})
    expected = ["begin", "prepare", "capture", "provider"]
    if kind == "api":
        expected += ["refresh", "builtin"]
    assert [row[0] for row in order] == expected + ["refresh", "final", "close"]
    assert order[0] == ("begin", c.root, True)
    assert all(row[1] is ticket for row in order if row[0] in {"capture", "refresh", "close"})
    assert setup_jobs.status(c.workroot, "Demo")["state"] == "completed"


@pytest.mark.parametrize("failure", ["prepare", "provider", "cancel"])
def test_ticket_is_closed_after_failure_or_stop(ready, monkeypatch, failure):
    c, calls, ticket = ready, [], object()
    monkeypatch.setattr(setup_runtime, "begin", lambda *args, **kw: ticket)
    monkeypatch.setattr(setup_runtime, "capture", lambda *args, **kw: calls.append("capture"))
    monkeypatch.setattr(setup_runtime, "refresh", lambda *args, **kw: calls.append("refresh"))
    monkeypatch.setattr(setup_runtime, "close", lambda value: calls.append(("close", value)))
    if failure == "prepare":
        monkeypatch.setattr(setup, "prepare", lambda *args, **kw:
                            (_ for _ in ()).throw(ValueError("Fixture preparation failure")))

    def provider(*args, **kwargs):
        calls.append("provider")
        if failure == "provider":
            raise ValueError("Fixture provider failure")
        kwargs["handle"].stopped.set()
        yield "Fixture provider stopped.\n"

    monkeypatch.setattr(api, "run", provider)
    c.handler._stream_agent_setup({"model": "Demo", "provider": "api:deepseek"})
    assert calls[-1] == ("close", ticket)
    assert "refresh" not in calls
    if failure == "prepare":
        assert "capture" not in calls and "provider" not in calls
    assert setup_jobs.status(c.workroot, "Demo")["state"] in {"failed", "cancelled"}
