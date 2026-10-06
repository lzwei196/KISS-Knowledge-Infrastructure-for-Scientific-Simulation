"""Exercise real import/update gates without downloading or running a model.

Only KDT's structural engine is doubled. Candidate hashing, host signatures,
doctor, extraction, quarantine and publication remain the shipped code.
"""
from contextlib import ExitStack, contextmanager, nullcontext
import io
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
from unittest import mock
import zipfile

import pytest

from kiss_cli import gui, kdtstudio, ki_updates, ki_verification


def package_files(name="Demo", skill="# Example KI\n"):
    return {
        "SKILL.md": skill,
        "preflight_check.py": "print('PREFLIGHT_REPORT={}')\n",
        "dag.yaml": (
            "template_version: '3.5'\nidentity:\n"
            f"  model_id: {name}\n  repo_url: https://example.org/model\n"
            "boundary: {}\ninputs: {}\noutputs: {}\nstates: {}\n"
            "processes: {}\ninfluence: {}\nsafety: {}\n"
        ),
    }


def write_package(root, name="Demo", skill="# Example KI\n"):
    root.mkdir(parents=True, exist_ok=True)
    for relative, text in package_files(name, skill).items():
        (root / relative).write_text(text, encoding="utf-8", newline="")


def zip_package():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for relative, text in package_files().items():
            archive.writestr("Demo/" + relative, text)
    return stream.getvalue()


@contextmanager
def isolated_engine(root):
    """Explicit fixture boundary for import/updater tests, never production."""
    state = SimpleNamespace(installed=True, ok=True, seen=[])

    def verify(candidate, *, kind):
        state.seen.append((candidate.name, kind))
        return {"ok": state.ok, "failures": [] if state.ok else ["fixture KDT failure"],
                "warnings": [], "info": {}}

    with ExitStack() as stack:
        stack.enter_context(mock.patch.dict(os.environ, {
            "GEOFORGE_KI_VERIFICATION_HOME": str(root / "acceptance"),
            "GEOFORGE_FLOW_KEYS": str(root / "keys"),
        }))
        stack.enter_context(mock.patch.object(kdtstudio, "engine_status", lambda: {
            "installed": state.installed, "commit": kdtstudio.REVIEWED_COMMIT,
            "source_digest": "f" * 64}))
        stack.enter_context(mock.patch.object(kdtstudio, "engine_source_digest", lambda *_: "f" * 64))
        stack.enter_context(mock.patch.object(kdtstudio, "_engine_imports", nullcontext))
        stack.enter_context(mock.patch.object(kdtstudio, "_load_engine_module", lambda *_: SimpleNamespace(verify=verify)))
        yield state


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_UPDATE_HOME", str(tmp_path / "updates"))
    with isolated_engine(tmp_path) as state:
        yield state


def import_handler(tmp_path, *, validate=False):
    captured = {}
    handler = object.__new__(gui.Handler)
    handler.path = "/api/import_ki?name=Demo.zip" + ("&validate=1" if validate else "")
    handler.catalog = SimpleNamespace(packages={}, user_dir=tmp_path / "user", refresh=lambda: None)
    handler._json = lambda obj, code=200: captured.update(body=obj, code=code)
    return handler, captured


@pytest.mark.parametrize("failure", ["missing_engine", "failed_kdt"])
def test_import_refuses_unverified_candidate_and_does_not_publish(tmp_path, engine, failure):
    engine.installed = failure != "missing_engine"
    engine.ok = failure != "failed_kdt"
    handler, response = import_handler(tmp_path)
    handler._import_ki_bytes(zip_package())
    assert response["code"] == 422
    assert response["body"]["state"] == "Draft"
    assert response["body"]["ready_to_import"] is False
    assert not (handler.catalog.user_dir / "Demo").exists()


def test_import_validate_only_is_verified_without_publishing(tmp_path, engine):
    handler, response = import_handler(tmp_path, validate=True)
    handler._import_ki_bytes(zip_package())
    assert response["code"] == 200
    assert response["body"]["state"] == "Verified"
    assert response["body"]["verification"]["native_regression"]["verified"] is False
    assert not (handler.catalog.user_dir / "Demo").exists()


def test_import_publishes_exact_verified_bytes_and_drift_loses_acceptance(tmp_path, engine):
    handler, response = import_handler(tmp_path)
    handler._import_ki_bytes(zip_package())
    assert response["code"] == 200 and response["body"]["state"] == "Active"
    installed = handler.catalog.user_dir / "Demo"
    acceptance = response["body"]["verification"]
    assert ki_verification.require_current(installed, acceptance) == acceptance
    assert ki_verification.current_report(installed) == acceptance
    (installed / "SKILL.md").write_text("# Local edit after activation\n", encoding="utf-8")
    assert ki_verification.current_report(installed) is None


def test_import_rechecks_the_hidden_copied_tree_before_publication(tmp_path, engine, monkeypatch):
    handler, response = import_handler(tmp_path)
    real_require = ki_verification.require_current

    def change_copied_tree(root, report, **kwargs):
        if root.parent.name.startswith(".ki-import-"):
            (root / "SKILL.md").write_text("# Changed during publication\n", encoding="utf-8")
        return real_require(root, report, **kwargs)

    monkeypatch.setattr(ki_verification, "require_current", change_copied_tree)
    handler._import_ki_bytes(zip_package())
    assert response["code"] == 422 and response["body"]["state"] == "Draft"
    assert "changed" in response["body"]["error"]
    assert not (handler.catalog.user_dir / "Demo").exists()


