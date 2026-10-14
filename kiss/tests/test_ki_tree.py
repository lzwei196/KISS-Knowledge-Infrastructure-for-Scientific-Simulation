"""Physical KI identity preserves files once and binds safe aliases explicitly."""
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from kiss_cli import kdtstudio, ki_tree


def link(path, target, *, directory=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.symlink_to(target, target_is_directory=directory)
    except OSError as error:
        if os.name == "nt" and getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows host lacks symbolic-link creation privilege")
        raise


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "Demo"
    (root / "canonical").mkdir(parents=True)
    (root / "canonical/probe.py").write_bytes(b"print('safe')\n")
    (root / "SKILL.md").write_bytes(b"# Demo\n")
    return root


def legacy_digest(root):
    value = hashlib.sha256()
    files = sorted((p for p in root.rglob("*") if p.is_file()),
                   key=lambda p: str(p.relative_to(root)))
    for path in files:
        value.update(path.relative_to(root).as_posix().encode("utf-8"))
        value.update(b"\0")
        value.update(path.read_bytes())
    signature = [[p.relative_to(root).as_posix(), p.stat().st_size,
                  p.stat().st_mtime_ns] for p in files]
    return value.hexdigest(), signature


def test_link_free_digest_and_signature_remain_exactly_compatible(tree):
    (tree / "empty").mkdir()
    (tree / "canonical/例子.txt").write_text("中文\n", encoding="utf-8")
    (tree / "canonical-other").write_bytes(b"sorting boundary")
    expected, signature = legacy_digest(tree)
    assert ki_tree.digest(tree) == kdtstudio.tree_digest(tree) == expected
    assert ki_tree.signature(tree) == kdtstudio.tree_signature(tree) == signature


def test_empty_tree_keeps_legacy_digest(tmp_path):
    assert ki_tree.digest(tmp_path) == hashlib.sha256(b"").hexdigest()


@pytest.mark.parametrize("directory", [False, True])
def test_internal_alias_is_separate_inventory_entry_and_not_expanded(tree, directory):
    target = "../canonical" if directory else "../canonical/probe.py"
    link(tree / "tools/alias", str(Path(target)), directory=directory)
    inventory = ki_tree.scan(tree)
    entries = {row.relative: row for row in inventory.entries}
    assert entries["tools/alias"].kind == "link"
    assert entries["tools/alias"].target == target[3:]
    assert sum(row.kind == "file" for row in entries.values()) == 2
    assert not any(path.startswith("tools/alias/") for path in entries)
    assert ki_tree.digest(tree) and kdtstudio.tree_digest(tree) == ki_tree.digest(tree)
    kdtstudio._validate_candidate_tree(tree)


def test_equivalent_native_target_spellings_have_the_same_identity(tree):
    alias = tree / "tools/alias"
    link(alias, str(Path("../canonical")), directory=True)
    first = ki_tree.digest(tree)
    alias.unlink()
    native = os.sep.join(["..", "canonical", "."])
    link(alias, native, directory=True)
    assert first is not None and ki_tree.digest(tree) == first


def test_non_native_spelling_cannot_hide_a_physically_broken_link(tree):
    alias = tree / "tools/alias"
    raw = "../canonical" if os.name == "nt" else "..\\canonical"
    link(alias, raw, directory=True)
    if alias.exists():
        assert ki_tree.digest(tree)
    else:
        with pytest.raises(ki_tree.TreeError, match="not traversable"):
            ki_tree.scan(tree)
        assert ki_tree.digest(tree) is None


def test_alias_target_and_canonical_bytes_both_affect_digest(tree):
    (tree / "other").mkdir()
    (tree / "other/probe.py").write_bytes((tree / "canonical/probe.py").read_bytes())
    alias = tree / "tools/alias"
    link(alias, str(Path("../canonical")), directory=True)
    first = ki_tree.digest(tree)
    alias.unlink()
    link(alias, str(Path("../other")), directory=True)
    second = ki_tree.digest(tree)
    (tree / "other/probe.py").write_bytes(b"changed\n")
    third = ki_tree.digest(tree)
    assert None not in (first, second, third)
    assert len({first, second, third}) == 3


@pytest.mark.parametrize("raw", ["/outside", "C:/outside", "C:outside",
                                 "\\outside", "\\\\host\\share\\outside",
                                 "//host/share/outside", "../../outside"])
def test_absolute_drive_unc_and_escape_targets_fail_closed(tree, monkeypatch, raw):
    alias = tree / "tools/alias"
    link(alias, str(Path("../canonical")), directory=True)
    real = os.readlink
    monkeypatch.setattr(os, "readlink", lambda path, *a, **kw:
                        raw if Path(path) == alias else real(path, *a, **kw))
    with pytest.raises(ki_tree.TreeError):
        ki_tree.scan(tree)
    assert ki_tree.digest(tree) is None
    assert ki_tree.signature(tree) is None


@pytest.mark.parametrize("target", ["../missing", ".", "..", "alias"])
def test_dangling_self_and_ancestor_aliases_fail_closed(tree, target):
    link(tree / "tools/alias", str(Path(target)), directory=True)
    with pytest.raises(ki_tree.TreeError):
        ki_tree.scan(tree)
    assert ki_tree.digest(tree) is None


@pytest.mark.parametrize("target", ["first", "first/probe.py", "first/../canonical"])
def test_alias_chains_including_cancelled_prefixes_are_rejected(tree, target):
    link(tree / "first", "canonical", directory=True)
    link(tree / "second", str(Path(target)), directory=target != "first/probe.py")
    with pytest.raises(ki_tree.TreeError, match="chains"):
        ki_tree.scan(tree)


@pytest.mark.parametrize("target", ["missing/../canonical", "SKILL.md/../canonical",
                                   "canonical/probe.py/."])
def test_nonexistent_and_non_directory_prefixes_cannot_be_normalized_away(tree, target):
    link(tree / "alias", str(Path(target)), directory=True)
    # Path removes a trailing '/.' on some hosts, so preserve that spelling.
    if target.endswith("/."):
        (tree / "alias").unlink()
        link(tree / "alias", target, directory=True)
    with pytest.raises(ki_tree.TreeError):
        ki_tree.scan(tree)


def test_sibling_directory_alias_cycle_is_rejected(tree):
    (tree / "other").mkdir()
    link(tree / "canonical/back", str(Path("../other")), directory=True)
    link(tree / "other/back", str(Path("../canonical")), directory=True)
    with pytest.raises(ki_tree.TreeError, match="cycle"):
        ki_tree.scan(tree)


def test_alias_cycle_is_rejected(tree):
    link(tree / "a", "b")
    link(tree / "b", "a")
    with pytest.raises(ki_tree.TreeError, match="chains"):
        ki_tree.scan(tree)


def test_root_link_is_rejected(tree, tmp_path):
    alias = tmp_path / "alias"
    link(alias, tree, directory=True)
    with pytest.raises(ki_tree.TreeError, match="root"):
        ki_tree.scan(alias)
    assert kdtstudio.tree_digest(alias) is None


def test_non_symlink_reparse_point_is_rejected(tree, monkeypatch):
    real = os.scandir

    class Child:
        name = "junction"
        def stat(self, *, follow_symlinks):
            assert follow_symlinks is False
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400,
                                   st_mtime_ns=0)

    class Children:
        def __enter__(self):
            return iter([Child()])
        def __exit__(self, *args):
            return False

    monkeypatch.setattr(os, "scandir", lambda path: Children() if Path(path) == tree else real(path))
    with pytest.raises(ki_tree.TreeError, match="reparse"):
        ki_tree.scan(tree)


