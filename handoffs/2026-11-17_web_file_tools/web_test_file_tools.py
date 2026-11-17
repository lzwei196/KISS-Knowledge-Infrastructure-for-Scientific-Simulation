"""2026-11-17 file tools (kiss_cli/filetools.py, VENDOR_PATCHES.md #3): line-numbered reads,
search_files, name patterns for project/work lists, edit_project_file."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from kiss_cli import api as A                      # noqa: E402
from kiss_cli import filetools as ft               # noqa: E402
from test_agent import FakeModel, call, say, run_agent, manage, env  # noqa: E402,F401


# ------------------------------------------------------------------ read window

def test_read_window_numbers_lines_and_says_how_to_continue(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("".join(f"line {i}\n" for i in range(1, 11)))
    out = ft.read_window(f, "a.txt", 1, 3, 60000)
    assert out.splitlines()[:4] == ["a.txt", "1: line 1", "2: line 2", "3: line 3"]
    assert out.endswith("(Showing lines 1-3 of 10. Use offset=4 to continue.)")
    out = ft.read_window(f, "a.txt", 9, 2000, 60000)
    assert "9: line 9" in out and "10: line 10" in out and out.endswith("(End of file - total 10 lines)")
    with pytest.raises(ft.FileToolError, match="past the end of a.txt \\(10 lines\\)"):
        ft.read_window(f, "a.txt", 11, 5, 60000)


def test_read_window_byte_cap_long_lines_crlf_and_empty(tmp_path):
    f = tmp_path / "b.txt"
    f.write_bytes(b"x" * 5000 + b"\r\nshort\r\n" + b"y\n" * 100)
    out = ft.read_window(f, "b.txt", 1, 2000, 60000)
    assert "1: " + "x" * 2000 + "... (line truncated to 2000 chars)" in out
    assert "\n2: short\n" in out and "\r" not in out
    capped = ft.read_window(f, "b.txt", 1, 2000, 2100)
    assert capped.endswith("(Output capped. Showing lines 1-12 of 102. Use offset=13 to continue.)"), capped[-200:]
    e = tmp_path / "e.txt"; e.write_text("")
    assert ft.read_window(e, "e.txt", 1, 10, 100).endswith("(End of file - total 0 lines)")


def test_read_args_checks():
    assert ft.read_args({}) == (1, 2000)
    assert ft.read_args({"offset": "5", "limit": 10.0}) == (5, 10)
    for bad in ({"offset": 0}, {"offset": -1}, {"limit": 2001}, {"offset": 1.5}, {"limit": "abc"},
                {"offset": True}, {"limit": float("nan")}):
        with pytest.raises(ft.FileToolError):
            ft.read_args(bad)


# ------------------------------------------------------------------ search

needs_rg = pytest.mark.skipif(ft.ripgrep() is None, reason="no ripgrep here")


@needs_rg
def test_search_groups_by_file_skips_hidden_backup_and_memory(tmp_path):
    r = tmp_path / "p"
    for rel, text in {"inputs/a.yaml": "x: 1\nTIME_STEP: 3600\n", "inputs/b.txt": "time_step = 1\n",
                      "memory/m.txt": "TIME_STEP\n", "inputs/memory/n.txt": "TIME_STEP\n",
                      ".hidden/h.txt": "TIME_STEP\n", "inputs/a.yaml.bak": "TIME_STEP\n",
                      "__pycache__/c.pyc": "TIME_STEP\n"}.items():
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_text(text)
    out = ft.search("time_step", r, r, skip_names=("memory",))
    assert out.startswith("Found 2 matches in 2 files:"), out
    assert "inputs/a.yaml\nLine 2: TIME_STEP: 3600" in out and "inputs/b.txt\nLine 1: time_step = 1" in out
    for bad in ("memory", ".hidden", ".bak", "pycache"):
        assert bad not in out
    one = ft.search("time_step", r / "inputs", r, include="*.yaml")
    assert one.startswith("Found 1 match in 1 file in inputs/:"), one
    assert ft.search("nothing_here", r, r).startswith("No matches for 'nothing_here'")


@needs_rg
def test_search_odd_patterns_never_become_flags_or_crash(tmp_path):
    r = tmp_path / "p"; r.mkdir()
    (r / "a.txt").write_text("a(b\n--files\n-v\n")
    assert "Line 1: a(b" in ft.search("a(b", r, r) and "searched as plain text" in ft.search("a(b", r, r)
    assert "Line 2: --files" in ft.search("--files", r, r)
    assert "Line 3: -v" in ft.search("-v", r, r)
    with pytest.raises(ft.FileToolError):
        ft.search("", r, r)
    for inc in ("!*.txt", "*.txt,*.md"):
        with pytest.raises(ft.FileToolError):
            ft.search("a", r, r, include=inc)
    assert ft.search("a", r, r, include="*.{txt,md}").startswith("Found")


@needs_rg
def test_search_caps_matches_and_lines(tmp_path):
    r = tmp_path / "p"; r.mkdir()
    for i in range(6):
        (r / f"f{i}.txt").write_text("hit " + "z" * 1000 + "\n" + "hit\n" * 60)
    out = ft.search("hit", r, r)
    assert out.startswith("Found 300 matches, showing the first 200 in "), out[:100]
    assert "narrow pattern, path or include" in out and "at most 50 matches" in out
    assert " ..." in out and "z" * 401 not in out


@needs_rg
def test_search_does_not_follow_links_out(tmp_path):
    r = tmp_path / "p"; r.mkdir()
    out_dir = tmp_path / "outside"; out_dir.mkdir(); (out_dir / "s.txt").write_text("SECRET\n")
    (r / "link").symlink_to(out_dir, target_is_directory=True)
    (r / "flink.txt").symlink_to(out_dir / "s.txt")
    assert ft.search("SECRET", r, r).startswith("No matches")


# ------------------------------------------------------------------ edits

def test_edit_exact_once_many_and_missing():
    c = "a = 1\nb = 2\na = 1\n"
    with pytest.raises(ft.FileToolError, match="matched 2 times in f \\(lines 1, 3\\)"):
        ft.apply_edit(c, "a = 1", "a = 9", False, "f")
    out, n, firsts = ft.apply_edit(c, "a = 1", "a = 9", True, "f")
    assert out == "a = 9\nb = 2\na = 9\n" and n == 2 and firsts == [1, 3]
    out, n, firsts = ft.apply_edit(c, "b = 2", "b = 3\nb2 = 4", False, "f")
    assert out == "a = 1\nb = 3\nb2 = 4\na = 1\n" and firsts == [2]
    with pytest.raises(ft.FileToolError, match="was not found in f"):
        ft.apply_edit(c, "c = 3", "x", False, "f")
    for old, new in (("", "x"), ("a = 1", "a = 1")):
        with pytest.raises(ft.FileToolError):
            ft.apply_edit(c, old, new, False, "f")


def test_edit_forgiving_match_keeps_indentation():
    c = "def f():\n    say(“hi”)  \n    return 1\n"
    out, n, _ = ft.apply_edit(c, 'say("hi")', 'say("bye")', False, "f")      # curly quotes
    assert out == 'def f():\n    say("bye")  \n    return 1\n'
    out, n, _ = ft.apply_edit(c, '    say("hi")\n    return 1\n', '    return 2\n', False, "f")  # trailing spaces
    assert out == "def f():\n    return 2\n"
    with pytest.raises(ft.FileToolError, match="not found"):           # wrong indentation never matches
        ft.apply_edit(c, 'say("hi")\nreturn 1', "x", False, "f")


def test_edit_keeps_windows_line_ends():
    out, _n, _f = ft.apply_edit("a\r\nb\r\n", "b", "c\nd", False, "f")
    assert out == "a\r\nc\r\nd\r\n"


def test_read_before_edit(tmp_path):
    p = tmp_path / "x.txt"; p.write_text("v1")
    ft._SEEN.pop(str(p), None)
    with pytest.raises(ft.FileToolError, match="read x.txt with read_project_file first"):
        ft.check_seen(p, "x.txt")
    ft.stamp(p); ft.check_seen(p, "x.txt")
    p.write_text("v2 longer")
    with pytest.raises(ft.FileToolError, match="changed since you last read it"):
        ft.check_seen(p, "x.txt")


# ------------------------------------------------------------------ list patterns

def test_name_filter_rules():
    f = A._name_filter("weather", ".")
    assert f("inputs/Weather_2020.csv") and not f("weather/x.csv")
    g = A._name_filter("*.csv", ".")
    assert g("inputs/deep/a.CSV") and not g("inputs/a.csv.bak")
    h = A._name_filter("**/*.txt", "inputs")
    assert h("inputs/a/b.txt") and not h("outputs/b.txt")
    i = A._name_filter("inputs/wea", ".")
    assert i("inputs/weather.csv") and not i("outputs/weather.csv")
    assert A._name_filter("", ".") is None and A._name_filter(None, ".") is None
    for bad in ("../x", "/etc"):
        with pytest.raises(A.ToolError):
            A._name_filter(bad, ".")
    assert A._capped_list(["a", "b", "c"], 2) == "a\nb\n(showing 2 of 3 files: use pattern=... or subdir=... to narrow it)"


# ------------------------------------------------------------------ through the real agent

def test_file_tools_through_the_agent(env):
    e, ws = env
    manage(e, ws, "PLANNING")
    (ws / "inputs").mkdir(exist_ok=True)
    (ws / "inputs" / "cfg.txt").write_text("".join(f"key{i} = {i}\n" for i in range(1, 2501)))
    (ws / "inputs" / "other.txt").write_text("alpha\n")
    m = FakeModel([
        call("read_project_file", {"path": "inputs/cfg.txt"}, "r1"),
        call("read_project_file", {"path": "inputs/cfg.txt", "offset": 2400, "limit": 5}, "r2"),
        call("edit_project_file", {"path": "inputs/other.txt", "old_string": "alpha", "new_string": "beta"}, "e0"),
        call("edit_project_file", {"path": "inputs/cfg.txt", "old_string": "key2400 = 2400",
                                   "new_string": "key2400 = 0"}, "e1"),
        call("edit_project_file", {"path": "inputs/cfg.txt", "old_string": "nothing", "new_string": "x"}, "e2"),
        call("search_files", {"pattern": "key2400 =", "where": "project"}, "s1"),
        call("search_files", {"pattern": "genotype", "ki": "DSSAT", "include": "*.md"}, "s2"),
        call("search_files", {"pattern": "x", "where": "project", "path": "memory"}, "s3"),
        call("read_ki_file", {"ki": "DSSAT", "path": "SKILL.md", "limit": 3}, "k1"),
        call("list_project_files", {"subdir": "inputs", "pattern": "*.txt"}, "l1"),
        call("edit_project_file", {"path": "runs/flow-state.json", "old_string": "PLANNING",
                                   "new_string": "RUNNING"}, "e3"),
        say("done")])
    p, _ev = run_agent(e, m, "look at the config")
    assert p.returncode == 0, p.stderr
    r1, r2, e0, e1, e2, s1, s2, s3, k1, l1, e3 = m.tool_results()
    assert r1.splitlines()[1] == "1: key1 = 1" and "Use offset=2001 to continue." in r1, r1[-200:]
    assert r2.splitlines()[1:6] == [f"{i}: key{i} = {i}" for i in range(2400, 2405)]
    assert e0.startswith("ERROR") and "read inputs/other.txt with read_project_file first" in e0, e0
    assert (ws / "inputs" / "other.txt").read_text() == "alpha\n"
    assert e1.startswith("edited inputs/cfg.txt (line 2400)") and "2400: key2400 = 0" in e1, e1
    assert "key2400 = 0\nkey2401 = 2401\n" in (ws / "inputs" / "cfg.txt").read_text()
    assert e2.startswith("ERROR") and "was not found" in e2
    assert s1.startswith("Found 1 match in 1 file:") and "inputs/cfg.txt\nLine 2400: key2400 = 0" in s1, s1
    assert not s2.startswith("ERROR") and "Line " in s2, s2[:300]
    assert s3.startswith("ERROR") and "no such folder" in s3, s3
    assert k1.splitlines()[0] == "SKILL.md" and k1.splitlines()[1].startswith("1: ") and "Use offset=4" in k1
    assert l1.splitlines() and all(".txt" in ln for ln in l1.splitlines()), l1
    assert e3.startswith("ERROR") and "PLANNING" in (ws / "runs" / "flow-state.json").read_text()
    m.close()


def test_read_only_turn_offers_search_but_not_edit(env):
    e, ws = env
    m = FakeModel([say("ok")])
    p, _ev = run_agent(e, m, "plan only", "--read-only")
    assert p.returncode == 0, p.stderr
    offered = {t["function"]["name"] for t in m.requests[0]["tools"]}
    assert "search_files" in offered and "edit_project_file" not in offered
    m.close()


# ------------------------------------------------------------------ review f1 (codex)

@needs_rg
def test_include_never_beats_the_exclusions(tmp_path):                     # f1 codex #1
    r = tmp_path / "p"
    for rel in ("memory/m.txt", "inputs/memory/n.txt", ".hid/h.txt", "inputs/.h2", "a.txt.bak", "ok.txt"):
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_text("SECRET\n")
    for inc in ("*", "**", "*.txt", "memory/**", ".*", "*.bak"):
        out = ft.search("SECRET", r, r, include=inc, skip_names=("memory",))
        body = out.split("\n", 1)[1] if out.startswith("Found") else ""
        for bad in ("memory", ".hid", ".h2", ".bak"):
            assert bad not in body, (inc, out)
    assert "ok.txt" in ft.search("SECRET", r, r, include="*", skip_names=("memory",))


def test_offset_infinite_is_a_tool_error():                                 # f1 codex #6
    for bad in ("1e999", float("inf"), "-inf"):
        with pytest.raises(ft.FileToolError):
            ft.read_args({"offset": bad})


def test_replace_all_on_a_big_file_is_fast():                               # f1 codex #3
    import time as _t
    c = "a\n" * 500_000
    t0 = _t.monotonic()
    out, n, firsts = ft.apply_edit(c, "a", "b", True, "f")
    assert n == 500_000 and out == "b\n" * 500_000 and firsts[-1] == 500_000
    assert _t.monotonic() - t0 < 10


def test_edit_leaves_other_line_ends_alone():                               # f1 codex #4
    assert ft.apply_edit("a\r\nb\nc\n", "b", "B", False, "f")[0] == "a\r\nB\nc\n"
    assert ft.apply_edit("a\r\nb\r\nc\n", "a\nb", "x\ny", False, "f")[0] == "x\r\ny\r\nc\n"
    assert ft.apply_edit("k = 1  \r\nz\r\n", "k = 1\nz", "k = 2\nz", False, "f")[0] == "k = 2\r\nz\r\n"


# ------------------------------------------------------------------ review f1 (opus)

def test_blank_old_string_matches_only_exactly():                           # f1 opus #1
    out, n, _ = ft.apply_edit("a\n  \nb\n\nc\n", "  ", "X", True, "f")
    assert out == "a\nX\nb\n\nc\n" and n == 1
    with pytest.raises(ft.FileToolError):
        ft.apply_edit("a\n\nb\n", "   ", "X", True, "f")


def test_nul_in_search_is_a_tool_error(tmp_path):                           # f1 opus #2
    for kw in ({"pattern": "a\0b"}, {"pattern": "a", "include": "*\0"}):
        with pytest.raises(ft.FileToolError):
            ft.search(kw["pattern"], tmp_path, tmp_path, include=kw.get("include", ""))


def test_line_numbered_content_is_refused():                                # f1 opus #3
    assert A._looks_line_numbered("1: a\n2: b\n3: c\n")
    assert A._looks_line_numbered("40: x = 1\n41: \n42: y\n")
    assert not A._looks_line_numbered("1: a\n2: b\n")
    assert not A._looks_line_numbered("1: a\n3: b\n4: c\n")
    assert not A._looks_line_numbered("1: a\nb\n2: c\n")


def test_giant_line_is_read_in_pieces(tmp_path):                            # f1 opus #6
    f = tmp_path / "g.txt"
    with open(f, "wb") as h:
        h.write(b"\xe4\xb8\xad" * 3_000_000 + b"\nend\n")                  # one 9 MB line, then "end"
    out = ft.read_window(f, "g.txt", 1, 10, 60000)
    assert "... (line truncated to 2000 chars)" in out and "\n2: end" in out
    assert out.endswith("(End of file - total 2 lines)")


# ------------------------------------------------------------------ review f2 (codex)

def test_replace_all_growth_is_refused_before_building():                   # f2 codex #1
    with pytest.raises(ft.FileToolError, match="over 1 MB"):
        ft.apply_edit("a\n" * 500_000, "a", "b" * 20_000, True, "f")


def test_lf_edit_just_under_1mb_is_allowed():                                # f3 codex #1 / opus #1
    content = "x" * 990_002 + "END"                 # LF file: "\n" is not counted as "\r\n"
    out = ft.apply_edit(content, "END", "y\n" * 4500, False, "f")[0]
    assert len(out) == 999_002
    with pytest.raises(ft.FileToolError, match="over 1 MB"):   # a CRLF file still counts "\r\n"
        ft.apply_edit("\r\n" + "x" * 990_000 + "END", "END", "y\n" * 4500, False, "f")


def test_blank_old_string_skips_the_quote_pass():                            # f2 codex #2
    with pytest.raises(ft.FileToolError, match="not found"):
        ft.apply_edit("a\n  \nb\n", "  ", "X", False, "f")


def test_crlf_old_string_in_an_lf_file_writes_lf():                           # f2 opus #2
    assert ft.apply_edit("a\nb\nc\n", "a\r\nb", "X\r\nY", False, "f")[0] == "X\nY\nc\n"
