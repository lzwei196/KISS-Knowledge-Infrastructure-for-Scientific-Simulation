"""A repair must be repeatable and must refuse drift before editing a checkout."""
import importlib.util
from pathlib import Path

import pytest


PATH = Path(__file__).resolve().parents[2] / "models/VIC/installer/windows/patch_vic_stdio.py"
SPEC = importlib.util.spec_from_file_location("vic_stdio_patch", PATH)
patcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(patcher)


def _checkout(root, newline="\n"):
    originals = {}
    for relative, edits in patcher.PATCHES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        original = "\n".join(old for old, _new, count in edits for _ in range(count))
        contents = ("/* upstream context */\n" + original + "\n/* end */\n").replace("\n", newline).encode()
        path.write_bytes(contents)
        originals[path] = contents
    return originals


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_patch_is_repeatable_and_preserves_line_endings(tmp_path, newline):
    originals = _checkout(tmp_path, newline)
    untouched = tmp_path / "scientific_model.c"
    untouched.write_bytes(b"untouched model physics\r\n")
    first = patcher.apply(tmp_path)
    after = {path: path.read_bytes() for path in originals}
    second = patcher.apply(tmp_path)
    assert all(row["status"] == "patched" for row in first["files"])
    assert all(row["status"] == "already_patched" for row in second["files"])
    assert {path: path.read_bytes() for path in originals} == after
    if newline == "\r\n":
        assert all(b"\n" not in data.replace(b"\r\n", b"") for data in after.values())
    assert untouched.read_bytes() == b"untouched model physics\r\n"


def test_unknown_later_source_does_not_partially_patch_earlier_files(tmp_path):
    originals = _checkout(tmp_path)
    last = tmp_path / patcher.PATCHES[-1][0]
    last.write_text("upstream code changed\n", encoding="utf-8")
    originals[last] = last.read_bytes()
    with pytest.raises(ValueError, match="unrecognized upstream"):
        patcher.apply(tmp_path)
    assert {path: path.read_bytes() for path in originals} == originals


def test_check_reports_exact_proposed_hashes_without_editing(tmp_path):
    originals = _checkout(tmp_path)
    checked = patcher.apply(tmp_path, check_only=True)
    assert {path: path.read_bytes() for path in originals} == originals
    applied = patcher.apply(tmp_path)
    assert [row["after_sha256"] for row in checked["files"]] == [row["after_sha256"] for row in applied["files"]]


def test_mixed_original_and_patched_blocks_refuse_without_editing(tmp_path):
    _checkout(tmp_path)
    patcher.apply(tmp_path)
    relative, edits = patcher.PATCHES[0]
    target = tmp_path / relative
    target.write_text(target.read_text() + edits[0][0] + "\n", encoding="utf-8")
    before = target.read_bytes()
    with pytest.raises(ValueError, match="unrecognized upstream"):
        patcher.apply(tmp_path)
    assert target.read_bytes() == before
