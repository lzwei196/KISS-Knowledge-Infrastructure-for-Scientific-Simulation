"""Setup API shares the host final verifier; no native model is run."""
import threading
from types import SimpleNamespace

import pytest

from kiss_cli import api, install, setup, setup_jobs, software_verification
from .test_gui_setup_jobs import ready
from .test_setup_final_runtime import case, saved_status


@pytest.mark.parametrize("requirements_ok", [False, True])
def test_gui_api_ki_pass_uses_real_final_verifier_and_manifest_verdict(ready, monkeypatch, requirements_ok):
    c = ready
    monkeypatch.setattr(software_verification, "requirements", lambda *a, **kw:
        install.Step("manifest-requirements", requirements_ok, "fixture native dependency origin failure"
                     if not requirements_ok else "fixture requirements passed"))
    answers = []
    def provider(_prov, ki, cfg, *_args, **kwargs):
        context = {**kwargs["setup_context"], "_handle": kwargs["handle"]}
        answers.append(api.execute_tool("run_preflight", {}, ki, cfg, setup_mode=True, setup_context=context))
        assert saved_status(c)["ok"] is requirements_ok
        yield "Fixture provider ended.\n"
    monkeypatch.setattr(api, "run", provider)
    c.handler._stream_agent_setup({"model": "Demo", "provider": "api:deepseek"})
    assert len(answers) == 1
    assert answers[0].startswith("PASS\n" if requirements_ok else "FAIL\n"), answers
    assert "Host software verification" in answers[0]
    if not requirements_ok:
        assert "fixture native dependency origin failure" in answers[0]
        assert not saved_status(c)["ok"]
    assert saved_status(c)["ok"] is requirements_ok


def test_setup_missing_callback_cannot_fall_back_to_ki_only_pass(case, monkeypatch):
    monkeypatch.setattr(install, "run_preflight", lambda *a, **kw: pytest.fail("weaker fallback forbidden"))
    with pytest.raises(api.ToolError, match="Host software verification is unavailable"):
        api.execute_tool("run_preflight", {}, case.live, case.cfg, setup_mode=True)


@pytest.mark.parametrize("answer", [True, "PASS", {"ok": True}, install.Step("x", 1, "truthy")])
def test_callback_requires_actual_boolean_host_verdict(case, answer):
    with pytest.raises(api.ToolError, match="no valid verdict"):
        api.execute_tool("run_preflight", {}, case.live, case.cfg, setup_mode=True,
                         setup_context={"verify_software": lambda: answer})


def test_request_cannot_override_host_binding_or_borrow_project_setup_scope(case):
    def forbidden():
        pytest.fail("forbidden callback")
    with pytest.raises(api.ToolError, match="no overrides"):
        api.execute_tool("run_preflight", {"manifest": {"python_deps": []}}, case.live, case.cfg,
                         setup_mode=True, setup_context={"verify_software": forbidden})
    with pytest.raises(api.ToolError, match="installation-only"):
        api.execute_tool("run_preflight", {}, case.live, case.cfg, setup_mode=True,
                         setup_context={"verify_software": forbidden, "installation_only": True})


@pytest.mark.parametrize("when", ["before", "during"])
def test_cancelled_verification_never_returns_pass(case, when):
    stopped = threading.Event()
    if when == "before": stopped.set()
    def callback():
        assert when == "during"
        stopped.set()
        return install.Step("verification", True, "passed before cancellation")
    with pytest.raises(api.ToolError, match="Stopped by the user"):
        api.execute_tool("run_preflight", {}, case.live, case.cfg, setup_mode=True,
            setup_context={"verify_software": callback, "_handle": SimpleNamespace(stopped=stopped)})


def test_exception_is_not_a_pass_and_no_weaker_retry(case, monkeypatch):
    monkeypatch.setattr(install, "run_preflight", lambda *a, **kw: pytest.fail("weaker retry forbidden"))
    def callback():
        raise ValueError("saved projection changed")
    with pytest.raises(api.ToolError, match="did not complete: saved projection changed"):
        api.execute_tool("run_preflight", {}, case.live, case.cfg, setup_mode=True,
                         setup_context={"verify_software": callback})


def test_api_and_cli_guidance_distinguish_full_verification_from_diagnostic(case):
    full = next(row for row in api.tool_schemas(case.live, setup_mode=True) if row["name"] == "run_preflight")
    diagnostic = next(row for row in api.tool_schemas(case.live) if row["name"] == "run_preflight")
    assert "complete software verification" in full["description"]
    assert "does not establish host software readiness" in diagnostic["description"]
    assert full["input_schema"]["additionalProperties"] is False
    guidance = setup.dependency_capability_guidance()
    assert "CLI providers" in guidance and "KI diagnostic only" in guidance
    assert "same complete host verification" in guidance
