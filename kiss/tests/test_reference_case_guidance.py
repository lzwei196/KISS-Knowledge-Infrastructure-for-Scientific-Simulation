"""Reference discovery reaches the real planning prompt without granting a run.

Only provider transport is captured; GUI materialisation, prompt composition and
Flow planning use their normal code. These are not model execution tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from kiss_cli import api, flowrun, gui, paths, prompt, settings
from kiss_cli.catalog import KI
from .test_flowrun import _ki, _project


def _case(root, name, docs=("README.md", "manifest.json", "expected.json")):
    case = root / "test_cases" / name
    case.mkdir(parents=True)
    for name in docs:
        (case / name).write_bytes(b"Supplied case fixture; preserve KISSPATH_STATIC.\r\n")
    return case


@pytest.mark.parametrize("shape", ["absent", "empty", "unrelated"])
def test_no_case_pointers_without_recognized_case_documents(tmp_path, shape):
    if shape == "empty":
        (tmp_path / "test_cases").mkdir()
    elif shape == "unrelated":
        _case(tmp_path, "not-a-described-case", docs=("unrelated.txt",))
        (tmp_path / "test_cases" / "README.md").write_text("Top-level overview")
    assert prompt._reference_case_guidance(tmp_path) == ""


def test_all_cases_are_discovered_without_selecting_one_or_reading_contents(tmp_path):
    _case(tmp_path, "zeta", docs=("README.md",))
    _case(tmp_path, "alpha")
    _case(tmp_path, "no-documents", docs=("run_reference.py",))
    text = prompt._reference_case_guidance(tmp_path)
    case_lines = [line.strip() for line in text.splitlines() if line.startswith("  ")]
    assert case_lines == [
        "test_cases/alpha/README.md, test_cases/alpha/manifest.json, test_cases/alpha/expected.json",
        "test_cases/zeta/README.md",
    ]
    assert "Supplied case fixture" not in text
    assert "no-documents" not in text
    assert "this list grants no execution permission" in text


@pytest.mark.parametrize("escape", ["case_root", "case_directory", "document"])
def test_discovery_does_not_advertise_symlinks_outside_selected_ki(tmp_path, escape):
    root = tmp_path / "ki"
    root.mkdir()
    outside = tmp_path / "outside"
    case = _case(outside, "external-case", docs=("README.md",))
    try:
        if escape == "case_root":
            (root / "test_cases").symlink_to(outside / "test_cases", target_is_directory=True)
        elif escape == "case_directory":
            (root / "test_cases").mkdir()
            (root / "test_cases" / "external-case").symlink_to(case, target_is_directory=True)
        else:
            local = root / "test_cases" / "external-case"
            local.mkdir(parents=True)
            (local / "README.md").symlink_to(case / "README.md")
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"This host does not permit creating test symlinks: {error}")
    assert prompt._reference_case_guidance(root) == ""


@pytest.mark.parametrize("execute", [False, True])
def test_compose_preserves_shared_contract_alongside_case_pointers(tmp_path, execute):
    source = _ki(tmp_path, "Fixture")
    ki = KI(source.name, source.root)
    _case(ki.root, "supplied-case")
    text = prompt.compose(ki, headless=False, execute=execute, strict=True)
    assert text.count("[SHIPPED REFERENCE CASES]") == 1
    assert "test_cases/supplied-case/manifest.json" in text
    assert "test_cases/supplied-case/expected.json" in text
    assert "[KI HARNESS v1]" in text
    assert ("TOOLS (validated)" if execute else "INSPECT mode") in text
    assert "this list grants no execution permission" in text
    assert "Do not substitute an example for a requested new-site study" in text


@pytest.mark.parametrize("names", [("FixtureA",), ("FixtureA", "FixtureB")])
def test_gui_planning_gets_source_mapping_and_each_materialised_case(tmp_path, monkeypatch, names):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry.json"))
    monkeypatch.setattr(settings, "database_access_mode", lambda: "off")
    monkeypatch.setattr(gui.install, "runtime_python", lambda *args: sys.executable)
    project = _project(tmp_path)
    models = []
    configs = {}
    for name in names:
        source = _ki(tmp_path, name)
        model = KI(name, source.root)
        _case(model.root, f"{name.lower()}-replay")
        models.append(model)
        cfg = paths.KissConfig.default(tmp_path / "installed" / name)
        cfg.python = sys.executable
        configs[name] = cfg

    class Catalogue(list):
        models_dir = tmp_path / "kis"

        def get(self, name):
            return next(item for item in self if item.name == name)

    catalogue = Catalogue(models)
    task = "Run the shipped reference cases from " + ", ".join(str(model.root) for model in models)
    pre = flowrun.pre(project, task, list(names), catalogue, None, None)
    handler = object.__new__(gui.Handler)
    handler.catalog, handler.workroot, handler.repo_root = catalogue, tmp_path, None
    handler._config = lambda model: configs[model.name]
    handler._workdir = lambda model: configs[model.name].root
    handler._status_for = lambda model: {"label": "Verified", "can_run": True}
    handler._software_status_prompt = lambda *args: "Fixture installation verified."
    captured = []

    def capture(_provider, _ki, cfg, system, request, **kwargs):
        captured.append((system, kwargs))
        yield "Captured planning prompt only."

    monkeypatch.setattr(api, "run", capture)
    turn = handler._chat_with_models(
        list(names), "api:deepseek", task, lambda piece: True, project,
        bare_task=task, flow_pre=pre,
    )
    assert len(captured) == 1
    system, kwargs = captured[0]
    assert turn.kind == "planning" and not turn.execute
    assert kwargs["flow"] is not None
    assert flowrun.current_state(project) == "PLANNING"
    assert "[PLANNING PROJECT]" in system
    assert "[EXISTING CASE REPLAY]" in system
    assert "Planning still cannot execute" in system
    assert "submit the bounded plan through normal approval" in system
    assert "different path or revision" in system
    assert "inspect and reconcile it" in system
    assert "Use the project working KIs for instructions, file reads and tool execution" in system
    assert "active library source is not proof of the project's revision" in system
    assert "Do not silently copy newer tools or guidance into that retained pair" in system
    assert system.count("[SHIPPED REFERENCE CASES]") == len(models)
    for model in models:
        working = project / "models" / model.name / "ki"
        assert f"active library source {model.root}; project working KI {working}" in system
        relative = Path("test_cases") / f"{model.name.lower()}-replay" / "README.md"
        assert relative.as_posix() in system
        assert (working / relative).read_bytes() == (model.root / relative).read_bytes()
