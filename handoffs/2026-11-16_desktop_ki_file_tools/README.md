# Desktop KI file tools: list one folder, find by name, name the real files on a miss (2026-11-16)

For the GeoForge Desktop developers. From the server side (owner's request).

## What it is

The API agent's two KI file tools in `kiss/kiss_cli/api.py` now work like the GeoForge web agent's
(live there since 2026-11-05):

- `list_ki_files` lists **one folder** at a time: SKILL.md and dag.yaml first, then sub-folders with their
  file counts, then files. Hidden, cache and backup files are counted, not listed.
- `list_ki_files(pattern=...)` **finds files by name**: plain words (`weather`), or a pattern
  (`docs/s4_*`, `**/*.py`, `docs/`). Case is ignored.
- A **wrong folder or file name** answers with the real names nearby ("Did you mean ...").
- Every hint can be copied back as written: it keeps `ki="..."` in multi-KI chats and the `Demo/` prefix
  during intake.

Tool names are unchanged, so the flow gate needs no change. The intake list, `ki=` for other selected KIs,
and paged reading (`_read_text_page`) are kept as they were.

## Why

A small model (Qwen 27B) looped on the old tools. The old `list_ki_files` returned `(empty)` for a folder
that does not exist; the model asked for it 123 times and guessed 21 file names. The new answers stop that,
and they help every model (DeepSeek, Claude) too.

What the agent sees on the real MODFLOW6 KI:

| Agent asks for | Before | After |
|---|---|---|
| Top of the KI | 66 lines, every file | 19 lines: key files, folders with counts |
| Wrong folder `tools/calibration` | `(empty)` | an error naming the real folders in `tools/`, and `calibration.yaml` |
| Wrong file `docs/calibrate.md` | "no such file" | the same, plus how to search by name |

## How to take it

It is written for **`windows-version`** (made on `cf3b765a`, 2026-11-12), which has the newest desktop code.

- Pull request #2: branch `desktop-ki-file-tools` into `windows-version`
  (https://github.com/lzwei196/KISS-Knowledge-Infrastructure-for-Scientific-Simulation/pull/2), or
- the patch in this folder: `git checkout windows-version && git am ki_file_tools.patch`
  (11 commits: the port, then one commit per review round).

Files: `kiss/kiss_cli/api.py`, new `kiss/tests/test_ki_file_tools.py`, and two updated tests
(`test_flowgate.py`, `test_ki_intake.py`) that expected the old full listing.

`mac-version` has a different `api.py`; the change would need a hand merge there.
**Question for you:** `mac-version` has 5 desktop commits from 2026-10-01 (Wine setup, FSM2 reruns, data
approval, setup and completion fixes) that git cannot find in `windows-version`. Are they already in it by hand?

## Tests

Full suite `python -m pytest kiss/tests` on Linux (Python 3.12), before and after:

| | `windows-version` as it is | With this change |
|---|---|---|
| Failed | 244 | 244 (the same tests) |
| Errors | 329 | 329 (the same tests) |
| Passed | 6,978 | 7,018 |

The 244 failures and 329 errors are there without this change. Most are Windows-only tests on Linux. Two
groups may be worth a look on your side:
- "SHAW official Trial input bytes changed" (a large share of the setup errors): the SHAW test data does
  not match the KI files brought from `main` on 11-12.
- "An absolute existing selected Python is required" and similar: fixture setup on a machine without a
  selected Python.

## Review

Reviewed by codex (gpt-6-astra, read-only) and a fresh Opus agent, 10 rounds. The owner ended the loop
after round 10, when the findings had for some rounds been about constructed conditions only. The one
must-fix from the last round is fixed (commit `75f347b8`). Opus approved rounds 6, 8 and 10. All reviews are
kept on the server in `/home/server/kiss_jobA_review/`.

## Safety and time limits

- Everything stays read-only and inside the KI. Every read is resolved and checked to be inside the KI.
- Walks never enter folder links or Windows junctions. Junctions are found through the lstat reparse tag,
  which works on Python 3.11 (the Windows app build) as well as 3.12.
- One call has a 5 s budget for walking, matching and hints. After it, no new file-system read starts, and
  the answer says that only part of the KI was searched. At most 50,000 files and folders are looked at.
- Patterns: `**` once, plus once more at the end (`**/*.py`, `docs/**`, `**/tests/**`); at most 16 `*`;
  paths over 512 characters are not matched by path patterns (and the answer says so).

## Known limits (left on purpose)

These need conditions a normal desktop does not produce: a hostile program timed to swap folders, simulated
very slow disks, or unusual names.

1. **A folder swapped for a link at exactly the wrong moment** (a parent folder after its sub-folders were
   queued, or a folder swapped to a link and back while it is being read) can make outside **names** show in
   a listing. Contents never: reads are refused outside the KI. Closing this fully needs `dir_fd`, which
   Windows does not have.
2. **Slow disks:** the setup before the KI tools run (resolving the KI, workspace and project folders, and
   `execution.stop_requested`) and the intake `ReadMap.resolve` have no time check of their own, so on a
   very slow disk a call can take a few seconds longer than 5 s. `os.walk` itself also looks at link targets.
3. **A successful `read_ki_file`** reads the whole file through the existing `_read_text_page`, outside the
   5 s budget, as before this change.
4. A search that ends exactly at the 50,000-entry limit, or when the time runs out during the last folder,
   says "only part of the KI was searched" although everything was seen (cautious, not wrong).
5. Entries not checked before the time ran out are shown as "(not checked)" without a folder `/`.
6. Drive-like names such as `a:b.txt` are refused as absolute paths on every platform.
