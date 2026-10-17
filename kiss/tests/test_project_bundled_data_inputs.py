"""Immutable selected-KI example files use the same review and worker contract."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from kiss_cli import ki_adaptations, ki_guard, paths, project_data_tools, project_paths
from kiss_cli.manifest import Manifest
from ki_tools_common.flow import plan as planning, project_inputs
from .test_project_data_tools import case, approve, run


SOURCE = '''from pathlib import Path
import csv,json
raw=Path('models/M/ki/outputs/example/weather.csv')
rows=list(csv.DictReader(raw.open()))
out=Path('outputs/inspection.json');out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps({'rows':rows,'count':len(rows)}))
'''


@pytest.fixture
def bundled(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_ADAPTATION_HOME", str(tmp_path / "adaptation-authority"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry"))
    c = list(case(tmp_path, SOURCE))
    source = tmp_path / "library/models/M"
    data = source / "outputs/example/weather.csv"
    data.parent.mkdir(parents=True)
    data.write_text("date,value\n2020-01-01,2\n2020-01-02,3\n", encoding="utf-8")
    (source / "SKILL.md").write_text("# M\nUse outputs/example for this shipped case.\n")
    ki_guard.enroll(source)
    project = c[1]
    installed = paths.KissConfig.default(tmp_path / "installed")
    installed.python, installed.relocation = sys.executable, "none"
    cfg = project_paths.model_config(project, "M", installed)
    live = project / "models/M/ki"
    report = ki_adaptations.materialise(source, live, cfg, model="M", manifest=Manifest(model="M"))
    assert not report.unresolved and not report.corrupted
    (live.parent / "kiss.toml").write_text(cfg.dumps(), encoding="utf-8")
    c[0] = SimpleNamespace(name="M", root=live)
    c[2].ki_roots["M"] = live
    c[3]["steps"][0]["project_data_tool"]["arguments"] = []
    c[4]["items"][0]["local_paths"] = ["models/M/ki/outputs/example/weather.csv"]
    return c


def review(c, **kwargs):
    return planning.validate(c[3], c[4], ["M"], {"M": c[0].root},
        for_review=True, project=c[1], ki_data_authority=project_data_tools.require_ki_data_source, **kwargs)


def request(c):
    return project_data_tools.worker_request(c[1], Path(c[5]["tool"]), c[3]["steps"][0], c[4], [],
                                            selected_ki_root=c[0].root)


def test_signed_example_outside_test_cases_reviews_and_runs_as_exact_data(bundled):
    c = bundled
    assert review(c) == []
    grant = request(c)
    expected = str(c[0].root / "outputs/example/weather.csv")
    assert grant["read_roots"] == [expected]
    assert grant["list_roots"] == []
    assert grant["non_executable_roots"] == [str(c[0].root)]
    before = Path(expected).read_bytes()
    approve(c)
    assert run(c).startswith("exit_code=0")
    assert json.loads((c[1] / "outputs/inspection.json").read_text())["count"] == 2
    assert Path(expected).read_bytes() == before


@pytest.mark.parametrize("relative", ["models/M/ki", "models/M/ki/outputs",
    "models/M/ki/outputs/example", "models/OTHER/ki/outputs/example/weather.csv",
    "models/M/ki/outputs/example/../example/weather.csv"])
def test_unsupported_sources_fail_during_review_and_execution(bundled, relative):
    c = bundled
    c[4]["items"][0]["local_paths"] = [relative]
    assert review(c)
    with pytest.raises((ValueError, OSError)):
        request(c)


@pytest.mark.parametrize("mode", ["changed", "missing_projection", "changed_projection", "runtime_changed", "old_root"])
def test_new_allowance_requires_current_authentic_project_projection(bundled, mode, tmp_path):
    c = bundled
    if mode == "changed":
        (c[0].root / "outputs/example/weather.csv").write_text("changed data")
    elif mode == "missing_projection":
        ki_adaptations._location(c[0].root).unlink()
    elif mode == "changed_projection":
        ki_adaptations._location(c[0].root).write_text('{}')
    elif mode == "runtime_changed":
        config = project_paths.load_model_config(c[1], "M")
        config.python = str(tmp_path / "different-python")
        (c[0].root.parent / "kiss.toml").write_text(config.dumps())
    else:
        c[0].root = tmp_path / "old-project/models/M/ki"
    assert review(c)
    with pytest.raises((ValueError, OSError)):
        request(c)


@pytest.mark.parametrize("name,content", [("runner.py", b"print(1)"), ("runner.bin", b"MZfake"),
    ("runner.txt", b"#!/usr/bin/python\nprint(1)"), ("runner.data", b"\x7fELFfake")])
def test_non_executable_file_check_is_shared_and_precedes_authority(tmp_path, name, content):
    project = tmp_path / "project"
    root = project / "models/M/ki"
    file = root / "outputs/example" / name
    file.parent.mkdir(parents=True)
    file.write_bytes(content)
    calls = []
    with pytest.raises(ValueError, match="executable"):
        project_inputs.grant(project, "M", file, selected_ki_root=root,
                             authority=lambda *a: calls.append(a))
    assert calls == []


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory_link"])
def test_aliases_cannot_grant_bundled_data(tmp_path, kind):
    project = tmp_path / "project"
    root = project / "models/M/ki"
    target = root / "outputs/example/data.csv"
    target.parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "data.csv").write_text("value\n3\n")
    try:
        if kind == "hardlink":
            target.hardlink_to(outside / "data.csv")
        elif kind == "symlink":
            target.symlink_to(outside / "data.csv")
        else:
            target.parent.rmdir()
            target.parent.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("host cannot create fixture filesystem alias")
    with pytest.raises((ValueError, OSError)):
        project_inputs.grant(project, "M", target, selected_ki_root=root, authority=lambda *a: None)


def test_future_project_data_can_be_reviewed_but_runtime_requires_it(bundled):
    c = bundled
    c[4]["items"][0].update(status="missing", local_paths=["inputs/future.csv"])
    assert not any("project data input" in error for error in review(c))
    with pytest.raises(ValueError, match="does not exist"):
        request(c)


@pytest.mark.parametrize("input_ids", [[], None, [""]])
def test_zero_input_project_data_tools_fail_review_and_worker_with_repair_feedback(bundled, input_ids):
    c = bundled
    c[3]["steps"][0]["inputs"] = input_ids
    errors = review(c)
    feedback = next(error for error in errors if "zero-input project data tools" in error)
    assert "inventory" in feedback and "step.inputs" in feedback
    with pytest.raises(ValueError, match="zero-input project data tools"):
        request(c)


def test_declared_acquisition_input_can_receive_its_local_path_before_execution(bundled):
    c = bundled
    c[4]["items"][0].update(status="missing", local_paths=[])
    assert project_inputs.review_errors(c[3], c[4], c[1], {"M": c[0].root},
                                       authority=project_data_tools.require_ki_data_source) == []
    with pytest.raises(ValueError, match="local input"):
        request(c)


def test_normal_ki_tool_may_have_no_data_inputs(bundled):
    c = bundled
    step = {"id": "preflight", "ki": "M", "tool": "preflight_check.py", "inputs": []}
    assert project_inputs.review_errors({"steps": [step]}, c[4], c[1], {"M": c[0].root}) == []


def test_previous_producer_keeps_future_project_path_reviewable(bundled):
    c = bundled
    c[4]["items"][0].update(status="ready", local_paths=["outputs/future.csv"])
    producer = {"id": "download", "ki": "M", "kind": "download", "outputs": ["forcing"]}
    adapted = {**c[3], "steps": [producer, *c[3]["steps"]]}
    assert project_inputs.review_errors(adapted, c[4], c[1], {"M": c[0].root},
                                       authority=project_data_tools.require_ki_data_source) == []
    with pytest.raises(ValueError, match="does not exist"):
        request(c)


def test_stale_projection_at_dispatch_returns_denial_without_a_worker(bundled, monkeypatch):
    from kiss_cli import api, execution
    c = bundled
    approve(c)
    ki_adaptations._location(c[0].root).unlink()
    calls = []
    monkeypatch.setattr(execution, "run_process", lambda *a, **kw: calls.append(a))
    with pytest.raises(api.ToolError, match="current signed project projection"):
        run(c)
    assert not calls


@pytest.mark.parametrize("decision", [True, False, 1, {}, [], None, ""])
def test_scientific_choice_requires_actual_chosen_option(bundled, decision):
    c = bundled
    c[3]["scientific_choices"] = [{"id": "production_mode", "high_impact": True,
        "options": ["PP", "WLP_FD"], "picked": "WLP_FD", "decision": decision}]
    errors = review(c)
    assert any("decision must be a nonempty string" in error for error in errors)
    c[3]["scientific_choices"][0]["decision"] = "WLP_FD"
    assert review(c) == []
