"""Update activation must keep the saved selection, GUI and report consistent.

Only the structural KDT engine and transport use test doubles. No scientific
model or provider runs, and every cache/project used here is temporary.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from kiss_cli import ki_updates
from . import test_ki_updates as updater


@pytest.fixture
def case(monkeypatch):
    fixture = updater.KiUpdateTests()
    fixture.setUp()
    fixture._write_ki(fixture.base, "Demo", "old instructions")
    pinned = fixture.root / "pinned-project"
    shutil.copytree(fixture.base, pinned / ".ki")
    (pinned / "config.json").write_text(json.dumps({
        "library_root": str(fixture.base), "ki_root": str(pinned / ".ki")}), encoding="utf-8")
    (pinned / "prepared-helpers").mkdir()
    (pinned / "prepared-helpers" / "helper.py").write_text("# pinned helper\n", encoding="utf-8")
    session = SimpleNamespace(root=fixture.base, calls=[])

    def activate(root):
        session.calls.append(root)
        session.root = root

    manager = ki_updates.UpdateManager(fixture.base, activate, branch="main")
    monkeypatch.setattr(manager, "_request_json", lambda *_: pytest.fail("Unexpected live network"))
    value = SimpleNamespace(fixture=fixture, manager=manager, monkeypatch=monkeypatch,
                            session=session, pinned=pinned,
                            state_path=fixture.home / "state.json")
    try:
        yield value
    finally:
        fixture.tearDown()


def _bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def _state_bytes(case):
    return case.state_path.read_bytes() if case.state_path.exists() else None


def _pipeline(case, *, configure=True):
    if configure:
        archive = case.fixture._archive({"Demo": "new instructions", "Other": "new KI"})
        case.manager._component_trees = {"models": "a" * 40, "manifests": "b" * 40,
                                         "shared_tools": "c" * 40, "data_kis": None}
        case.manager._source_commit = "d" * 40
        case.monkeypatch.setattr(case.manager, "_remote_revision", lambda: (
            ki_updates._revision_identity(case.manager._component_trees), "a" * 40, "b" * 40))
        case.monkeypatch.setattr(case.manager, "_download", lambda target: shutil.copyfile(archive, target))
    case.manager._run()
    return case.manager.status()


def _assert_kept(case, before, pinned):
    assert _state_bytes(case) == before
    assert case.session.root == case.fixture.base
    assert case.manager.current_library_root == case.fixture.base
    assert _bytes(case.pinned) == pinned


def test_callback_failure_restores_session_before_saved_pointer_changes(case):
    before, pinned = _state_bytes(case), _bytes(case.pinned)

    def activate(root):
        case.session.calls.append(root)
        case.session.root = root  # A failing callback may have partially changed the GUI.
        if root != case.fixture.base:
            raise RuntimeError("Candidate catalogue activation failed")

    case.manager.activate = activate
    report = _pipeline(case)
    _assert_kept(case, before, pinned)
    assert case.session.calls[-1] == case.fixture.base
    assert report["state"] == "error"
    assert report["activation"]["outcome"] == "restored"
    assert "Candidate catalogue activation failed" in report["error"]


@pytest.mark.parametrize("saved", [False, True])
def test_state_write_failure_rolls_back_callback_and_preserves_old_bytes(case, monkeypatch, saved):
    if saved:
        case.state_path.parent.mkdir(parents=True, exist_ok=True)
        # Preserve bytes, including fields this updater does not understand.
        case.state_path.write_bytes(b'{ "active_snapshot": "older", "owner": "previous" }\n')
    before, pinned = _state_bytes(case), _bytes(case.pinned)
    actual = ki_updates._atomic_json

    def fail_state(path, value):
        if path == case.state_path:
            raise OSError("Cannot replace saved library selection")
        actual(path, value)

    monkeypatch.setattr(ki_updates, "_atomic_json", fail_state)
    report = _pipeline(case)
    assert len(case.session.calls) == 2, "Candidate callback must run before persistence, then roll back"
    _assert_kept(case, before, pinned)
    assert report["activation"]["outcome"] == "restored"


def test_failed_rollback_reports_uncertainty_without_old_active_labels(case, monkeypatch):
    before = _state_bytes(case)

    def activate(root):
        case.session.calls.append(root)
        if root == case.fixture.base:
            raise RuntimeError("Old catalogue cannot be restored")
        case.session.root = root

    actual = ki_updates._atomic_json
    def fail_state(path, value):
        if path == case.state_path:
            raise OSError("Cannot save selection")
        actual(path, value)

    case.manager.activate = activate
    monkeypatch.setattr(ki_updates, "_atomic_json", fail_state)
    report = _pipeline(case)
    assert _state_bytes(case) == before
    assert case.session.root != case.fixture.base
    assert report["state"] == "error"
    assert report["activation"]["outcome"] == "uncertain"
    assert "uncertain" in report["summary"].lower()
    assert "kept the current" not in report["summary"].lower()
    assert not report.get("active_revision") and not report.get("components")
    assert report.get("windows_overlay") is None and report.get("reference_cases") is None
    assert "Old catalogue cannot be restored" in report["activation"]["rollback_error"]
    assert report["activation"]["restart_required"] is True
    calls = list(case.session.calls)
    assert case.manager.start() is False
    assert case.manager.status()["state"] == "error"
    assert case.manager.status()["activation"]["restart_required"] is True
    assert case.session.calls == calls
    case.manager._run()
    assert case.manager.status()["state"] == "error" and case.session.calls == calls


def test_fresh_session_reconciles_historical_uncertainty_and_allows_retry(case):
    case.manager._set(state="error", summary="Activation is uncertain; restart", error="Old rollback failed",
        activation={"outcome": "uncertain", "restart_required": True, "current_root": None},
        active_revision="old-revision", components={"library_root": "wrong"})
    reopened = ki_updates.UpdateManager(case.fixture.base, case.manager.activate, branch="main")
    report = reopened.status()
    assert report["state"] == "idle" and report["activation"] is None
    assert report["previous_activation"]["outcome"] == "uncertain"
    assert not report.get("active_revision")
    assert report["components"] == ki_updates.component_sources(case.fixture.base)
    case.manager = reopened
    assert _pipeline(case)["state"] == "updated"


def test_foreign_state_change_during_validation_is_not_overwritten(case, monkeypatch):
    foreign = b'{"active_snapshot":"foreign","owner":"another updater"}\n'
    actual_validate = case.manager._validate

    def validate(root):
        result = actual_validate(root)
        case.state_path.write_bytes(foreign)
        return result

    monkeypatch.setattr(case.manager, "_validate", validate)
    report = _pipeline(case)
    assert _state_bytes(case) == foreign
    assert not case.session.calls
    assert case.session.root == case.fixture.base
    assert report["state"] == "error"
    assert "changed" in report["error"].lower()


def test_foreign_state_change_during_callback_is_preserved_and_session_restored(case):
    foreign = b'{"active_snapshot":"foreign","owner":"another updater"}\n'

    def activate(root):
        case.session.calls.append(root)
        case.session.root = root
        if root != case.fixture.base:
            case.state_path.write_bytes(foreign)

    case.manager.activate = activate
    report = _pipeline(case)
    assert _state_bytes(case) == foreign
    assert case.session.root == case.fixture.base
    assert case.session.calls[-1] == case.fixture.base
    assert report["state"] == "error" and report["activation"]["outcome"] == "restored"


def test_writer_error_after_replace_reconciles_committed_selection(case, monkeypatch):
    actual = ki_updates._atomic_json

    def write_then_fail(path, value):
        actual(path, value)
        if path == case.state_path:
            raise OSError("Writer raised after successful replace")

    monkeypatch.setattr(ki_updates, "_atomic_json", write_then_fail)
    report = _pipeline(case)
    selected = ki_updates.active_library_root()
    assert selected is not None and selected != case.fixture.base
    assert case.session.root == selected == case.manager.current_library_root
    assert len(case.session.calls) == 1
    assert report["activation"]["outcome"] == "committed"
    assert "kept the current" not in report["summary"].lower()
    assert report["active_revision"] == selected.name
    assert report["components"] == ki_updates.component_sources(selected)


def test_report_failure_after_commit_does_not_claim_previous_library_was_kept(case, monkeypatch):
    actual_set = case.manager._set
    fired = False

    def fail_success_report(**values):
        nonlocal fired
        if values.get("state") in {"updated", "up_to_date"} and not fired:
            fired = True
            raise OSError("Could not save success report")
        actual_set(**values)

    monkeypatch.setattr(case.manager, "_set", fail_success_report)
    report = _pipeline(case)
    selected = ki_updates.active_library_root()
    assert fired and selected is not None
    assert case.session.root == selected == case.manager.current_library_root
    assert report["state"] == "error"
    assert report["activation"]["outcome"] == "committed"
    assert "kept the current" not in report["summary"].lower()
    assert report["active_revision"] == selected.name
    assert report["components"] == ki_updates.component_sources(selected)


def test_persistent_report_write_failure_after_commit_leaves_terminal_memory_status(case, monkeypatch):
    actual = ki_updates._atomic_json

    def fail_reports_after_commit(path, value):
        if path.name == "last-report.json" and case.state_path.exists():
            raise OSError("Report storage unavailable")
        actual(path, value)

    monkeypatch.setattr(ki_updates, "_atomic_json", fail_reports_after_commit)
    report = _pipeline(case)
    selected = ki_updates.active_library_root()
    assert selected is not None and selected == case.session.root
    assert report["state"] == "error" and report["progress"] is None
    assert report["activation"]["outcome"] == "committed"
    assert "kept the current" not in report["summary"].lower()
    assert report["components"] == ki_updates.component_sources(selected)


def test_report_write_failure_at_start_leaves_terminal_memory_without_worker(case, monkeypatch):
    actual = ki_updates._atomic_json

    def fail_reports(path, value):
        if path.name == "last-report.json":
            raise OSError("Report storage unavailable before worker starts")
        actual(path, value)

    monkeypatch.setattr(ki_updates, "_atomic_json", fail_reports)
    assert case.manager.start() is False
    report = case.manager.status()
    assert report["state"] == "error" and report["progress"] is None
    assert report["activation"] is None
    assert case.manager._thread is None and not case.session.calls


def test_ancillary_proxy_settings_failure_cannot_conceal_committed_error(case, monkeypatch):
    actual_proxy, actual_set = ki_updates.settings.proxy_url_for, case.manager._set

    def fail_proxy_after_commit(*args, **kwargs):
        if case.state_path.exists():
            raise OSError("Proxy settings unreadable")
        return actual_proxy(*args, **kwargs)

    def fail_success_report(**values):
        if values.get("state") in {"updated", "up_to_date"}:
            raise OSError("Success report failed")
        actual_set(**values)

    monkeypatch.setattr(ki_updates.settings, "proxy_url_for", fail_proxy_after_commit)
    monkeypatch.setattr(case.manager, "_set", fail_success_report)
    report = _pipeline(case)
    assert report["state"] == "error" and report["progress"] is None
    assert report["activation"]["outcome"] == "committed"
    assert report["activation"]["current_root"] == str(case.session.root)


def test_active_label_failure_cannot_conceal_committed_error(case, monkeypatch):
    actual = ki_updates.component_sources

    def fail_labels(root, *args, **kwargs):
        if root != case.fixture.base:
            raise OSError("Active component labels unavailable")
        return actual(root, *args, **kwargs)

    monkeypatch.setattr(ki_updates, "component_sources", fail_labels)
    report = _pipeline(case)
    assert report["state"] == "error" and report["activation"]["outcome"] == "committed"
    assert report["activation"]["current_root"] == str(case.session.root)
    assert "kept the current" not in report["summary"].lower()
    assert report["components"] == {}


def test_pointer_unreadable_after_failed_write_is_explicitly_uncertain(case, monkeypatch):
    actual_write, actual_read = ki_updates._atomic_json, Path.read_bytes
    attempted = False

    def fail_state(path, value):
        nonlocal attempted
        if path == case.state_path:
            attempted = True
            raise OSError("Selection writer failed")
        actual_write(path, value)

    def fail_pointer_read(path):
        if attempted and path == case.state_path:
            raise PermissionError("Cannot inspect selection after failure")
        return actual_read(path)

    monkeypatch.setattr(ki_updates, "_atomic_json", fail_state)
    monkeypatch.setattr(Path, "read_bytes", fail_pointer_read)
    report = _pipeline(case)
    assert attempted
    assert report["state"] == "error" and report["activation"]["outcome"] == "uncertain"
    assert "uncertain" in report["summary"].lower()
    assert "kept the current" not in report["summary"].lower()
    assert not report.get("components") and not report.get("active_revision")


def test_success_activates_before_saving_and_does_not_touch_pinned_project(case):
    before, pinned = _state_bytes(case), _bytes(case.pinned)
    observed = []

    def activate(root):
        observed.append(_state_bytes(case))
        case.session.calls.append(root)
        case.session.root = root

    case.manager.activate = activate
    report = _pipeline(case)
    assert report["state"] == "updated", report.get("error")
    assert observed == [before]
    selected = ki_updates.active_library_root()
    assert selected == case.session.root == case.manager.current_library_root
    assert _bytes(case.pinned) == pinned
    assert report["activation"]["outcome"] == "committed"


def test_fastpath_activation_failure_restores_session_without_rewriting_pointer(case, monkeypatch):
    first = _pipeline(case)
    assert first["state"] == "updated", first.get("error")
    before = _state_bytes(case)
    candidate = case.manager.current_library_root
    # A fresh app session has its bundled catalogue until saved selection loads.
    case.manager.current_library_root = case.fixture.base
    case.session.root = case.fixture.base
    case.session.calls.clear()

    def activate(root):
        case.session.calls.append(root)
        case.session.root = root
        if root == candidate:
            raise RuntimeError("Saved catalogue activation failed")

    case.manager.activate = activate
    monkeypatch.setattr(case.manager, "_download", lambda *_: pytest.fail("Fast path downloaded archive"))
    report = _pipeline(case, configure=False)
    assert _state_bytes(case) == before
    assert case.session.calls == [candidate, case.fixture.base]
    assert case.session.root == case.manager.current_library_root == case.fixture.base
    assert report["state"] == "error" and report["activation"]["outcome"] == "restored"
    assert report["components"] == ki_updates.component_sources(case.fixture.base)
    assert not report.get("active_revision")

