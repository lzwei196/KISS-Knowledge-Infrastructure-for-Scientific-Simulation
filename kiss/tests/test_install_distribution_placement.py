"""Runtime placement retains the distribution proven by the manifest suffix."""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import install
from kiss_cli.manifest import Acquire, Manifest


@pytest.fixture
def case(tmp_path):
    source = tmp_path / "official" / "Demo"
    binary = source / "build/bin/demo.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"MZ harmless fixture, never executed")
    (source / "Data/Genotype").mkdir(parents=True)
    (source / "Data/MODEL.ERR").write_bytes(b"official support messages")
    (source / "Data/Genotype/demo.CUL").write_bytes(b"official cultivar")
    workspace = tmp_path / "workspace"
    cfg = SimpleNamespace(root=workspace, roles={"binaries": workspace / "binaries"})
    manifest = Manifest(model="Demo", install_dir="Demo",
                        acquire=Acquire(strategy="build", produces="build/bin/demo.exe"))
    return SimpleNamespace(source=source, binary=binary, cfg=cfg, man=manifest,
                           prefix=workspace / "binaries/Demo")


def test_nested_executable_keeps_sibling_data_distribution(case):
    binary, notes = install.place_agent_install(case.man, case.binary, case.cfg)
    assert binary == case.prefix / "build/bin/demo.exe"
    assert (case.prefix / "Data/MODEL.ERR").read_bytes() == b"official support messages"
    assert (case.prefix / "Data/Genotype/demo.CUL").read_bytes() == b"official cultivar"
    assert any("distribution" in note for note in notes)


def test_previous_partial_install_with_binary_is_completed_without_overwrite(case):
    placed = case.prefix / "build/bin/demo.exe"
    placed.parent.mkdir(parents=True)
    placed.write_bytes(case.binary.read_bytes())
    before = placed.stat().st_mtime_ns
    binary, notes = install.place_agent_install(case.man, case.binary, case.cfg)
    assert binary == placed
    assert (case.prefix / "Data/MODEL.ERR").read_bytes() == b"official support messages"
    assert placed.stat().st_mtime_ns == before
    assert notes


def test_conflicting_existing_file_stops_before_adding_any_missing_files(case):
    placed = case.prefix / "build/bin/demo.exe"
    placed.parent.mkdir(parents=True)
    placed.write_bytes(case.binary.read_bytes())
    conflict = case.prefix / "Data/Genotype/demo.CUL"
    conflict.parent.mkdir(parents=True)
    conflict.write_bytes(b"different local cultivar must survive")
    with pytest.raises(ValueError, match="conflict"):
        install.place_agent_install(case.man, case.binary, case.cfg)
    assert conflict.read_bytes() == b"different local cultivar must survive"
    assert not (case.prefix / "Data/MODEL.ERR").exists()


def test_source_already_at_canonical_root_is_unchanged(case):
    case.cfg.roles["binaries"] = case.source.parent
    result, notes = install.place_agent_install(case.man, case.binary, case.cfg)
    assert result == case.binary
    assert not notes


@pytest.mark.parametrize("relation", ["destination_inside_source", "source_inside_destination"])
def test_overlapping_distribution_roots_are_rejected_before_mutation(case, relation):
    if relation == "destination_inside_source":
        case.cfg.roles["binaries"] = case.source / "nested"
    else:
        case.cfg.roles["binaries"] = case.source.parent.parent
        case.man.install_dir = "official"
    with pytest.raises(ValueError, match="overlap"):
        install.place_agent_install(case.man, case.binary, case.cfg)
    assert not (case.source / "nested").exists()


@pytest.mark.parametrize("produces", ["../demo.exe", "build/../../demo.exe", "\\demo.exe", "C:demo.exe"])
def test_escaping_manifest_product_is_rejected(case, produces):
    case.man.acquire.produces = produces
    with pytest.raises(ValueError, match="relative"):
        install.place_agent_install(case.man, case.binary, case.cfg)
    assert not case.prefix.exists()


def test_home_root_cannot_be_inferred_as_a_distribution(case, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: case.source))
    with pytest.raises(ValueError, match="home"):
        install.place_agent_install(case.man, case.binary, case.cfg)
    assert not case.prefix.exists()


def test_previous_build_subtree_alias_retains_data_and_canonical_binary(case):
    case.prefix.mkdir(parents=True)
    try:
        (case.prefix / "build").symlink_to(case.source / "build", target_is_directory=True)
    except OSError as error:
        if os.name == "nt" and getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows host lacks symlink creation privilege")
        raise
    result, _ = install.place_agent_install(case.man, case.binary, case.cfg)
    assert os.path.samefile(result, case.binary)
    assert os.path.samefile(case.prefix / "build", case.source / "build")
    assert (case.prefix / "Data/MODEL.ERR").read_bytes() == b"official support messages"


def test_no_symlink_privilege_copies_complete_distribution(case, monkeypatch):
    def denied(*args, **kwargs):
        raise OSError(1314, "symlink privilege unavailable")
    monkeypatch.setattr(Path, "symlink_to", denied)
    result, _ = install.place_agent_install(case.man, case.binary, case.cfg)
    assert result.read_bytes() == case.binary.read_bytes()
    assert not case.prefix.is_symlink()
    assert (case.prefix / "Data/MODEL.ERR").read_bytes() == b"official support messages"


def test_missing_mandatory_assets_are_not_invented(case):
    install.place_agent_install(case.man, case.binary, case.cfg)
    assert not (case.prefix / "Data/Genotype/China").exists()
    assert not (case.source / "Data/Genotype/China").exists()