@pytest.mark.skipif(os.name == "nt", reason="POSIX special file fixture")
def test_unusual_file_type_is_rejected(tree):
    os.mkfifo(tree / "pipe")
    with pytest.raises(ki_tree.TreeError, match="file type"):
        ki_tree.scan(tree)


def test_limits_count_canonical_entries_and_bytes_only(tree):
    link(tree / "alias", "canonical", directory=True)
    byte_count = len((tree / "SKILL.md").read_bytes()) + len((tree / "canonical/probe.py").read_bytes())
    assert ki_tree.digest(tree, max_entries=4, max_bytes=byte_count)
    with pytest.raises(ki_tree.TreeError, match="entries"):
        ki_tree.scan(tree, max_entries=3)
    with pytest.raises(ki_tree.TreeError, match="bytes"):
        ki_tree.scan(tree, max_bytes=byte_count - 1)


def test_missing_or_regular_file_root_has_no_identity(tmp_path):
    assert ki_tree.digest(tmp_path / "missing") is None
    file = tmp_path / "file"
    file.write_bytes(b"no directory")
    assert ki_tree.digest(file) is None


def test_retarget_during_hashing_fails_closed(tree, monkeypatch):
    (tree / "other").mkdir()
    alias = tree / "alias"
    link(alias, "canonical", directory=True)
    real_scan = ki_tree.scan
    calls = 0
    def mutate_between_scans(root, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            alias.unlink()
            link(alias, "other", directory=True)
        return real_scan(root, **kwargs)
    monkeypatch.setattr(ki_tree, "scan", mutate_between_scans)
    assert ki_tree.digest(tree) is None


def test_directory_timestamp_settling_does_not_change_content_identity(tree, monkeypatch):
    expected = ki_tree.digest(tree)
    real_scan = ki_tree.scan
    calls = 0
    def settled_timestamp(root, **kwargs):
        nonlocal calls
        calls += 1
        inventory = real_scan(root, **kwargs)
        if calls == 2:
            return replace(inventory, entries=tuple(
                replace(row, mtime_ns=row.mtime_ns + 1) if row.kind == "directory" else row
                for row in inventory.entries))
        return inventory
    monkeypatch.setattr(ki_tree, "scan", settled_timestamp)
    assert ki_tree.digest(tree) == expected


def test_physically_different_target_cannot_share_logical_alias_identity(tree, monkeypatch):
    alias = tree / "alias"
    link(alias, "SKILL.md")
    other = tree / "other.txt"
    other.write_bytes((tree / "SKILL.md").read_bytes())
    real_stat = Path.stat
    def different_target(path, *args, **kwargs):
        if path == alias and kwargs.get("follow_symlinks", True):
            return real_stat(other, *args, **kwargs)
        return real_stat(path, *args, **kwargs)
    monkeypatch.setattr(Path, "stat", different_target)
    with pytest.raises(ki_tree.TreeError, match="canonical target"):
        ki_tree.scan(tree)
    assert ki_tree.digest(tree) is None


def test_growing_file_cannot_read_beyond_byte_budget(tree, monkeypatch):
    limit = sum(row.size for row in ki_tree.scan(tree).entries)
    real_open = Path.open
    def grow_before_open(path, *args, **kwargs):
        if path == tree / "SKILL.md" and args == ("rb",):
            with real_open(path, "ab") as handle:
                handle.write(b"more than the limit")
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", grow_before_open)
    assert ki_tree.digest(tree, max_bytes=limit) is None


def test_link_signature_records_the_target(tree):
    link(tree / "alias", "canonical", directory=True)
    rows = {row[0]: row for row in ki_tree.signature(tree)}
    assert rows["alias"][1:3] == ["link", "canonical"]

