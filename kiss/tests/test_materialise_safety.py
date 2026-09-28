"""KI refresh rejects existing aliases before touching generated/user files."""
import pytest

from kiss_cli import gui, paths, port
from kiss_cli.catalog import KI


@pytest.mark.parametrize("operation", ["materialise", "assets", "desktop"])
@pytest.mark.parametrize("link_scope", ["root", "directory", "file", "dangling"])
def test_refresh_rejects_destination_links_before_any_write(tmp_path, operation, link_scope):
    project = (tmp_path / "project").resolve()
    source = tmp_path / "source"
    source.mkdir()
    (source / "00-first.txt").write_text("new generated file")
    (source / "SKILL.md").write_text("# New source\n")
    (source / "data").mkdir()
    (source / "data" / "last.txt").write_text("new asset")
    outside = tmp_path / "unrelated-user-files"
    outside.mkdir()
    sentinel = outside / "SKILL.md"
    sentinel.write_text("Original user document\n")
    destination = project / "models" / "M" / "ki"
    destination.parent.mkdir(parents=True)
    if link_scope == "root":
        destination.symlink_to(outside, target_is_directory=True)
        link = destination
    else:
        destination.mkdir()
        if link_scope == "directory":
            link = destination / "data"
            link.symlink_to(outside, target_is_directory=True)
        elif link_scope == "file":
            link = destination / "SKILL.md"
            link.symlink_to(sentinel)
        else:
            link = destination / "SKILL.md"
            link.symlink_to(outside / "missing-file")
    # The first sorted source must not be copied before a later alias is found.
    assert not (destination / "00-first.txt").exists()
    cfg = paths.KissConfig.default(tmp_path / "installed-M")
    with pytest.raises(ValueError, match="symlink"):
        if operation == "materialise":
            port.materialise(source, destination, cfg)
        elif operation == "assets":
            gui._copy_missing_assets(source, destination)
        else:
            handler = object.__new__(gui.Handler)
            handler._config = lambda ki: cfg
            handler.repo_root = None
            handler._session_workspace(project, KI("M", source))
    assert not (destination / "00-first.txt").exists()
    assert sentinel.read_text() == "Original user document\n"
    assert link.is_symlink()  # fail closed; never remove or repair user links
    assert not (destination.parent / paths.CONFIG_NAME).exists()


def test_refresh_regular_destination_still_copies_and_rewrites(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "SKILL.md").write_text("output=KISSPATH_OUTPUTS/result.nc\n")
    destination = tmp_path / "project" / "models" / "M" / "ki"
    cfg = paths.KissConfig.default(tmp_path / "project")
    result = port.materialise(source, destination, cfg)
    assert result.files_written == 1
    assert (destination / "SKILL.md").read_text() == f"output={cfg.roles['outputs'].as_posix()}/result.nc\n"
