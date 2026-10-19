"""Capacity refusal is read-only; it never authorizes or starts adoption."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import api, gui, setup, setup_capacity as capacity, setup_jobs
from .test_setup_final_runtime import case
from .test_gui_setup_jobs import ready


@pytest.fixture(autouse=True)
def controlled_volumes(tmp_path, monkeypatch):
    # The test host really has an exhausted C: volume. Results must depend on
    # these fixtures, not its free space, and temporary test data stays on D:.
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    monkeypatch.setattr(capacity, "_temporary_root", lambda: temporary)
    monkeypatch.setattr(capacity, "_volume", lambda path: (1, str(tmp_path), 10 * 1024**3))


def contents(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def test_existing_ancestor_probe_never_makes_requested_directories(tmp_path):
    before = contents(tmp_path)
    destination = tmp_path / "not-yet-created" / "workspace"
    assert capacity._ancestor(destination) == tmp_path.resolve()
    assert not destination.parent.exists()
    assert contents(tmp_path) == before


def test_free_space_probe_uses_real_existing_destination_volume(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(capacity.shutil, "disk_usage", lambda path:
                        seen.append(path) or SimpleNamespace(free=1234))
    # Restore only this function, whose implementation is intentionally small.
    from importlib.util import spec_from_file_location, module_from_spec
    spec = spec_from_file_location("kiss_cli._capacity_probe_fixture", capacity.__file__)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    ident, label, free = module._volume(tmp_path / "new-root")
    assert ident == tmp_path.stat().st_dev and label == str(tmp_path.resolve()) and free == 1234
    assert seen == [tmp_path.resolve()]
    assert not (tmp_path / "new-root").exists()


def test_same_volume_sums_copies_and_reserves_headroom_once(tmp_path, monkeypatch):
    expected = capacity.RESERVE_BYTES + 100 + 200
    monkeypatch.setattr(capacity, "_volume", lambda path: (7, "same-volume", expected))
    rows = capacity._require([(tmp_path / "a", 100, "a"), (tmp_path / "b", 200, "b")])
    assert len(rows) == 1 and rows[0]["required_bytes"] == expected
    assert rows[0]["copy_bytes"] == 300 and rows[0]["purposes"] == ["a", "b"]


def test_separate_full_authority_volume_cannot_borrow_workspace_free_space(tmp_path, monkeypatch):
    def volume(path):
        return (1, "workspace-volume", 10**10) if Path(path).name == "work" else (2, "authority-volume", 0)
    monkeypatch.setattr(capacity, "_volume", volume)
    with pytest.raises(capacity.CapacityError) as caught:
        capacity._require([(tmp_path / "work", 100, "replacement"), (tmp_path / "profile", 200, "backup")])
    assert len(caught.value.volumes) == 1
    assert caught.value.volumes[0]["path"] == "authority-volume"
    assert "free another 65 MiB" in str(caught.value)
    assert caught.value.response()["state"] == "waiting_for_user"


def test_unavailable_volume_is_a_typed_actionable_refusal(tmp_path, monkeypatch):
    def fail(path):
        raise OSError("fixture unreadable volume")
    monkeypatch.setattr(capacity, "_volume", fail)
    with pytest.raises(capacity.CapacityError, match="Cannot check free space") as caught:
        capacity._require([(tmp_path, 1, "backup")])
    assert caught.value.response()["needs_user"] is True


def test_bounded_allocation_rounds_small_files_without_reading_bytes(tmp_path):
    root = tmp_path / "ki"
    root.mkdir()
    (root / "a").write_bytes(b"a")
    (root / "b").write_bytes(b"b" * 4097)
    (root / "directory").mkdir()
    assert capacity._allocation(root) == 5 * 4096


def test_repair_estimate_uses_only_active_source_and_prepared_helpers(tmp_path, monkeypatch):
    root, source, helper = tmp_path / "work", tmp_path / "source", tmp_path / "ktc"
    sizes = {root / "ki": 4096, source: 8192, helper: 12288}
    seen = []
    monkeypatch.setattr(capacity, "_allocation", lambda path: seen.append(path) or sizes[path])
    rows = capacity.require_repair(root, workroot=tmp_path, source_root=source, helper_root=helper)
    assert seen == list(sizes)
    context = sum(sizes.values()) + 48 * 1024
    assert rows[0]["copy_bytes"] == 5 * 4096 + 2 * context
    assert rows[0]["required_bytes"] == capacity.RESERVE_BYTES + rows[0]["copy_bytes"]
    assert rows[0]["copy_bytes"] < capacity.ki_investigation.MAX_CONTEXT_BYTES


def test_temp_selection_never_calls_write_probing_gettempdir(tmp_path, monkeypatch):
    # Use the function from the source module rather than the autouse fixture.
    from importlib.util import spec_from_file_location, module_from_spec
    spec = spec_from_file_location("kiss_cli._capacity_temp_fixture", capacity.__file__)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.tempfile, "tempdir", None)
    monkeypatch.setattr(module.tempfile, "gettempdir", lambda: pytest.fail("must not probe by writing"))
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    assert module._temporary_root() == tmp_path


def test_startup_507_precedes_lease_log_request_and_provider(ready, monkeypatch):
    c = ready
    before = contents(c.root)
    monkeypatch.setattr(capacity, "_volume", lambda path: (1, "full-volume", 0))
    monkeypatch.setattr(setup_jobs, "start", lambda *a, **kw: pytest.fail("must not take lease"))
    monkeypatch.setattr(setup, "request", lambda *a, **kw: pytest.fail("must not migrate requests"))
    monkeypatch.setattr(api, "run", lambda *a, **kw: pytest.fail("must not call provider"))
    c.handler._stream_agent_setup({"model": "Demo", "provider": "api:deepseek"})
    status, payload = c.responses[0]
    assert status == 507 and payload["code"] == "setup_storage_capacity"
    assert payload["needs_user"] and "retry setup" in payload["error"]
    assert not c.output and contents(c.root) == before


def test_startup_full_disk_does_not_create_new_workspace(ready, monkeypatch):
    c = ready
    root = c.workroot / "new-workspace"
    c.handler._workdir = lambda ki: root
    monkeypatch.setattr(capacity, "_volume", lambda path: (1, "full-volume", 0))
    c.handler._stream_agent_setup({"model": "Demo", "provider": "api:deepseek"})
    assert c.responses[0][0] == 507 and not root.exists()


def test_capacity_drop_at_repair_checkpoint_waits_without_adoption(ready, monkeypatch):
    from kiss_cli import setup_ki_repair
    c, events = ready, []
    before = contents(c.live.root)
    monkeypatch.setattr(setup_ki_repair, "recipe_for", lambda name: "fixture_recipe")
    def provider(*args, **kwargs):
        assert kwargs["setup_context"]["request_ki_repair"]("fixture path defect")["queued"]
        yield "handoff queued"
    def repair(root, **kwargs):
        kwargs["check_binding"]()
        events.append("initial capacity passed")
        monkeypatch.setattr(capacity, "_volume", lambda path: (1, "full-volume", 0))
        kwargs["check_binding"]()
        pytest.fail("low-capacity checkpoint must not return to adoption")
    monkeypatch.setattr(api, "run", provider)
    monkeypatch.setattr(setup_ki_repair, "run", repair)
    c.handler._stream_agent_setup({"model": "Demo", "provider": "api:deepseek"})
    assert events == ["initial capacity passed"]
    job = setup_jobs.status(c.workroot, "Demo")
    assert job["state"] == "waiting_for_user" and "disk space" in job["detail"]
    assert setup.request(c.root)["status"] == "waiting"
    assert contents(c.live.root) == before
    assert not setup_ki_repair._pointer(c.root).exists()
    assert len(c.seen.preflight) == 1, "capacity refusal cannot reach fresh success preflight"
    assert json.loads((c.root / "status.json").read_text())["ok"] is False


def test_sealed_apply_callback_refuses_before_loading_or_pending_journal(tmp_path, monkeypatch):
    from kiss_cli import setup_ki_repair
    root = tmp_path / "work"
    root.mkdir()
    before = contents(tmp_path)
    monkeypatch.setattr(setup_ki_repair.investigation, "_load",
                        lambda *a: pytest.fail("capacity refusal must precede adoption bookkeeping"))
    def refuse():
        raise capacity.CapacityError([{"path": str(root), "free_bytes": 0,
            "required_bytes": capacity.RESERVE_BYTES}])
    with pytest.raises(capacity.CapacityError):
        setup_ki_repair.apply(root, "0" * 16, "verification", check_binding=refuse)
    assert contents(tmp_path) == before


def test_sufficient_capacity_preserves_normal_provider_and_verification(ready, monkeypatch):
    c, calls = ready, []
    def provider(*args, **kwargs):
        calls.append(True)
        yield "fixture setup done"
    monkeypatch.setattr(api, "run", provider)
    c.handler._stream_agent_setup({"model": "Demo", "provider": "api:deepseek"})
    assert calls == [True]
    assert setup_jobs.status(c.workroot, "Demo")["state"] == "completed", c.output
    assert json.loads((c.root / "status.json").read_text())["ok"] is True
