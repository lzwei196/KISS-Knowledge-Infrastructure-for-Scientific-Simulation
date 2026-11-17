"""File reading, searching and small edits for the API agent's tools (LOCAL PATCH,
VENDOR_PATCHES.md #3, 2026-11-17).

Adapted from two open-source agents:
- DeepSeek Harness (MIT, github.com/deepseek-ai/deepseek-harness @ 39163dd3):
  ``packages/fs/tool-fs/src/read-render.ts`` (line-numbered read window, footers),
  ``packages/fs/tool-fs-search/src/grep.ts`` (ripgrep --json argv, grouped output, caps),
  ``packages/fs/fs-local/src/fsio.ts`` applyLiteralEdit (not found / matched N times).
- Qwen Code (Apache-2.0, github.com/QwenLM/qwen-code @ 6db070d7):
  ``packages/core/src/utils/editHelper.ts`` (forgiving edit match: curly quotes, dashes,
  odd spaces, trailing spaces; indentation always kept),
  ``packages/core/src/tools/priorReadEnforcement.ts`` (read before edit, changed since read).

Pure functions; the tool code in api.py does the path checks and decides the roots.
"""
from __future__ import annotations

import json
import math
import os
import threading
import re
import shutil
import subprocess
from pathlib import Path

READ_LIMIT = 2000            # default and largest `limit` (lines) of one read
READ_MAX_LINE = 2000         # characters kept of one line


class FileToolError(Exception):
    """A message for the model; api.py turns it into a ToolError."""


# --------------------------------------------------------------------------- reads

def _int_arg(value, name: str, default: int) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise FileToolError(f"{name} must be a positive whole number")
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise FileToolError(f"{name} must be a positive whole number") from None
    if not math.isfinite(f) or f < 1 or f != int(f):
        raise FileToolError(f"{name} must be a positive whole number")
    return int(f)


def read_args(args: dict) -> tuple[int, int]:
    """(offset, limit) from the tool arguments; offset is 1-based."""
    offset = _int_arg(args.get("offset"), "offset", 1)
    limit = _int_arg(args.get("limit"), "limit", READ_LIMIT)
    if limit > READ_LIMIT:
        raise FileToolError(f"limit must be {READ_LIMIT} or less; read the rest with offset")
    return offset, limit


def read_window(path: Path, display: str, offset: int, limit: int, max_bytes: int) -> str:
    """Lines ``offset..`` of a text file as ``N: text``, at most ``limit`` lines and ``max_bytes``
    bytes, with a footer saying where it stopped (DSH buildWindow + formatReadOutput). The whole file
    is scanned once so the total line count is exact."""
    lines: list[str] = []
    total = 0
    used = 0
    capped = False
    keep = READ_MAX_LINE * 4 + 8                 # bytes kept of one line (UTF-8 is at most 4 a char)
    with open(path, "rb") as f:
        while True:
            raw = f.readline(1 << 20)
            if not raw:
                break
            if not raw.endswith(b"\n"):         # a long line: keep its start, skip the rest
                head = raw[:keep]
                while raw and not raw.endswith(b"\n"):
                    raw = f.readline(1 << 20)
                raw = head + b"\n"
            total += 1
            if capped or total < offset or len(lines) >= limit:
                continue
            text = raw[:keep].rstrip(b"\n").rstrip(b"\r").decode("utf-8", errors="replace")
            if len(raw) > keep or len(text) > READ_MAX_LINE:
                text = text[:READ_MAX_LINE] + f"... (line truncated to {READ_MAX_LINE} chars)"
            row = f"{total}: {text}"
            size = len(row.encode("utf-8")) + 1
            if used + size > max_bytes and lines:
                capped = True
                continue
            used += size
            lines.append(row)
    if offset > total and not (total == 0 and offset == 1):
        raise FileToolError(f"offset {offset} is past the end of {display} ({total} lines)")
    end = offset + len(lines) - 1 if lines else offset - 1
    if capped:
        foot = f"(Output capped. Showing lines {offset}-{end} of {total}. Use offset={end + 1} to continue.)"
    elif end < total:
        foot = f"(Showing lines {offset}-{end} of {total}. Use offset={end + 1} to continue.)"
    else:
        foot = f"(End of file - total {total} lines)"
    body = "\n".join(lines)
    return f"{display}\n{body}\n\n{foot}" if lines else f"{display}\n{foot}"


# --------------------------------------------------------------------------- search