def test_existing_unrelated_directory_alias_is_not_filled(case, tmp_path):
    case.prefix.mkdir(parents=True)
    elsewhere = tmp_path / "unrelated"
    elsewhere.mkdir()
    try:
        (case.prefix / "Data").symlink_to(elsewhere, target_is_directory=True)
    except OSError as error:
        if os.name == "nt" and getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows host lacks symlink creation privilege")
        raise
    with pytest.raises(ValueError, match="conflict"):
        install.place_agent_install(case.man, case.binary, case.cfg)
    assert not list(elsewhere.iterdir())


def test_stop_during_inventory_does_not_create_install(case, monkeypatch):
    import threading
    stopped = threading.Event()
    original = Path.iterdir

    def listing(path):
        for child in original(path):
            if path == case.source:
                stopped.set()
            yield child

    monkeypatch.setattr(Path, "iterdir", listing)
    with install.cancellation_context(stop=stopped.is_set):
        with pytest.raises(install.InstallStopped):
            install.place_agent_install(case.man, case.binary, case.cfg)
    assert not case.prefix.exists()


@pytest.mark.parametrize("operation", ["compare", "copy"])
def test_stop_is_checked_between_distribution_byte_chunks(case, monkeypatch, operation):
    import contextlib
    import threading

    case.binary.write_bytes(b"model bytes" * (1 << 19))
    placed = case.prefix / "build/bin/demo.exe"
    if operation == "compare":
        placed.parent.mkdir(parents=True)
        placed.write_bytes(case.binary.read_bytes())
    stopped = threading.Event()
    original_open = Path.open

    @contextlib.contextmanager
    def stopping_reader(path, *args, **kwargs):
        with original_open(path, *args, **kwargs) as stream:
            class Reader:
                def read(self, size):
                    data = stream.read(size)
                    stopped.set()
                    return data
            yield Reader()

    def selected_open(path, *args, **kwargs):
        if path == case.binary and args and args[0] == "rb":
            return stopping_reader(path, *args, **kwargs)
        return original_open(path, *args, **kwargs)

    def denied(*args, **kwargs):
        raise OSError(1314, "test the copy fallback")

    monkeypatch.setattr(Path, "open", selected_open)
    monkeypatch.setattr(Path, "symlink_to", denied)
    with install.cancellation_context(stop=stopped.is_set):
        with pytest.raises(install.InstallStopped):
            install.place_agent_install(case.man, case.binary, case.cfg)
    assert stopped.is_set()
    if operation == "compare":
        assert placed.stat().st_size == case.binary.stat().st_size
        assert not (case.prefix / "Data").exists()
    else:
        # The interrupted copy owns only this new partial file, which is
        # removed so a retry can complete instead of reporting a conflict.
        assert not placed.exists()
        monkeypatch.setattr(Path, "open", original_open)
        result, _ = install.place_agent_install(case.man, case.binary, case.cfg)
        assert result.read_bytes() == case.binary.read_bytes()


@pytest.mark.parametrize("partial", [False, True])
def test_downloaded_named_package_staged_in_binaries_keeps_its_own_tree(case, partial):
    package = case.cfg.roles["binaries"] / "official-demo"
    binary = package / "bin/demo.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"MZ genuine fixture")
    (package / "lib").mkdir()
    (package / "lib/runtime.data").write_bytes(b"required package data")
    unrelated = package.parent / "other-model"
    unrelated.mkdir()
    (unrelated / "keep.dat").write_bytes(b"unrelated")
    case.man.acquire = Acquire(strategy="download", produces="official-demo/bin/demo.exe")
    if partial:
        (case.prefix / "official-demo").mkdir(parents=True)
    placed, notes = install.place_agent_install(case.man, binary, case.cfg)
    assert placed == case.prefix / "official-demo/bin/demo.exe"
    assert placed.read_bytes() == binary.read_bytes()
    assert (case.prefix / "official-demo/lib/runtime.data").read_bytes() == b"required package data"
    assert not (case.prefix / "other-model").exists()
    assert (unrelated / "keep.dat").read_bytes() == b"unrelated"
    assert notes


def test_build_root_is_not_reinterpreted_as_a_downloaded_package(case):
    binary = case.cfg.roles["binaries"] / "build/bin/demo.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"MZ genuine fixture")
    with pytest.raises(ValueError, match="overlap"):
        install.place_agent_install(case.man, binary, case.cfg)
    assert not case.prefix.exists()


def test_downloaded_package_conflict_is_preserved_before_missing_files(case):
    package = case.cfg.roles["binaries"] / "official-demo"
    binary = package / "bin/demo.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"MZ genuine fixture")
    (package / "lib").mkdir()
    (package / "lib/runtime.data").write_bytes(b"official data")
    conflict = case.prefix / "official-demo/lib/runtime.data"
    conflict.parent.mkdir(parents=True)
    conflict.write_bytes(b"local changes")
    case.man.acquire = Acquire(strategy="download", produces="official-demo/bin/demo.exe")
    with pytest.raises(ValueError, match="conflict"):
        install.place_agent_install(case.man, binary, case.cfg)
    assert conflict.read_bytes() == b"local changes"
    assert not (case.prefix / "official-demo/bin").exists()


def test_downloaded_package_top_level_alias_is_not_a_staging_root(case):
    package = case.cfg.roles["binaries"] / "official-demo"
    package.parent.mkdir(parents=True)
    try:
        package.symlink_to(case.source, target_is_directory=True)
    except OSError as error:
        if os.name == "nt" and getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows host lacks symlink creation privilege")
        raise
    case.man.acquire = Acquire(strategy="download", produces="official-demo/build/bin/demo.exe")
    with pytest.raises(ValueError, match="real directory"):
        install.place_agent_install(case.man, package / "build/bin/demo.exe", case.cfg)
    assert not case.prefix.exists()

