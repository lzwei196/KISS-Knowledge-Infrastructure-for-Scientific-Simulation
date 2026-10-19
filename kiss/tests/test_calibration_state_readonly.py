"""Status polling observes calibration state; preparation is an explicit action."""
import json
from pathlib import Path

import pytest

from kiss_cli import calibration
from kiss_cli.catalog import KI


def _tree(root):
    """Reads may change access times, but no file identity/content may change."""
    if not root.exists():
        return None
    result = {}
    for path in sorted(root.rglob("*")):
        st = path.stat()
        result[path.relative_to(root).as_posix()] = (
            path.is_dir(), st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns,
            None if path.is_dir() else path.read_bytes())
    return result


def _ki(root, name="Demo", files=("calibration.yaml", "tools/calib_run.py")):
    source = root / name
    source.mkdir(parents=True)
    for relative in files:
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# reusable adapter\n", encoding="utf-8")
    return KI(name, source)


@pytest.fixture
def runtime(monkeypatch):
    current = {"available": True, "ready": True, "engine_root": "current-engine",
               "commit": "current-build", "dependencies": {"numpy": {"available": True}}}
    monkeypatch.setattr(calibration, "framework_status", lambda: dict(current))
    return current


def _forbid_preparation(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("status polling attempted calibration preparation")
    for name in ("ensure_project", "_adapter", "_copy_once"):
        monkeypatch.setattr(calibration, name, fail)


@pytest.mark.parametrize("existing_project", [False, True])
@pytest.mark.parametrize("source_files", [(), ("calibration.yaml",),
                                           ("calibration.yaml", "tools/calib_run.py")])
def test_unprepared_selected_ki_stays_unprepared_without_any_writes(
        tmp_path, monkeypatch, runtime, existing_project, source_files):
    ki = _ki(tmp_path / "models", files=source_files)
    project = tmp_path / "project"
    if existing_project:
        project.mkdir()
    before = _tree(project)
    _forbid_preparation(monkeypatch)

    state = calibration.project_state(project, [ki])

    assert _tree(project) == before
    assert state["ready"] is True  # Shared engine availability is separate.
    assert state["ready_adapter_count"] == state["case_count"] == state["run_count"] == 0
    assert state["latest_run"] is None
    assert state["adapters"] == [{
        "ki": "Demo", "status": "authoring-needed", "contract": None, "runner": None,
        "source_has_contract": "calibration.yaml" in source_files,
        "source_has_runner": "tools/calib_run.py" in source_files}]


def test_poll_observes_new_runtime_but_preserves_preparation_and_run_records(tmp_path, monkeypatch, runtime):
    ki = _ki(tmp_path / "models")
    project = tmp_path / "project"
    calibration.ensure_project(project, [ki])
    manifest = project / "calibration" / calibration.MANIFEST
    retained = json.loads(manifest.read_text(encoding="utf-8"))
    retained.update(engine_root="historical-engine", commit="historical-build", ready=False)
    manifest.write_text(json.dumps(retained, indent=4) + "\n", encoding="utf-8")
    case = project / "calibration/cases/observations.csv"
    case.write_text("time,Q\n1,2\n", encoding="utf-8")
    report = project / "calibration/runs/retained/report.json"
    report.parent.mkdir()
    report.write_text(json.dumps({"ki": "Demo", "report": {
        "status": "completed", "promotable": False, "holdout": {"passed": False}}}), encoding="utf-8")
    before = _tree(project)
    _forbid_preparation(monkeypatch)

    first = calibration.project_state(project, [ki])
    runtime.update(ready=False, dependencies={"numpy": {"available": False}})
    second = calibration.project_state(project)  # Auto-KI still shows retained adapter.

    assert _tree(project) == before
    assert first["engine_root"] == second["engine_root"] == "current-engine"
    assert first["ready"] is True and second["ready"] is False
    assert first["ready_adapter_count"] == second["ready_adapter_count"] == 1
    assert first["case_count"] == second["case_count"] == 1
    assert first["run_count"] == second["run_count"] == 1
    assert second["latest_run"]["promotable"] is False
    assert second["latest_run"]["holdout"] == {"passed": False}


def test_poll_does_not_repair_missing_adapter_or_copy_new_selection(tmp_path, monkeypatch, runtime):
    old = _ki(tmp_path / "models", "Retained")
    new = _ki(tmp_path / "models", "New")
    project = tmp_path / "project"
    calibration.ensure_project(project, [old])
    (project / "calibration/kis/Retained/tools/calib_run.py").unlink()
    before = _tree(project)
    _forbid_preparation(monkeypatch)

    state = calibration.project_state(project, [old, new])

    assert _tree(project) == before
    assert state["ready_adapter_count"] == 0
    assert {item["ki"]: item["status"] for item in state["adapters"]} == {
        "New": "authoring-needed", "Retained": "authoring-needed"}
    assert state["adapters"][1]["source_has_runner"] is True


def test_invalid_saved_manifest_is_not_rewritten_and_existing_adapter_is_visible(tmp_path, monkeypatch, runtime):
    ki = _ki(tmp_path / "models")
    project = tmp_path / "project"
    calibration.ensure_project(project, [ki])
    (project / "calibration" / calibration.MANIFEST).write_text("invalid saved JSON\n", encoding="utf-8")
    before = _tree(project)
    _forbid_preparation(monkeypatch)

    state = calibration.project_state(project)

    assert _tree(project) == before
    assert state["ready_adapter_count"] == 1
    assert state["adapters"][0]["ki"] == "Demo"


def test_explicit_preparation_still_copies_adapter_and_preserves_project_edits(tmp_path, runtime):
    ki = _ki(tmp_path / "models")
    project = tmp_path / "project"
    assert calibration.project_state(project, [ki])["ready_adapter_count"] == 0
    prepared = calibration.ensure_project(project, [ki])
    assert prepared["adapters"][0]["status"] == "ready"
    assert (project / "calibration" / calibration.MANIFEST).is_file()
    assert (project / "calibration/README.md").is_file()
    for rel in ("cases", "runs", "runtime"):
        assert (project / "calibration" / rel).is_dir()
    contract = project / "calibration/kis/Demo/calibration.yaml"
    contract.write_text("# project-specific contract\n", encoding="utf-8")
    calibration.ensure_project(project, [ki])
    assert contract.read_text(encoding="utf-8") == "# project-specific contract\n"
    assert calibration.project_state(project, [ki])["ready_adapter_count"] == 1
