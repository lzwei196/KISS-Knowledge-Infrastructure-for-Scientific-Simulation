"""KI file tools: one folder per listing, find by name, real names on a miss.

Brought over from the GeoForge web agent (2026-11-05). A small model looped on the
old tools: it asked 123 times for a folder that did not exist and guessed 21 file
names. Shaped like Gemini CLI / Qwen Code: one folder at a time, a name pattern,
hidden and backup files left out but counted, and the real names when a folder
or file does not exist.
"""
from __future__ import annotations

import os
import sys

import pytest

from kiss_cli import api as A
from kiss_cli import paths
from kiss_cli.catalog import KI


def _fake_ki(tmp_path):
    k = tmp_path / "KI"
    for rel in ("SKILL.md", "dag.yaml", "zeta.txt", "SKILL.md.bak.2026", "x.py.orig", ".kdt_state.yaml",
                "docs/s4_genotype_config_skill.md", "docs/s2_weather_prep_skill.md",
                "tools/s2_weather_prep/validate_weather_file.py", "tools/__pycache__/a.cpython-312.pyc",
                ".kdt_runs/r1/log.txt", ".kdt_snapshots/s1/docs/s2_weather_prep_skill.md"):
        (k / rel).parent.mkdir(parents=True, exist_ok=True)
        (k / rel).write_text(rel)
    return k.resolve()


def test_ki_list_one_folder_hides_backups_and_counts_them(tmp_path):
    k = _fake_ki(tmp_path)
    lines = A._ki_list_folder(k, k).splitlines()
    assert lines[1:3] == ["SKILL.md", "dag.yaml"]                      # key files first
    assert "docs/  (2 files)" in lines and "tools/  (1 file)" in lines   # pycache not counted
    assert not any(".bak" in l or ".orig" in l or l.startswith(".") for l in lines[:-1])
    assert lines[-1].startswith("(5 hidden, cache or backup entries not shown")
    assert "docs/s4_genotype_config_skill.md" not in lines              # one level only
    sub = A._ki_list_folder(k / ".kdt_runs", k)                          # a hidden folder by name
    assert ".kdt_runs/r1/  (1 file)" in sub


