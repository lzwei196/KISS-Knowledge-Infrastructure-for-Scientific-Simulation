"""Archive links retain relative semantics on native Windows filesystems."""
import os
from pathlib import Path
import stat
import zipfile

import pytest

from kiss_cli import ki_updates, ki_verification


def archive_with_link(path, target):
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("repo/models/Demo/SKILL.md", "# Demo\n")
        bundle.writestr("repo/models/Demo/s1_grid/probe.txt", "canonical content\n")
        alias = zipfile.ZipInfo("repo/models/Demo/tools/alias")
        alias.create_system = 3
        alias.external_attr = (stat.S_IFLNK | 0o777) << 16
        bundle.writestr(alias, target)


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_UPDATE_HOME", str(tmp_path / "update-state"))
    return ki_updates.UpdateManager(tmp_path / "current", lambda _root: None)


@pytest.mark.parametrize("directory", [False, True], ids=["file-alias", "directory-alias"])
def test_relative_posix_archive_link_traverses_native_target(manager, tmp_path, directory):
    archive = tmp_path / "incoming.zip"
    destination = tmp_path / "extracted"
    raw_target = "../s1_grid" if directory else "../s1_grid/probe.txt"
    archive_with_link(archive, raw_target)
    try:
        manager._extract(archive, destination)
    except OSError as error:
        if os.name == "nt" and getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows test host lacks symbolic-link creation privilege")
        raise
    ki = destination / "models/Demo"
    alias = ki / "tools/alias"
    assert alias.is_symlink() and alias.exists()
    assert alias.is_dir() is directory
    linked_file = alias / "probe.txt" if directory else alias
    assert linked_file.read_text(encoding="utf-8") == "canonical content\n"
    assert os.readlink(alias) == str(Path(raw_target))
    assert alias.resolve().is_relative_to(ki.resolve())
    # The shared tree contract binds this internal alias without expanding it.
    # A content identity is not an authoring/publication acceptance receipt.
    assert ki_verification.content_digest(ki) is not None


@pytest.mark.parametrize("target,reason", [
    ("/private/author/tools", "absolute symbolic link"),
    ("../../../../outside", "escapes the snapshot"),
])
def test_native_spelling_does_not_relax_archive_escape_checks(manager, tmp_path, target, reason):
    archive = tmp_path / "incoming.zip"
    destination = tmp_path / "extracted"
    outside = tmp_path / "outside"
    outside.write_text("untouched", encoding="utf-8")
    archive_with_link(archive, target)
    with pytest.raises(RuntimeError, match=reason):
        manager._extract(archive, destination)
    assert outside.read_text(encoding="utf-8") == "untouched"
    assert not (destination / "models/Demo/tools/alias").is_symlink()
