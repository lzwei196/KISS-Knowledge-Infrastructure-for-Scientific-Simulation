"""Capture actual provider launch composition, then probe local CLI parsing only.

No Codex model call, authentication change, or user configuration write occurs.
"""
from dataclasses import replace
import io
import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from kiss_cli import flowgate, policy, providers


def capture(tmp_path, monkeypatch, *, state=None, resume=False, danger=False,
            network=False, template_flags=()):
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    source = tmp_path / "approved-ki"
    source.mkdir(exist_ok=True)
    provider = replace(providers.PROVIDERS["codex"])
    provider.argv = [*provider.argv, *template_flags]
    provider.resume_argv = [*provider.resume_argv, *template_flags]
    flow = flowgate.load()
    fp = (flow.policy.for_state(flow.states.State(state), "codex", project,
                                {"Demo": source}) if state else None)
    pol = policy.Policy("Demo", posture=(policy.Posture.DANGER_FULL_ACCESS if danger
                                       else policy.Posture.WORKSPACE_WRITE))
    pol.add("read", source, "existing effective KI grant")
    if network:
        pol.add("network", "example.test", "approved network fixture")
    launches = []
    with monkeypatch.context() as patch:
        patch.setattr(provider, "health", lambda: providers.ProviderHealth(True, True, "fixture"))
        patch.setattr(provider, "path", lambda: "codex")
        patch.setattr(providers, "_launcher", lambda binary: [binary])
        def spawn(argv, **kwargs):
            launches.append(argv)
            return SimpleNamespace(stdout=io.StringIO(""), stdin=None,
                                   wait=lambda **_: 0, poll=lambda: 0)
        patch.setattr(providers.subprocess, "Popen", spawn)
        list(providers.run(provider, "fixture only", project, pol=pol, flow_policy=fp,
                           extra_dirs=[str(source), str(source), str(project)],
                           resume="00000000-0000-0000-0000-000000000000" if resume else None))
    assert len(launches) == 1
    return launches[0], source


@pytest.mark.parametrize("state", [item.value for item in flowgate.load().states.State])
@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("danger", [False, True])
def test_flow_owns_one_sandbox_for_every_phase(tmp_path, monkeypatch, state, resume, danger):
    argv, source = capture(tmp_path, monkeypatch, state=state, resume=resume, danger=danger)
    expected = "workspace-write" if state in {"PLANNING", "REPLAN_REQUIRED", "EXECUTING"} else "read-only"
    assert argv.count("--sandbox") == 1
    assert argv[argv.index("--sandbox") + 1] == expected
    assert "danger-full-access" not in argv
    assert "--dangerously-bypass-approvals-and-sandbox" not in argv
    if state in {"PLANNING", "REPLAN_REQUIRED"}:
        assert "--add-dir" not in argv
    else:
        assert argv.count("--add-dir") == 1
        assert argv[argv.index("--add-dir") + 1] == str(source.resolve())
    if resume:
        assert argv.index("--sandbox") < argv.index("resume")
        if "--add-dir" in argv:
            assert argv.index("--add-dir") < argv.index("resume")


@pytest.mark.parametrize("flags", [("--sandbox", "danger-full-access"),
    ("--sandbox=danger-full-access",), ("-s", "danger-full-access"), ("-s=danger-full-access",),
    ("-sdanger-full-access",)])
@pytest.mark.parametrize("resume", [False, True])
def test_flow_replaces_template_sandbox_aliases_and_keeps_network_config(tmp_path, monkeypatch, flags, resume):
    argv, _ = capture(tmp_path, monkeypatch, state="RESOLVING_KIS", network=True, template_flags=flags, resume=resume)
    assert argv.count("--sandbox") == 1 and argv[argv.index("--sandbox") + 1] == "read-only"
    assert not any("danger-full-access" in part for part in argv)
    assert "sandbox_workspace_write.network_access=true" in argv


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("danger", [False, True])
def test_no_flow_keeps_existing_native_policy_and_authorized_roots(tmp_path, monkeypatch, resume, danger):
    argv, source = capture(tmp_path, monkeypatch, resume=resume, danger=danger)
    assert argv.count("--sandbox") == 1
    assert argv[argv.index("--sandbox") + 1] == ("danger-full-access" if danger else "workspace-write")
    assert argv[argv.index("--add-dir") + 1] == str(source.resolve())


@pytest.mark.parametrize("state", ["RESOLVING_KIS", "PLANNING", "EXECUTING"])
@pytest.mark.parametrize("resume", [False, True])
def test_installed_cli_accepts_composed_syntax_without_invoking_provider(tmp_path, monkeypatch, state, resume):
    executable = shutil.which("codex")
    if not executable:
        pytest.skip("Installed CLI parser check; provider capture tests remain required")
    argv, _ = capture(tmp_path, monkeypatch, state=state, resume=resume, network=True)
    # --help parses the exact launch flags but never loads a session or calls a model.
    result = subprocess.run([executable, *argv[1:], "--help"], cwd=tmp_path,
        capture_output=True, text=True, encoding="utf-8", timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert result.returncode == 0, result.stderr
    assert "Usage:" in result.stdout