def test_ki_find_by_pattern_and_plain_words(tmp_path):
    k = _fake_ki(tmp_path)
    (k / ".kdt_snapshots/s1/tools").mkdir(parents=True)
    (k / ".kdt_snapshots/s1/tools/old.py").write_text("x")
    assert A._ki_find("docs/s4_*", k, k).splitlines()[1:] == ["docs/s4_genotype_config_skill.md"]
    w = A._ki_find("WEATHER", k, k)                                     # plain word, any case
    assert "docs/s2_weather_prep_skill.md" in w and "tools/s2_weather_prep/validate_weather_file.py" in w
    assert ".kdt_snapshots" not in w                                    # hidden trees not searched
    assert A._ki_find("genotype skill", k, k).splitlines()[1:] == ["docs/s4_genotype_config_skill.md"]
    for p in ("**/*.py", "*.py", ".py"):                                # no snapshot copies
        assert A._ki_find(p, k, k).splitlines()[1:] == ["tools/s2_weather_prep/validate_weather_file.py"], p
    assert "SKILL.md.bak.2026" in A._ki_find("SKILL.md.bak*", k, k)    # asked for by name
    assert ".kdt_snapshots/s1/tools/old.py" in A._ki_find(".kdt_snapshots/**", k, k)
    assert A._ki_find("docs/", k, k).splitlines()[1:] == [               # trailing slash
        "docs/s2_weather_prep_skill.md", "docs/s4_genotype_config_skill.md"]
    assert "tools/s2_weather_prep/validate_weather_file.py" in A._ki_find("tools/s2_weather_prep", k, k)
    assert "validate_weather_file.py" in A._ki_find("s2_weather_prep/*.py", k / "tools", k)  # from subdir
    for p in ("[a-Z]", "[z-a]*", "[!]x]", "[[]x"):                       # no crash, literal
        assert A._ki_find(p, k, k).startswith("No files match")
    (k / "tools/s2_weather_prep_old").mkdir(); (k / "tools/s2_weather_prep_old/n.py").write_text("x")
    assert "s2_weather_prep_old" not in A._ki_find("tools/s2_weather_prep", k, k)   # a folder = that folder
    assert "tools/s2_weather_prep_old/n.py" in A._ki_find("tools/s2_w", k, k)       # else a name start
    assert A._ki_find("*/*.py", k / "tools", k).splitlines()[1:] == [               # one depth under subdir
        "tools/s2_weather_prep/validate_weather_file.py", "tools/s2_weather_prep_old/n.py"]
    assert "folders with a similar name: tools/s2_weather_prep/" in A._ki_find("s2_forcing", k, k)
    assert "'WEATHER'" in A._ki_find("WEATHER", k, k)                                 # shown as typed
    none = A._ki_find("tools/s2_forcing", k, k)
    assert none.startswith("No files match") and "folders in tools/: tools/s2_weather_prep/" in none
    assert "list it with list_ki_files(subdir=\"docs\")" in A._ki_find("docs", k, k)
    assert A._ki_find("*:*", k, k).startswith("No files match")                       # not "absolute"
    assert A._ki_find("C:N", k, k).startswith("No files match")                       # not a drive
    assert "SKILL.md.bak.2026" in A._ki_find(".bak", k, k)                            # hidden types
    assert "tools/__pycache__/a.cpython-312.pyc" in A._ki_find(".pyc", k, k)
    assert A._ki_find("state", k, k).splitlines() == [                                # retry hidden
        "No visible file matches 'state'; these hidden, cache or backup files do:", ".kdt_state.yaml"]
    assert A._ki_find("Tools/S2_weather_prep", k, k).splitlines()[1:] == [          # any case
        "tools/s2_weather_prep/validate_weather_file.py"]
    assert A._ki_find("tools\\s2_weather_prep\\*.py", k, k).splitlines()[1:] == [   # Windows separators
        "tools/s2_weather_prep/validate_weather_file.py"]
    (k / "docs/recipe.bake.md").write_text("x")
    assert "recipe.bake" not in A._ki_find(".bak", k, k)                              # .bake is no backup
    d2 = A._ki_missing_file("docs.md", k / "docs.md", k)
    assert "Did you mean" not in d2, d2                                               # not every docs/ file
    assert "validate_weather_file.py" in A._ki_find("tools/s2_weather_prep", k / "tools/s2_weather_prep", k)
    assert "Close file names" not in A._ki_find("docs", k, k)
    for bad in ("../x", "/etc/*", "docs/../../x", "C:/x", "C:\\x", "", "/", "./"):
        with pytest.raises(A.ToolError):
            A._ki_find(bad, k, k)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need extra rights on Windows")
def test_ki_folder_link_outside_is_not_counted(tmp_path):
    k = _fake_ki(tmp_path)
    outside = tmp_path / "outside"; outside.mkdir(); (outside / "secret.txt").write_text("x")
    (k / "linkdir").symlink_to(outside, target_is_directory=True)
    (k / "loop").symlink_to(k / "loop")                                              # a link loop
    top = A._ki_list_folder(k, k)
    assert "linkdir/  (folder link)" in top and "\nloop\n" in top + "\n"
    assert "A folder has that name" not in A._ki_find("linkdir", k, k)               # links are not folders
    assert A._ki_find("secret", k, k).startswith("No files match")                   # never walked into