GREP_MAX_MATCHES = 200       # matches shown in one answer
GREP_MAX_LINE = 400          # characters shown of one matched line
GREP_PER_FILE = 50           # matches taken from one file (rg --max-count)
GREP_TIMEOUT = 20            # seconds
GREP_RAW_CAP = 20_000_000    # bytes of rg output read at most
_SKIP_GLOBS = ("!__pycache__", "!*.pyc", "!*.pyo", "!*.bak*", "!*.orig*", "!*.backup*", "!*~")


#: where the server keeps its own ripgrep (static build, copied at install); then PATH, then the
#: copy that ships with the Kimi CLI
RG_PLACES = ("/mnt/disk1/Hydrocraft_server/tools/ripgrep/rg",)


def ripgrep() -> str | None:
    for c in (os.environ.get("GEOFORGE_RG"), *RG_PLACES, shutil.which("rg"),
              str(Path.home() / ".kimi-code" / "bin" / "rg")):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def check_include(include: str) -> str:
    """One positive glob (DSH validateInclude): no "!x", no "a,b" list outside {..}."""
    include = (include or "").strip()
    if not include:
        return ""
    if include.startswith("!"):
        raise FileToolError("include must be one file-name filter like '*.yaml'; '!' (leave out) is not supported")
    depth = 0
    for ch in include:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            raise FileToolError("include must be one filter, not a list: use '*.{yaml,txt}' instead of '*.yaml,*.txt'")
    return include