def updater(tmp_path, monkeypatch, *, changed=True, data_ki=False):
    base = tmp_path / "base"
    write_package(base / "models/Demo", skill="# Existing KI\n")
    archive_path = tmp_path / "source.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        prefix = "repository/"
        archive.writestr(prefix + "ki_tools_common/pyproject.toml", '[project]\nname="ki_tools_common"\nversion="0.1.0"\n')
        archive.writestr(prefix + "ki_tools_common/ki_tools_common/__init__.py", "")
        for relative, text in package_files(skill="# Changed KI\n" if changed else "# Existing KI\n").items():
            archive.writestr(prefix + "models/Demo/" + relative, text)
        if data_ki:
            for relative, text in package_files("DataReader").items():
                archive.writestr(prefix + "kiss/data_kis/DataReader/" + relative, text)
    activated = []
    manager = ki_updates.UpdateManager(base, activated.append)
    manager._source_commit = "d" * 40
    manager._component_trees = {"models": "a" * 40, "manifests": None,
                                "shared_tools": "c" * 40, "data_kis": "e" * 40 if data_ki else None}
    monkeypatch.setattr(manager, "_remote_revision", lambda: ("a" * 32, "a" * 40, None))
    monkeypatch.setattr(manager, "_download", lambda target: shutil.copyfile(archive_path, target))
    return manager, activated


@pytest.mark.parametrize("failure", ["missing_engine", "failed_kdt"])
def test_updated_ki_gate_failure_preserves_active_library_and_quarantines(tmp_path, engine, monkeypatch, failure):
    engine.installed = failure != "missing_engine"
    engine.ok = failure != "failed_kdt"
    manager, activated = updater(tmp_path, monkeypatch)
    manager._run()
    report = manager.status()
    assert report["state"] == "error" and activated == []
    assert "KDT verification required" in report["error"]
    assert not (tmp_path / "updates/state.json").exists()
    assert (tmp_path / "base/models/Demo/SKILL.md").read_text() == "# Existing KI\n"
    assert report["validation_failure"]["activated"] is False
    assert Path(report["validation_failure"]["quarantine_path"]).is_dir()


def test_unchanged_shipped_ki_is_retained_without_claiming_kdt_pass(tmp_path, engine, monkeypatch):
    engine.installed = False
    manager, activated = updater(tmp_path, monkeypatch, changed=False)
    manager._run()
    assert len(activated) == 1
    assert engine.seen == []
    meta = json.loads((activated[0] / ki_updates.SNAPSHOT_MANIFEST).read_text(encoding="utf-8"))
    assert meta["ki_verification"] == [{"name": "Demo", "state": "unchanged_existing"}]
    assert meta["reference_cases"]["native_verification"] == "not_performed"


def test_new_data_ki_cannot_bypass_the_shared_gate(tmp_path, engine, monkeypatch):
    engine.ok = False
    manager, activated = updater(tmp_path, monkeypatch, changed=False, data_ki=True)
    manager._run()
    assert activated == []
    assert "DataReader: KDT verification required" in manager.status()["error"]


@pytest.mark.parametrize("mutation_point", ["after_validation", "before_activation"])
def test_updated_candidate_changed_after_verification_is_not_activated(tmp_path, engine, monkeypatch, mutation_point):
    manager, activated = updater(tmp_path, monkeypatch)
    if mutation_point == "after_validation":
        validate = manager._validate

        def mutate(root):
            result = validate(root)
            (root / "models/Demo/SKILL.md").write_text("# late edit\n", encoding="utf-8")
            return result

        monkeypatch.setattr(manager, "_validate", mutate)
    else:
        atomic = ki_updates._atomic_json

        def mutate(path, doc):
            atomic(path, doc)
            if path.name == ki_updates.SNAPSHOT_MANIFEST and path.parent.name.startswith(".incoming-"):
                (path.parent / "models/Demo/SKILL.md").write_text("# final edit\n", encoding="utf-8")

        monkeypatch.setattr(ki_updates, "_atomic_json", mutate)
    manager._run()
    assert activated == []
    assert "changed" in manager.status()["error"]
    assert not (tmp_path / "updates/state.json").exists()


def test_old_static_validation_policy_does_not_skip_new_shared_gate(tmp_path, engine, monkeypatch):
    manager, activated = updater(tmp_path, monkeypatch)
    manager._run()
    assert len(activated) == 1 and len(engine.seen) == 1
    state_path = tmp_path / "updates/state.json"
    state = json.loads(state_path.read_text())
    state["validation_policy"] = "ki-doctor-reference-cases-v1"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    # Simulate a fresh host loading that older policy, not the current manager's
    # already adopted tree. A policy transition must inspect the archive again.
    manager.current_library_root = tmp_path / "base"
    engine.ok = False
    manager._run()
    assert len(activated) == 1
    assert "KDT verification required" in manager.status()["error"]
