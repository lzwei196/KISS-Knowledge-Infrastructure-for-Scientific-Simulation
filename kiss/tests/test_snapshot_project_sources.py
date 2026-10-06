"""Fresh immutable-library projects cannot inherit retired installed KI files."""
from pathlib import Path

import pytest

from kiss_cli import gui, ki_updates, paths, project_paths
from kiss_cli.catalog import KI


def fresh_project(tmp_path, *, snapshot=True):
    library = tmp_path / "library"
    source = library / "models" / "SHAW"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Updated SHAW\n", encoding="utf-8")
    if snapshot:
        (library / ki_updates.SNAPSHOT_MANIFEST).write_text("{}", encoding="utf-8")
    shared = paths.KissConfig.default(tmp_path / "installed")
    shared_live = shared.root / "ki"
    shared_live.mkdir(parents=True)
    project = tmp_path / "project"
    cfg = project_paths.model_config(project, "SHAW", shared)
    handler = object.__new__(gui.Handler)
    handler.library_root = library
    handler._config = lambda _ki: shared
    return handler, KI("SHAW", source), project, cfg, shared, shared_live


@pytest.mark.parametrize("retired", [
    "tools/run_reference_case.py",
    "s6_execution/tools/removed_runner.py",
    "docs/removed-guidance.md",
    "test_cases/retired/inputs/Trial.303.inp",
    "test_cases/trial/old_expected.json",
])
def test_snapshot_does_not_resurrect_any_old_shared_ki_file(tmp_path, retired):
    handler, ki, project, cfg, _shared, shared_live = fresh_project(tmp_path)
    stale = shared_live / retired
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"old installed KI content\r\n")
    # The current case is copied exactly, without old supplemental files.
    current = ki.root / "test_cases/trial/run_reference.py"
    current.parent.mkdir(parents=True)
    current.write_bytes(b'# current CLI supports --keep only\n')
    source_bytes = current.read_bytes()

    live, _ = handler._session_workspace(project, ki, cfg=cfg)

    assert not (live.root / retired).exists()
    assert (live.root / "test_cases/trial/run_reference.py").read_bytes() == source_bytes
    assert stale.read_bytes() == b"old installed KI content\r\n"
    assert current.read_bytes() == source_bytes


def test_snapshot_preserves_external_binary_binding_and_installed_bytes(tmp_path):
    handler, ki, project, cfg, shared, shared_live = fresh_project(tmp_path)
    binary = shared.roles["binaries"] / "shaw303.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"MZ existing managed engine")
    old_asset = shared_live / "reference/licensed.exe"
    old_asset.parent.mkdir()
    old_asset.write_bytes(b"MZ old KI asset")

    live, resolved = handler._session_workspace(project, ki, cfg=cfg)

    assert resolved.roles["binaries"] == shared.roles["binaries"]
    assert binary.read_bytes() == b"MZ existing managed engine"
    assert not (live.root / "reference/licensed.exe").exists()
    saved = paths.KissConfig.load(project / "models/SHAW")
    assert saved.roles["binaries"] == shared.roles["binaries"]


def test_legacy_bundled_library_keeps_existing_asset_overlay_contract(tmp_path):
    handler, ki, project, cfg, _shared, shared_live = fresh_project(tmp_path, snapshot=False)
    asset = shared_live / "reference/licensed.exe"
    asset.parent.mkdir()
    asset.write_bytes(b"MZ licensed asset")

    live, _ = handler._session_workspace(project, ki, cfg=cfg)

    assert (live.root / "reference/licensed.exe").read_bytes() == asset.read_bytes()
