"""Upload storage tests: fixture files only, no provider or project execution."""
from __future__ import annotations

import copy
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from kiss_cli import sessions


@pytest.fixture
def upload_project(tmp_path):
    workroot = tmp_path / "workspace"
    session = sessions.create(workroot)
    project = sessions.project_path(workroot, session)
    return workroot, session, project


def test_repeated_names_never_overwrite_even_in_same_second(upload_project, monkeypatch):
    workroot, session, _ = upload_project
    monkeypatch.setattr(sessions.time, "time", lambda: 1700000000)
    saved = [sessions.save_upload(workroot, session, "weather.csv", data)
             for data in (b"first", b"second", b"third", b"fourth")]
    assert len(set(saved)) == 4
    assert [path.read_bytes() for path in saved] == [b"first", b"second", b"third", b"fourth"]


def test_concurrent_uploads_use_exclusive_creation(upload_project):
    workroot, session, _ = upload_project
    contents = [f"upload-{i}".encode() for i in range(24)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        saved = list(pool.map(lambda data: sessions.save_upload(
            workroot, session, "shared.csv", data, item="observations"), contents))
    assert len(set(saved)) == len(contents)
    assert [path.read_bytes() for path in saved] == contents


@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("folder,item", [
    ("inputs", ""), ("inputs/uploads", ""),
    ("inputs/user", "site"), ("inputs/user/site", "site"),
])
def test_symlink_parent_cannot_write_outside_project(upload_project, tmp_path, monkeypatch,
                                                   folder, item, fallback):
    workroot, session, project = upload_project
    if fallback:
        monkeypatch.setattr(os, "supports_dir_fd", set())
    outside = tmp_path / "outside"
    outside.mkdir()
    target = project / folder
    if target.exists():
        # Preserve fixture contents; make the symlink the only changed component.
        target.rename(project / ("old-" + folder.replace("/", "-")))
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(outside, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        sessions.save_upload(workroot, session, "data.csv", b"private", item=item)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("fallback", [False, True])
@pytest.mark.parametrize("existing", [False, True])
def test_symlink_target_is_never_followed(upload_project, tmp_path, monkeypatch, existing, fallback):
    workroot, session, project = upload_project
    if fallback:
        monkeypatch.setattr(os, "supports_dir_fd", set())
    outside = tmp_path / "outside.csv"
    if existing:
        outside.write_bytes(b"original")
    (project / "inputs/uploads/data.csv").symlink_to(outside)
    try:
        saved = sessions.save_upload(workroot, session, "data.csv", b"new")
    except (ValueError, OSError):
        pass
    else:
        assert not saved.is_symlink()
        assert saved.resolve().is_relative_to(project / "inputs/uploads")
        assert saved.read_bytes() == b"new"
    if existing:
        assert outside.read_bytes() == b"original"
    else:
        assert not outside.exists()


@pytest.mark.parametrize("existing", [False, True])
def test_fallback_rejects_link_entry_before_open(upload_project, tmp_path, monkeypatch, existing):
    workroot, session, project = upload_project
    monkeypatch.setattr(os, "supports_dir_fd", set())
    outside = tmp_path / "outside.csv"
    if existing:
        outside.write_bytes(b"original")
    target = project / "inputs/uploads/data.csv"
    target.symlink_to(outside)
    assert os.path.lexists(target)
    assert target.exists() is existing
    opened = []
    def forbidden(*args):
        opened.append(args)
        raise AssertionError("A known reparse target must be rejected before opening it")
    monkeypatch.setattr(sessions, "_open_upload_new", forbidden)
    with pytest.raises(ValueError, match="upload target"):
        sessions.save_upload(workroot, session, "data.csv", b"private")
    assert not opened and target.is_symlink()
    assert outside.read_bytes() == b"original" if existing else not outside.exists()


@pytest.mark.skipif(os.name != "nt", reason="Native Windows reparse-point creation boundary")
def test_windows_link_inserted_after_lstat_is_never_opened(upload_project, tmp_path, monkeypatch):
    workroot, session, project = upload_project
    outside = tmp_path / "outside.csv"
    target = project / "inputs/uploads/data.csv"
    original = sessions._open_upload_new
    intercepted = []
    def insert_link_then_open(path, flags):
        path = Path(path)
        if not intercepted:
            assert path == target and not os.path.lexists(path)
            # The ordinary lstat has already found no entry. Replace that
            # state before the real native CREATE_NEW/OPEN_REPARSE_POINT call.
            path.symlink_to(outside)
            intercepted.append(path)
        return original(path, flags)
    monkeypatch.setattr(sessions, "_open_upload_new", insert_link_then_open)
    saved = sessions.save_upload(workroot, session, "data.csv", b"private")
    assert intercepted == [target]
    assert saved != target and not saved.is_symlink()
    assert saved.read_bytes() == b"private"
    assert target.is_symlink() and not outside.exists()


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.skipif(os.name != "nt", reason="Native Windows reparse-point creation boundary")
def test_windows_native_create_refuses_existing_link_without_lstat(tmp_path, existing):
    outside = tmp_path / "outside.csv"
    if existing:
        outside.write_bytes(b"original")
    link = tmp_path / "upload.csv"
    link.symlink_to(outside)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_BINARY
    with pytest.raises(FileExistsError):
        sessions._open_upload_new(link, flags)
    assert link.is_symlink()
    assert outside.read_bytes() == b"original" if existing else not outside.exists()


def test_generic_and_targeted_uploads_keep_sanitized_paths_and_state(upload_project):
    workroot, session, project = upload_project
    for relative in ("runs/plan.json", "runs/data-inventory.json", "runs/approval.json",
                     ".geoforge/state.json"):
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"unchanged")
    before_session = copy.deepcopy(session)
    before = {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}
    generic = sessions.save_upload(workroot, session, "../../weather data.csv", b"rain")
    targeted = sessions.save_upload(workroot, session, "site.csv", b"point", item="../site_geometry")
    assert generic == project / "inputs/uploads/weather_data.csv"
    assert targeted == project / "inputs/user/site_geometry/site.csv"
    assert session == before_session
    assert all((project / rel).read_bytes() == data for rel, data in before.items())
    new_files = {p.relative_to(project) for p in project.rglob("*") if p.is_file()} - before.keys()
    assert new_files == {generic.relative_to(project), targeted.relative_to(project)}


def test_upload_does_not_repair_unrelated_project_layout(upload_project):
    workroot, session, project = upload_project
    (project / "README.md").unlink()
    (project / "runs").rmdir()
    sessions.save_upload(workroot, session, "data.csv", b"data")
    assert not (project / "README.md").exists()
    assert not (project / "runs").exists()
