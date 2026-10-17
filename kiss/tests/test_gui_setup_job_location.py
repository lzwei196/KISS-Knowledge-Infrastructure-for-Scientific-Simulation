"""A new setup folder must not inherit another folder's terminal job banner."""
from types import SimpleNamespace

from kiss_cli import gui, install_locations, setup_jobs


def test_setup_get_filters_cancelled_history_after_location_changes(tmp_path, monkeypatch):
    workroot, old, selected = tmp_path / "work", tmp_path / "old", tmp_path / "new"
    job = setup_jobs.start(workroot, "Demo", old, "fixture")
    job.finish("cancelled", "Previous folder was stopped")
    old_status = (old / "status.json").read_bytes()
    install_locations.select(workroot, "Demo", selected)

    ki = SimpleNamespace(name="Demo", meta={})
    handler = object.__new__(gui.Handler)
    handler.workroot = workroot
    handler.catalog = SimpleNamespace(get=lambda name: ki)
    handler.path = "/api/setup/Demo"
    handler._json = lambda body, status=200: (status, body)
    handler._manifest_verified = lambda value: "unverified"
    handler._required_data_state = lambda *args, **kwargs: {}
    handler._status_for = lambda value: {"state": "missing", "can_run": False}
    handler._setup_project_preflight_state = lambda *args: {}
    monkeypatch.setattr(gui.setup_flow, "setup_state",
                        lambda root, status: {"workspace": str(root)})

    status, body = handler._do_GET()
    assert status == 200
    assert body["workspace"] == str(selected)
    assert body["job"] is None
    assert (old / "status.json").read_bytes() == old_status

    # Selecting the earlier folder restores its own durable history.
    install_locations.select(workroot, "Demo", old)
    handler._install_location_index = None
    _, body = handler._do_GET()
    assert body["job"]["id"] == job.id
    assert body["job"]["state"] == "cancelled"
