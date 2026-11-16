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
    # paged reading kept (review r1): metadata, line range and the next start line
    (k / "docs/long.md").write_text("".join(f"line {i}\n" for i in range(1, 31)))
    page = call("read_ki_file", {"path": "docs/long.md", "start_line": 11, "line_count": 5})
    assert page.read_metadata["read_path"] == "docs/long.md"
    assert page.read_metadata["read_kind"] == "text" and page.read_metadata["next_start_line"] == 16
    assert page.content.startswith("line 11\n") and "line 16" not in page.content


def test_absolute_and_non_text_arguments_are_refused(tmp_path):
    """Review r1: an absolute folder is refused before any trimming; non-text arguments get a clear error."""
    k = _fake_ki(tmp_path)
    ki, cfg = KI("M", k), paths.KissConfig.default(tmp_path / "project")

    def call(name, args):
        return A.execute_tool(name, args, ki, cfg)

    for sub in ("/tests", "//docs", "\\docs", "C:\\", "C:/docs", "C:docs", "\\\\server\\share\\x", "/"):
        with pytest.raises(A.ToolError, match="absolute paths are not accepted"):
            call("list_ki_files", {"subdir": sub})
        with pytest.raises(A.ToolError, match="absolute paths are not accepted"):
            call("read_ki_file", {"path": sub + "/SKILL.md"})
    with pytest.raises(A.ToolError, match="absolute paths are not accepted"):
        call("list_ki_files", {"pattern": "/docs/*.md"})
    for key, bad in (("subdir", ["docs"]), ("pattern", 5)):
        with pytest.raises(A.ToolError, match=f"{key} must be a string"):
            call("list_ki_files", {key: bad})
    with pytest.raises(A.ToolError, match="path must be a string"):
        call("read_ki_file", {"path": ["SKILL.md"]})


def test_windows_junction_is_never_entered(tmp_path, monkeypatch):
    """Review r1: Python 3.11 (the Windows app) has no os.path.isjunction; the reparse tag decides."""
    k = _fake_ki(tmp_path)
    (k / "jdir").mkdir(); (k / "jdir" / "secret.txt").write_text("x")
    real_lstat = os.lstat
    junction = str(k / "jdir")

    class _Junction:
        def __init__(self, info):
            self.st_mode, self.st_reparse_tag = info.st_mode, A._IO_REPARSE_TAG_MOUNT_POINT

    def lstat(path, *a, **kw):
        info = real_lstat(path, *a, **kw)
        return _Junction(info) if os.fspath(path) == junction else info

    monkeypatch.setattr(A.os, "lstat", lstat)
    monkeypatch.delattr(A.os.path, "isjunction", raising=False)
    top = A._ki_list_folder(k, k)
    assert "jdir/  (folder link)" in top and "secret" not in top
    assert A._ki_find("secret", k, k).startswith("No files match")
    assert "jdir/" not in A._ki_walk(k, k, hidden=False)[1]


