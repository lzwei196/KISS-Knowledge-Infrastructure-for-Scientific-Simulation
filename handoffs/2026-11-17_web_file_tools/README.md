# Web file tools -> desktop (handoff, 2026-11-17)

The GeoForge web agent ("GeoForge agent (API)", small models like Qwen 27B) got better file tools on
2026-11-17. They are LIVE on the web server since 16:26. This folder and the branch `web-updates` carry them to
the desktop app. The web engine is a vendored copy of `kiss/kiss_cli/` (local patches #1-#3 in
`web_VENDOR_PATCHES.md`); patch #3 is this change.

## What was wrong, what is better

| Before | Now |
|---|---|
| A big file read was cut at 60,000 / 120,000 characters with no word; the model thought it had all of it | Lines come back numbered (`12: text`) with a footer: "Showing lines 1-2000 of 8500. Use offset=2001 to continue." |
| No way to read part of a file | `offset` / `limit` on read_ki_file, read_project_file, read_work_file (at most 2000 lines) |
| No text search; the model opened files one by one | New tool `search_files` (ripgrep, grouped by file, 200 matches, 20 s, skips hidden / cache / backup / project `memory/`) |
| Project / work lists stopped at 1000 / 800 lines silently | `pattern` filter + "(showing 1000 of N files; use pattern or subdir)" |
| Changing one line meant rewriting the whole file (small models break files that way) | New tool `edit_project_file` (old_string -> new_string; must match once unless replace_all; forgiving match for curly quotes, dashes, odd spaces, trailing spaces; indentation kept; line ends kept) |
| Nothing stopped an edit made from an old view | The file must have been read earlier in the same process and be unchanged since |

Adapted from DeepSeek Harness (MIT, @39163dd3: tool-fs read-render.ts, tool-fs-search grep.ts, fs-local
applyLiteralEdit) and Qwen Code (Apache-2.0, @6db070d7: utils/editHelper.ts, tools/priorReadEnforcement.ts).

## How to pull

```
git fetch origin
git merge origin/web-updates        # into your working branch
```
`web-updates` is based on `desktop-ki-file-tools` (PR #2, the desktop list_ki_files work), so it brings that
too. Future web engine updates will be added to `web-updates` the same way.

What merges as is:
- `kiss/kiss_cli/filetools.py` - all the logic (pure functions, no web code).
- `kiss/tests/test_filetools.py` - 21 tests of filetools alone (pass on Linux: `pytest tests/test_filetools.py`).
- this folder.

What you must do by hand (the desktop `api.py` differs from the web copy in ~2,700 lines, so the web
`api.py` cannot be copied):
1. **Wire the tools in `kiss/kiss_cli/api.py`**, following `web_api_py.patch`: tool schemas (offset/limit,
   pattern, the two new tools), and in `execute_tool` call `filetools.read_window`, `filetools.search`,
   `filetools.apply_edit`, `stamp` / `check_seen`; turn `FileToolError` into the tool error text.
   edit_project_file must use exactly the same write-folder and flow checks as write_project_file.
2. **Flow allow-list**: add `search_files` (read-only) and `edit_project_file` (write) to
   `ki_tools_common/ki_tools_common/flow/policy.py`, or a desktop flow hides them. The web did this in
   `gate.py` (`web_gate_py.patch`); the desktop has no gate.py.
3. **ripgrep**: `filetools.RG_PLACES` holds the web server's path. Ship rg (15.x; `rg.exe` on Windows) with
   the app and put its path there or in env `GEOFORGE_RG`. Without rg, search_files answers "ripgrep missing".
4. **Read-before-edit memory** (`filetools._SEEN`) lives as long as the process. On the web that is one turn;
   in the desktop app it is the whole session. Decide if that is fine or clear it per turn.
5. **Windows**: test CRLF files (edits keep the file's own line ends) and paths with `\`.
6. Web-only, skip or adapt: the line-numbered-content warning in write_project_file is in api.py (keep it;
   small models copy "12: " numbers into files), the `memory/` skip is for the web memory study.

Run `web_test_file_tools.py` as a guide for the api-level tests (it uses the web test harness, so it will not
run as is).

## Reviews and known limits

Reviewed by codex (gpt-6-astra, read-only) and a fresh Claude Opus agent: f1 (6 + 9 findings, fixed), f2 (1
must-fix: edit memory growth, fixed), f3 (both APPROVE, no must-fix), then one agreed one-line fix (size check
counts "\r\n" only in CRLF files). Known limits, not fixed: a lone "\r" in old/new can land in an LF file;
a huge old_string makes the forgiving line pass slow; a hidden folder named directly is searched;
`proc.wait()` after killing rg can block if rg is stuck on a dead disk.

Not built yet (planned on the web, from DeepSeek Harness): long tool output saved to a file with a short
preview; read-only tools run at the same time; a cheap-model search helper.