def search(pattern: str, base: Path, root: Path, *, include: str = "",
           skip_names: tuple[str, ...] = (), literal: bool = False) -> str:
    """Search text files under ``base`` (inside ``root``) for ``pattern``; paths in the answer are
    relative to ``root``. Hidden, cache and backup files are left out (also below an explicitly
    named ``base``), and every folder named in ``skip_names``. Case is ignored."""
    if not pattern:
        raise FileToolError("pattern is empty; e.g. pattern='TIME_STEP' or pattern='def run'")
    include = check_include(include)
    if "\0" in pattern or "\0" in include:
        raise FileToolError("pattern and include cannot contain a NUL character")
    rg = ripgrep()
    if rg is None:
        raise FileToolError("text search is not available on this machine (ripgrep missing)")
    argv = [rg, "--json", "--ignore-case", "--no-ignore", "--max-filesize=5M",
            f"--max-count={GREP_PER_FILE}", "--no-config"]
    if literal:
        argv.append("--fixed-strings")
    if include:
        argv.append(f"--glob={include}")        # first: in ripgrep a later --glob wins, so the
    argv += [f"--glob={g}" for g in _SKIP_GLOBS]  # exclusions below always beat include
    argv.append("--glob=!.*")
    argv += [f"--glob=!{t}/" for t in skip_names]
    argv += [f"--regexp={pattern}", "--", "."]
    if base != root:
        argv[-1] = base.relative_to(root).as_posix()
    try:
        proc = subprocess.Popen(argv, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.DEVNULL, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
    except OSError as e:
        raise FileToolError(f"text search could not start: {e.strerror or e}") from None
    out = bytearray()
    errbuf = bytearray()
    full = threading.Event()

    def pump_out():
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                return
            if not full.is_set():
                out.extend(chunk)
                if len(out) > GREP_RAW_CAP:
                    full.set()
                    proc.kill()

    def pump_err():                              # keep draining; keep only the tail
        while True:
            chunk = proc.stderr.read(65536)
            if not chunk:
                return
            errbuf.extend(chunk)
            del errbuf[:-8192]

    readers = [threading.Thread(target=pump_out, daemon=True), threading.Thread(target=pump_err, daemon=True)]
    for t in readers:
        t.start()
    cut = False
    try:
        proc.wait(timeout=GREP_TIMEOUT)
    except subprocess.TimeoutExpired:
        cut = True
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    for t in readers:
        t.join(timeout=5)
    cut = cut or full.is_set()
    err = bytes(errbuf)
    if proc.returncode == 2 and not out:
        msg = err.decode("utf-8", "replace").strip().splitlines()
        bad = next((m for m in msg if "regex" in m.lower() or "error" in m.lower()), msg[-1] if msg else "")
        if "regex" in bad.lower() and not literal:
            return search(pattern, base, root, include=include, skip_names=skip_names, literal=True) + \
                "\n(pattern was not a valid regular expression, so it was searched as plain text)"
        raise FileToolError(f"search failed: {bad[:300]}")

    by_file: dict[str, list[str]] = {}
    per_file: dict[str, int] = {}
    seen = 0
    text = bytes(out[:GREP_RAW_CAP]).decode("utf-8", "replace")
    lines = text.split("\n")
    if cut and lines:
        lines = lines[:-1]                       # the last line may be half written
    for line in lines:
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("type") != "match":
            continue
        data = rec.get("data") or {}
        path = ((data.get("path") or {}).get("text"))
        num = data.get("line_number")
        if not isinstance(path, str) or not isinstance(num, int):
            continue
        seen += 1
        if seen > GREP_MAX_MATCHES:
            continue
        lt = (data.get("lines") or {}).get("text")
        lt = "(line is not valid UTF-8)" if lt is None else lt.rstrip("\n").rstrip("\r")
        if len(lt) > GREP_MAX_LINE:
            lt = lt[:GREP_MAX_LINE] + " ..."
        rel = path[2:] if path.startswith("./") else path
        per_file[rel] = per_file.get(rel, 0) + 1
        by_file.setdefault(rel, []).append(f"Line {num}: {lt.strip()}")
    where = "" if base == root else f" in {base.relative_to(root).as_posix()}" + ("/" if base.is_dir() else "")
    if seen == 0:
        msg = (f"No matches for {pattern!r}{where}" + (f" (files: {include})" if include else "")
               + ". (Files over 5 MB, hidden files and backups are not searched.)")
        if cut:
            msg += " (the search stopped early: it ran too long; narrow path or include)"
        return msg
    shown = min(seen, GREP_MAX_MATCHES)
    noun = "match" if seen == 1 else "matches"
    head = (f"Found {seen} {noun}" if seen == shown else f"Found {seen} {noun}, showing the first {shown}")
    head += f" in {len(by_file)} file{'s' if len(by_file) != 1 else ''}{where}:"
    body = "\n\n".join(f"{p}\n" + "\n".join(rows) for p, rows in by_file.items())
    notes = []
    if seen > shown:
        notes.append("narrow pattern, path or include to see the rest")
    if cut:
        notes.append("the search stopped early (too long or too much output), so there may be more")
    if any(n >= GREP_PER_FILE for n in per_file.values()):
        notes.append(f"at most {GREP_PER_FILE} matches are taken from one file; read it with offset/limit for more")
    tail = ("\n\n(" + "; ".join(notes) + ")") if notes else ""
    return f"{head}\n\n{body}{tail}"


# --------------------------------------------------------------------------- edits

_SAME_CHAR = {
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-",
    "−": "-", "‘": "'", "’": "'", "‚": "'", "‛": "'", "“": '"',
    "”": '"', "„": '"', "‟": '"', " ": " ", " ": " ", " ": " ",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
    " ": " ", " ": " ", " ": " ", "　": " ",
}
_SAME_TABLE = str.maketrans(_SAME_CHAR)


def _plain(s: str) -> str:
    """One character for one character, so positions stay the same (Qwen normalizeBasicCharacters)."""
    return s.translate(_SAME_TABLE)


def _starts(text: str, needle: str) -> list[int]:
    out, i = [], text.find(needle)
    while i != -1:
        out.append(i)
        i = text.find(needle, i + len(needle))
    return out


def _line_matches(content: str, needle: str) -> list[tuple[int, int]]:
    """(start, end) of every run of whole lines equal to ``needle``'s lines when trailing spaces
    and curly quotes / dashes / odd spaces are ignored; indentation must match (Qwen
    findLineBasedMatch)."""
    pat = needle.split("\n")
    ends_nl = needle.endswith("\n")
    if ends_nl:
        pat = pat[:-1]
    if not pat:
        return []
    lines = content.split("\n")
    starts, pos = [], 0
    for ln in lines:
        starts.append(pos)
        pos += len(ln) + 1
    want = [_plain(p).rstrip() for p in pat]
    if not any(want):                            # only spaces / empty lines: exact matches only
        return []
    have = [_plain(ln).rstrip() for ln in lines]
    out = []
    m = len(pat)
    i = 0
    while i <= len(lines) - m:
        if have[i] == want[0] and have[i:i + m] == want:
            last = i + m - 1
            end = starts[last] + len(lines[last])
            if ends_nl and end < len(content):
                end += 1                         # the line end (with its "\r", if any)
            elif lines[last].endswith("\r"):
                end -= 1                         # the line keeps its own "\r"
            out.append((starts[i], end))
            i += m
        else:
            i += 1
    return out


def find_edit(content: str, old: str) -> tuple[list[tuple[int, int]], str]:
    """Where ``old`` is in ``content``: exact first, then the forgiving passes. Returns the spans
    and how it was found ("exact", "quotes", "lines")."""
    hits = _starts(content, old)
    if hits:
        return [(i, i + len(old)) for i in hits], "exact"
    if not old.strip():                          # only spaces / line ends: exact matches only
        return [], ""
    hits = _starts(_plain(content), _plain(old))
    if hits:
        return [(i, i + len(old)) for i in hits], "quotes"
    spans = _line_matches(content, old)
    return spans, ("lines" if spans else "")


def _lines_of(content: str, positions) -> list[int]:
    """Line numbers of increasing positions, counted in one pass."""
    out, line, prev = [], 1, 0
    for pos in positions:
        line += content.count("\n", prev, pos)
        prev = pos
        out.append(line)
    return out


EDIT_MAX_CHARS = 1_000_000     # the edited file may not grow past this (write_project_file's 1 MB)


def apply_edit(content: str, old: str, new: str, replace_all: bool, display: str) -> tuple[str, int, list[int]]:
    """(new content, replacements, first lines of the changes). Raises FileToolError with what the
    model should do next when the text is not there or is there more than once."""
    if old == "":
        raise FileToolError("old_string is empty: copy the exact lines to change from read_project_file")
    if old == new:
        raise FileToolError("old_string and new_string are the same: nothing to change")
    old_lf, new_lf = old.replace("\r\n", "\n"), new.replace("\r\n", "\n")
    tries = [(old, new), (old_lf, new_lf)] if "\r\n" in content else [(old_lf, new_lf)]
    if "\r\n" in content:                       # a model writes "\n"; the file may have "\r\n"
        tries.append((old_lf.replace("\n", "\r\n"), new_lf.replace("\n", "\r\n")))
    spans, how, new_n = [], "", new
    for o, n_ in tries:
        spans, how = find_edit(content, o)
        if spans:
            new_n = n_
            break
    if not spans:
        raise FileToolError(
            f"old_string was not found in {display}. No change made. Copy the text exactly as it is "
            f"in the file (same indentation, without the 'N: ' line numbers that read_project_file "
            f"shows); read the file again to check.")
    if len(spans) > 1 and not replace_all:
        where = ", ".join(str(n) for n in _lines_of(content, [s for s, _e in spans[:10]]))
        raise FileToolError(
            f"old_string matched {len(spans)} times in {display} (lines {where}). No change made. "
            f"Add a few lines around it so it matches once, or set replace_all=true.")
    grow = len(new_n.replace("\n", "\r\n") if "\r\n" in content else new_n) * len(spans) - sum(e - s for s, e in spans)
    if len(content) + grow > EDIT_MAX_CHARS:     # checked before the new text is built
        raise FileToolError(f"the edited {display} would be over 1 MB. No change made.")
    out, last = [], 0
    firsts = []
    shift = 0
    for (s, e), line in zip(spans, _lines_of(content, [s for s, _e in spans])):
        rep = new_n
        if "\r\n" not in rep and "\n" in rep and ("\r\n" in content[s:e] or content.startswith("\r\n", e)):
            rep = rep.replace("\n", "\r\n")       # only the replaced lines follow the file's line ends
        out.append(content[last:s])
        firsts.append(line + shift)
        out.append(rep)
        shift += rep.count("\n") - content.count("\n", s, e)
        last = e
    out.append(content[last:])
    return "".join(out), len(spans), firsts


def edit_snippet(content: str, first_line: int, new: str, around: int = 3, cap: int = 40) -> str:
    """The changed lines plus a few around them, numbered like read_project_file."""
    lines = content.replace("\r\n", "\n").split("\n")
    n_new = max(1, new.replace("\r\n", "\n").count("\n") + 1)
    a = max(1, first_line - around)
    b = min(len(lines), first_line + n_new - 1 + around, a + cap - 1)
    return "\n".join(f"{i}: {lines[i - 1]}" for i in range(a, b + 1))


# ----------------------------------------------------------------- read before edit

#: path -> (mtime_ns, size) at the last read or write in this process (one agent turn).
_SEEN: dict[str, tuple[int, int]] = {}


def stamp(path: Path) -> None:
    try:
        st = path.stat()
    except OSError:
        return
    _SEEN[str(path)] = (st.st_mtime_ns, st.st_size)


def check_seen(path: Path, display: str) -> None:
    """Qwen priorReadEnforcement / DSH FS_NOT_OBSERVED + FS_STALE_VERSION."""
    was = _SEEN.get(str(path))
    if was is None:
        raise FileToolError(f"read {display} with read_project_file first, then edit it")
    st = path.stat()
    if (st.st_mtime_ns, st.st_size) != was:
        raise FileToolError(f"{display} changed since you last read it; read it again, then edit")