def test_glob_matching_cannot_hang_and_matches_the_plain_reading(tmp_path):
    """Review r1: '*a*a*a...b' backtracked for seconds or minutes. The new regex must answer the
    same as the plain translation (checked on many generated cases) and stay fast."""
    import random
    import re
    import time

    def plain(pattern):   # the reviewed web translation, kept here as the reference
        out, i = [], 0
        while i < len(pattern):
            if pattern.startswith("**/", i):
                out.append("(?:.*/)?"); i += 3; continue
            if pattern.startswith("**", i):
                out.append(".*"); i += 2; continue
            c = pattern[i]
            out.append("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c))
            i += 1
        return re.compile("".join(out) + r"\Z", re.IGNORECASE | re.DOTALL)

    rnd = random.Random(7)
    checked = 0
    for _ in range(6000):
        pat = "".join(rnd.choice(["a", "b", "/", "*", "*", "?", "**", "**/", "."]) for _ in range(rnd.randint(1, 8)))
        try:
            fast = A._ki_glob_regex(pat)
        except A.ToolError:
            continue   # too many ** : refused, never slow
        ref = plain(pat)
        for _ in range(12):
            name = "".join(rnd.choice("ab/.\nA") for _ in range(rnd.randint(0, 12)))
            assert bool(fast.match(name)) == bool(ref.match(name)), (pat, name)
            checked += 1
    assert checked > 30000
    assert A._ki_glob_regex("*a**b").match("a\nab")                    # review r2: newline in a name
    for ok in ("**/*.py", "docs/**", ".kdt_runs/**", "**/s2_*/*.csv", "**/docs/**", "*****z"):
        A._ki_glob_regex(ok)                                           # common shapes stay allowed
    for bad in ("**/a/**/b", "*a**/*a**/*b", "**a**a*b", "**/x/**/y/**", "**?**z"):
        with pytest.raises(A.ToolError, match=r"\*\* only once"):
            A._ki_glob_regex(bad)
    with pytest.raises(A.ToolError, match=r"\* at most"):
        A._ki_glob_regex("*a" * 20)


@pytest.mark.skipif(sys.platform == "win32", reason="uses SIGALRM as a hard stop")
def test_glob_worst_cases_are_fast():
    """Review r1/r2: shapes that backtracked for seconds; a hard stop so a hang fails, not blocks."""
    import signal
    import time

    def boom(*_):
        raise TimeoutError("glob match took too long")

    old = signal.signal(signal.SIGALRM, boom)
    signal.alarm(20)
    try:
        long_name = ("a" * 200 + "/") * 15 + "x.txt"
        started = time.monotonic()
        for pat in ("*a" * 15 + "*b", "*****z", "*****.zzz", "**/*a*a*a*a*a*b", "*a*a*a*a*b/**", "*a**/*a*b"):
            rx = A._ki_glob_regex(pat)
            for name in ("a" * 250 + ".txt", long_name, ("ab/" * 80) + "a" * 120):
                for _ in range(20):
                    rx.match(name)
        assert time.monotonic() - started < 5.0
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def test_big_ki_search_and_hints_stay_right(tmp_path, monkeypatch):
    """Review r1: a walk cut off at the file limit missed files in later folders; counting and
    hint lists had no overall limit."""
    k = _fake_ki(tmp_path)
    monkeypatch.setattr(A, "_KI_WALK_CAP", 50)
    (k / "build").mkdir()
    for i in range(80):
        (k / "build" / f"o{i:03d}.obj").write_text("x")
    (k / "tools" / "run_model.py").write_text("x")
    # a path pattern walks only the folder it names, so the big build/ folder cannot hide the file
    assert "tools/run_model.py" in A._ki_find("tools/*.py", k, k)
    assert "only part of the KI" not in A._ki_find("tools/*.py", k, k)
    assert "tools/run_model.py" in A._ki_find("tools/run_model", k, k)
    # a miss looks in the named folder first
    assert "Did you mean: tools/run_model.py" in A._ki_missing_file(
        "tools/run_modl.py", k / "tools/run_modl.py", k)
    # a cut walk says so, without claiming the file is not there
    cut = A._ki_find("zzz_nothing", k, k)
    assert cut.startswith("No files match 'zzz_nothing' in the part of the KI that was searched.")
    assert "only part of the KI was searched (limits: 50 files and folders" in cut
    # counting: one budget for the whole listing; folders past the budget are not counted
    monkeypatch.setattr(A, "_KI_COUNT_BUDGET", 30)
    top = A._ki_list_folder(k, k)
    # "80+" = at least 80: one folder is read in one step, the budget stops before the next one
    assert "build/  (80+ files)" in top and "docs/  (not counted)" in top
    # hint lists are capped
    many = tmp_path / "many"
    for i in range(60):
        (many / f"d{i:02d}").mkdir(parents=True)
    msg = A._ki_missing_folder("nope", many / "nope", many.resolve())
    assert "(20 more)" in msg and len(msg) < 2000


def test_hints_keep_the_ki_they_were_given(tmp_path):
    """Review r1: a hint followed word for word must reach the same KI (ki= kept; intake prefix kept)."""
    k = _fake_ki(tmp_path)
    b = A._KiView(ki="B")
    assert 'list_ki_files(subdir="tools/s2_weather_prep", ki="B")' in A._ki_missing_folder(
        "tools/s2_forcing", k / "tools/s2_forcing", k, b)
    assert 'list_ki_files(pattern="genotype", ki="B")' in A._ki_missing_file(
        "docs/genotype.md", k / "docs/genotype.md", k, b)
    assert 'list_ki_files(subdir="docs", ki="B")' in A._ki_find("docs", k, k, b)
    demo = A._KiView(prefix="Demo/")
    assert "Did you mean: Demo/docs/s4_genotype_config_skill.md" in A._ki_missing_file(
        "Demo/docs/genotype.md", k / "docs/genotype.md", k, demo)
    listing = A._ki_list_folder(k / "docs", k, demo)
    assert "Folder: Demo/docs/" in listing and "Demo/docs/s4_genotype_config_skill.md" in listing
    assert A._ki_find("docs/s4_*", k, k, demo).splitlines()[1:] == ["Demo/docs/s4_genotype_config_skill.md"]


def test_folders_differing_only_in_case_are_both_searched(tmp_path):
    """Review r2: the fixed-folder start must not drop Data/ when data/ also exists."""
    k = (tmp_path / "KI"); (k / "Data").mkdir(parents=True)
    if (k / "data").exists():
        pytest.skip("case-insensitive file system")
    (k / "data").mkdir(); (k / "Data" / "a.csv").write_text("x"); (k / "data" / "b.csv").write_text("x")
    k = k.resolve()
    assert A._ki_find("data/*.csv", k, k).splitlines()[1:] == ["Data/a.csv", "data/b.csv"]
    assert "data/b.csv" in A._ki_find("DATA/b.csv", k, k)


def test_hint_values_are_quoted_and_names_kept_exactly(tmp_path):
    """Review r2: quotes or backslashes in a name, and a KI name with spaces, survive in a hint."""
    k = _fake_ki(tmp_path)
    view = A._KiView(ki=" B ")
    assert view.call("list_ki_files", subdir='my"da\\ta') == 'list_ki_files(subdir="my\\"da\\\\ta", ki=" B ")'
    import json
    args = json.loads("{" + view.call("list_ki_files", subdir='my"da\\ta')[len("list_ki_files("):-1]
                      .replace('subdir=', '"subdir":').replace(', ki=', ', "ki":') + "}")
    assert args == {"subdir": 'my"da\\ta', "ki": " B "}                     # reads back exactly
    assert 'ki=" B "' in A._ki_missing_file("docs/genotype.md", k / "docs/genotype.md", k, view)
    assert 'list_ki_files(subdir="Demo", pattern="genotype")' in A._ki_missing_file(
        "Demo/docs/genotype.md", k / "docs/genotype.md", k, A._KiView(prefix="Demo/"))


def test_matching_has_a_hard_limit(tmp_path, monkeypatch):
    """Review r3: an allowed pattern can still be slow on very long paths. Long paths are skipped and
    one search stops after a time limit; both are said in the answer."""
    k = _fake_ki(tmp_path)
    pat = "*a**/*" + "a" * 100 + "b"
    long_files = [("a" * 200 + "/") * 15 + f"x{i:03d}.txt" for i in range(50)]
    monkeypatch.setattr(A, "_ki_walk", lambda *a_, **kw: (long_files, [], False))
    import time
    started = time.monotonic()
    out = A._ki_find(pat, k, k)
    assert time.monotonic() - started < 2.0
    assert "50 paths longer than 512 characters were not matched" in out
    monkeypatch.setattr(A, "_ki_walk", lambda *a_, **kw: (["docs/a.md", "docs/b.md"], ["docs/"], False))
    monkeypatch.setattr(A, "_KI_FIND_SECONDS", -1.0)                   # already past the limit
    out = A._ki_find("docs/*.md", k, k)
    assert out.startswith("No files match 'docs/*.md' in the part of the KI that was searched.")
    assert "only part of the KI was searched" in out


def test_cut_off_search_says_so_first(tmp_path, monkeypatch):
    k = _fake_ki(tmp_path)
    monkeypatch.setattr(A, "_KI_WALK_CAP", 3)
    out = A._ki_find("zzz_nothing", k, k)
    assert out.startswith("No files match 'zzz_nothing' in the part of the KI that was searched.")


def test_junction_is_not_counted_or_used_as_start(tmp_path, monkeypatch):
    """Review r3: junction checks also in counting and in the pattern's start folder."""
    k = _fake_ki(tmp_path)
    (k / "docs" / "jdir").mkdir(); (k / "docs" / "jdir" / "secret.txt").write_text("x")
    (k / "jtop").mkdir(); (k / "jtop" / "secret.txt").write_text("x")
    real_lstat = os.lstat
    junctions = {str(k / "docs" / "jdir"), str(k / "jtop")}

    class _Junction:
        def __init__(self, info):
            self.st_mode, self.st_reparse_tag = info.st_mode, A._IO_REPARSE_TAG_MOUNT_POINT

    def lstat(path, *a_, **kw):
        info = real_lstat(path, *a_, **kw)
        return _Junction(info) if os.fspath(path) in junctions else info

    monkeypatch.setattr(A.os, "lstat", lstat)
    assert "docs/  (2 files)" in A._ki_list_folder(k, k)               # jdir/secret.txt not counted
    assert A._ki_fixed_folder("jtop/*.txt", k) is None                 # never a start folder
    assert A._ki_find("jtop/*.txt", k, k).startswith("No files match")   # the walk never enters it
    found = A._ki_find("secret", k, k)
    assert found.startswith("No files match") and "secret.txt" not in found


def test_unreadable_entry_is_shown_not_walked(tmp_path, monkeypatch):
    k = _fake_ki(tmp_path)
    (k / "locked").mkdir(); (k / "locked" / "x.txt").write_text("x")
    (k / ".hidlock").mkdir()
    real_lstat = os.lstat
    blocked = {str(k / "locked"), str(k / ".hidlock")}

    def lstat(path, *a_, **kw):
        if os.fspath(path) in blocked:
            raise PermissionError(13, "Permission denied")
        return real_lstat(path, *a_, **kw)

    monkeypatch.setattr(A.os, "lstat", lstat)
    top = A._ki_list_folder(k, k)
    assert "locked  (cannot read)" in top and "locked/" not in top
    assert ".hidlock/" not in top and 'subdir=".hidlock"' not in top     # not offered as a folder
    assert "locked/x.txt" not in A._ki_find("x", k, k)                  # never walked into


def test_unicode_case_matches_the_pattern_rule(tmp_path):
    """Review r3: the start-folder shortcut uses the pattern's own case rule (Σ, σ, ς)."""
    k = tmp_path / "KI"
    (k / "Σ").mkdir(parents=True)
    if (k / "ς").exists() or (k / "σ").exists():
        pytest.skip("case-insensitive file system")
    (k / "ς").mkdir(); (k / "Σ" / "a.csv").write_text("x"); (k / "ς" / "b.csv").write_text("x")
    k = k.resolve()
    hits = A._ki_find("σ/*.csv", k, k).splitlines()[1:]
    assert sorted(hits) == sorted(["Σ/a.csv", "ς/b.csv"])


def test_intake_path_copied_into_a_pattern_and_placeholders(tmp_path):
    """Review r3: in intake a listed path (Demo/...) works as a pattern; placeholders keep Demo/."""
    k = _fake_ki(tmp_path)
    demo = A._KiView(prefix="Demo/")
    assert A._ki_find("Demo/docs/s4_genotype_config_skill.md", k, k, demo).splitlines()[1:] == [
        "Demo/docs/s4_genotype_config_skill.md"]
    assert A._ki_find("demo/docs/*.md", k, k, demo).splitlines()[1:] == [
        "Demo/docs/s2_weather_prep_skill.md", "Demo/docs/s4_genotype_config_skill.md"]
    assert 'list_ki_files(subdir="Demo/...")' in A._ki_find("nothing_here", k, k, demo)
    assert 'read_ki_file(path="Demo/...")' in A._ki_list_folder(k, k, demo)
    assert 'list_ki_files(subdir="Demo")' in A._ki_missing_file("Demo", k, k, demo)
    assert 'ki=" "' in A._KiView(ki=" ").call("list_ki_files", subdir="docs")


def test_whole_call_has_one_time_budget(tmp_path, monkeypatch):
    """Review r4: hints and the hidden retry share the budget; "close spelling" scores few names."""
    import random
    import time
    k = _fake_ki(tmp_path)
    rnd = random.Random(3)

    def similar(i):
        s = list("x" * 120)
        for _ in range(6):
            s[rnd.randrange(120)] = rnd.choice("abcdefgh")
        return "d%02d/" % (i % 50) + "".join(s) + "%05d.txt" % i

    names = [similar(i) for i in range(10_000)]
    monkeypatch.setattr(A, "_ki_walk", lambda *a_, **kw: (names, [], False))
    started = time.monotonic()
    A._ki_find("x" * 118 + "q.txt", k, k)
    assert time.monotonic() - started < 8.0          # was 10.9 s before (difflib over every name)
    started = time.monotonic()
    A._ki_missing_file("d00/" + "x" * 118 + "q.txt", k / "d00/q.txt", k)
    assert time.monotonic() - started < 8.0


def test_slow_hidden_walk_still_returns_hidden_hits(tmp_path, monkeypatch):
    """Review r4: a slow second walk is not blamed on matching, and its hits are kept."""
    import time
    k = _fake_ki(tmp_path)

    def walk(base, ki_root, *, hidden, deadline=None):
        if hidden:
            time.sleep(0.3)
            return [".kdt_runs/run.lock", "SKILL.md"], [], False
        return ["SKILL.md"], [], False

    monkeypatch.setattr(A, "_ki_walk", walk)
    monkeypatch.setattr(A, "_KI_FIND_SECONDS", 2.0)
    out = A._ki_find("*.lock", k, k)
    assert out.splitlines() == ["No visible file matches '*.lock'; these hidden, cache or backup files do:",
                                ".kdt_runs/run.lock"]


def test_length_limit_only_for_path_patterns(tmp_path, monkeypatch):
    """Review r4: 512 characters is the limit for a path pattern; a name search reads only the name."""
    k = _fake_ki(tmp_path)
    ok_path = "d" * (512 - len("/SKILL_extra.md")) + "/SKILL_extra.md"      # exactly 512
    long_path = "e" * (513 - len("/SKILL_extra.md")) + "/SKILL_extra.md"    # 513
    assert len(ok_path) == 512 and len(long_path) == 513
    monkeypatch.setattr(A, "_ki_walk", lambda *a_, **kw: ([ok_path, long_path], [], False))
    by_path = A._ki_find("**/SKILL_extra.md", k, k)
    assert ok_path in by_path and long_path not in by_path.splitlines()[:3]
    assert "1 paths longer than 512 characters were not matched" in by_path
    by_name = A._ki_find("SKILL_extra", k, k)
    assert ok_path in by_name and long_path in by_name and "not matched" not in by_name
    started = __import__("time").monotonic()
    rx = A._ki_glob_regex("*a**/*" + "a" * 250 + "b")                       # review r4 worst shape
    for _ in range(20):
        rx.match("a" * 511)
    assert __import__("time").monotonic() - started < 5.0


def test_intake_prefix_keeps_the_pattern_meaning(tmp_path):
    """Review r4: after Demo/ is taken off, a path pattern stays a path pattern."""
    k = _fake_ki(tmp_path)
    (k / "reader.py").write_text("x"); (k / "tools" / "reader.py").write_text("x")
    demo = A._KiView(prefix="Demo/")
    assert A._ki_find("Demo/*.py", k, k, demo).splitlines()[1:] == ["Demo/reader.py"]   # top folder only
    assert A._ki_find("Demo/reader.py", k, k, demo).splitlines()[1:] == ["Demo/reader.py"]
    everything = A._ki_find("Demo/", k, k, demo)
    assert "Demo/docs/s4_genotype_config_skill.md" in everything and "Demo/tools/reader.py" in everything
    assert A._ki_find("./Demo/docs/s4_*", k, k, demo).splitlines()[1:] == ["Demo/docs/s4_genotype_config_skill.md"]
    assert A._ki_find("DEMO/docs/s4_*", k, k, demo).splitlines()[1:] == ["Demo/docs/s4_genotype_config_skill.md"]
    assert "Demo/tools/reader.py" in A._ki_find("*.py", k, k, demo)        # no prefix: a name search
    empty = tmp_path / "empty"; empty.mkdir()
    assert 'list_ki_files(subdir="Demo/...")' in A._ki_missing_folder("Demo/x", empty / "x", empty.resolve(), demo)


def test_list_ki_files_schema_offers_pattern():
    schema = next(t for t in A.tool_schemas(None) if t["name"] == "list_ki_files")
    props = schema["input_schema"]["properties"]
    assert {"subdir", "pattern", "ki"} <= set(props)
    assert "one folder" in schema["description"].lower()