def test_ki_missing_folder_and_file_name_the_real_ones(tmp_path):
    k = _fake_ki(tmp_path)
    m = A._ki_missing_folder("tools/s2_forcing", k / "tools/s2_forcing", k)
    assert m.startswith("no such folder in this KI: tools/s2_forcing")
    assert "folders in tools/: tools/s2_weather_prep/" in m and "__pycache__" not in m
    f = A._ki_missing_file("docs/s4_genotype.md", k / "docs/s4_genotype.md", k)
    assert "Did you mean: docs/s4_genotype_config_skill.md" in f
    assert "is a folder" in A._ki_missing_file("docs", k / "docs", k)
    assert A._ki_missing_folder("x", k / "x", k).count("similar") == 0                # no 1-letter hints
    assert "Did you mean: docs/s4_genotype_config_skill.md" in A._ki_missing_file(
        "docs/genotype.md", k / "docs/genotype.md", k)
    (k / "tools/s2_weather_prep/calc_tav.py").write_text("x")
    d = A._ki_missing_file("tools/s2_weather_prep/validate_weather.py",
                           k / "tools/s2_weather_prep/validate_weather.py", k)
    assert "Did you mean: tools/s2_weather_prep/validate_weather_file.py ?" in d and "calc_tav" not in d
    g = A._ki_missing_file("tools/s2_forcing/x.py", k / "tools/s2_forcing/x.py", k)   # folder missing too
    assert "no such folder in this KI: tools/s2_forcing" in g and "tools/s2_weather_prep/" in g


def test_ki_file_tools_through_execute_tool(tmp_path):
    """The tools as the agent calls them: list, a wrong folder, a pattern, a wrong name, an escape."""
    k = _fake_ki(tmp_path)
    ki, cfg = KI("M", k), paths.KissConfig.default(tmp_path / "project")

    def call(name, args):
        return A.execute_tool(name, args, ki, cfg)

    top = call("list_ki_files", {})
    assert top.splitlines()[1] == "SKILL.md" and "docs/  (2 files)" in top
    assert "hidden, cache or backup entries not shown" in top
    assert "docs/s4_genotype_config_skill.md" in call("list_ki_files", {"subdir": "docs"})
    assert "docs/s4_genotype_config_skill.md" in call("list_ki_files", {"subdir": "docs\\"})  # Windows slash
    assert "docs/s4_genotype_config_skill.md" in call("list_ki_files", {"pattern": "docs/s4_*"})
    with pytest.raises(A.ToolError, match="tools/s2_weather_prep/"):
        call("list_ki_files", {"subdir": "tools/s2_forcing"})
    with pytest.raises(A.ToolError, match="is a file, not a folder"):
        call("list_ki_files", {"subdir": "SKILL.md"})
    with pytest.raises(A.ToolError, match="Did you mean: docs/s4_genotype_config_skill.md"):
        call("read_ki_file", {"path": "docs/s4_genotype.md"})
    with pytest.raises(A.ToolError, match="path is empty"):
        call("read_ki_file", {"path": ""})
    with pytest.raises(A.ToolError, match="escapes"):
        call("list_ki_files", {"subdir": "../"})
    with pytest.raises(A.ToolError, match="escapes"):
        call("read_ki_file", {"path": "../outside.txt"})
    for bad in ({"path": "a\x00b"},):                                                # never a crash
        with pytest.raises(A.ToolError):
            call("read_ki_file", bad)
    with pytest.raises(A.ToolError):
        call("list_ki_files", {"subdir": "a\x00b"})
    assert "No files match" in call("list_ki_files", {"pattern": "[a-Z]*"})
    assert "SKILL.md.bak.2026" in call("read_ki_file", {"path": "SKILL.md.bak.2026"})   # still readable by name
    page = call("read_ki_file", {"path": "docs/s4_genotype_config_skill.md"})          # paged reading kept
    assert "docs/s4_genotype_config_skill.md" in page


def test_list_ki_files_schema_offers_pattern():
    schema = next(t for t in A.tool_schemas(None) if t["name"] == "list_ki_files")
    props = schema["input_schema"]["properties"]
    assert {"subdir", "pattern", "ki"} <= set(props)
    assert "one folder" in schema["description"].lower()
