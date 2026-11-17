# Local patches to the vendored engine (kiss_cli/, GeoForge Desktop linux-version ec46fe47)

Everything else in kiss_cli/ is byte-identical to that commit (see kiss_cli.SHA256, regenerated after
each patch; the originals' hashes are in kiss_cli.SHA256.orig).

1. `kiss_cli/api.py` `execute_tool` (2026-10-21): `cfg.roles["argument_roots"]` — a list of extra folders
   KI tool arguments may point into (the server's data folders). The desktop allows only the project,
   the KI and the binaries folder. Owner asked for the agent's tool set to match what server chats need.

2. `kiss_cli/api.py` KI file tools (2026-11-05): `list_ki_files` lists ONE folder (key files first,
   sub-folders with file counts), leaves hidden / cache / backup entries out but counts them, takes a
   `pattern` to find files by name (plain words, or a glob; in the whole KI or under `subdir`; hidden
   trees searched only when the pattern names them, or once more when nothing visible matches), and a missing folder names the real folders nearby. `read_ki_file` on a missing name answers "Did you mean ...". Shaped like Gemini CLI / Qwen
   Code's list_directory + glob. Same tool names, so the flow policy (`ki_tools_common/flow/policy.py`)
   and gate.py are unchanged. Also `kimem/events.py`: a READ's target falls back to `pattern`.

3. `kiss_cli/api.py` + new `kiss_cli/filetools.py` file tools (2026-11-17). Adapted from DeepSeek Harness
   (MIT, deepseek-ai/deepseek-harness @ 39163dd3: tool-fs read-render.ts, tool-fs-search grep.ts, fs-local
   applyLiteralEdit) and Qwen Code (Apache-2.0, QwenLM/qwen-code @ 6db070d7: utils/editHelper.ts,
   tools/priorReadEnforcement.ts). `read_ki_file` / `read_project_file` / `read_work_file` answer numbered
   lines with `offset` / `limit` (at most 2000 lines, 60,000 / 120,000 bytes, long lines cut at 2000 chars)
   and say where to continue; `read_project_file` takes files up to 200 MB (was 5 MB) since it reads a
   window; binary files are refused. `list_project_files` / `list_work_files` take `pattern`
   (list_ki_files' rules) and say when the list was cut. New `search_files` (ripgrep --json, argv only,
   case ignored, hidden/cache/backup and project `memory/` left out, 200 matches, 20 s). New
   `edit_project_file` (old_string -> new_string, must match once unless replace_all; forgiving match for
   curly quotes, dashes, odd spaces and trailing spaces, indentation kept; the file must have been read or
   written earlier in the same turn and be unchanged since; same write rules as write_project_file).
   gate.py: `search_files` in WEB_TOOLS and READ_ONLY_TOOLS, `edit_project_file` in WEB_TOOLS. The desktop
   flow policy (ki_tools_common/flow/policy.py) does not list the two new tools yet, so a desktop flow
   hides them.
