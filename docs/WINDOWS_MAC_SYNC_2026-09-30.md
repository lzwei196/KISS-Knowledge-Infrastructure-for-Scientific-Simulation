# Windows / mac sync and Windows fixes — 2026-09-30

## Scope

- Windows baseline: `420958db5e529f116cd29992266f0f8c9f126d99` (0.6.54 parity build, 2026-09-28).
- Integrated mac commit: `bc7882564e4aedea61f080c43cb0adb5e9b4ec71` — the 2026-09-28/29 flow fix round (one commit, 56 files). Remote heads were fetched on 2026-09-30; `main` (`9e5e649`) and the other branches are unchanged since the previous sync.
- Version stays **0.6.54**; build label **windows-mac-sync-20260930**. Local Windows build: no push, tag or GitHub release.

This is an ancestry merge of `mac-version` into `windows-version`. Eleven files conflicted; every conflict kept both sides (mac's new Stop/turn plumbing plus Windows paths, runtimes, paging and UTF-8 handling).

## What the mac round brings

Downloads continue without Project Status open and survive recovery; Stop covers the whole turn and is recorded as `stopped`; each step stands on its latest attempt; interview answers are saved host-side and credited at signing; uploads in `inputs/user/<input>/` are bound at Approve; the agent download tool is limited to planned inputs GeoForge does not fetch; GeoForge Database is used only when activated (fixes the audit's "database off is not enforced at review" defect); planning asks the study period and validation separately, so a KI example's period is no longer proposed as the project's scope (the AquaCrop defect). Calibration and installer downloads now run in supervised child processes. `flow/UPSTREAM.json` pins the shared Flow package against the server.

## Windows problems found and fixed

1. **Stop did not reach descendants on Windows.** mac's Stop walks POSIX process groups (`ps`, `killpg`); on Windows it ended only the direct child, and the mac notes state no Windows mechanism was added. Windows now snapshots the process tree with the Toolhelp API before anything is killed and terminates each process through one handle that also verifies its creation time and liveness, so a recycled PID is never signalled. Children of a root that already exited (a `.cmd` shim, a build driver) are reached. GeoForge's own run-tool wrapper keeps the 5 s grace to write its `stopped` receipt; agent CLIs, which receive no signal on Windows, are ended at once. `taskkill /T` remains only as a fallback when no process table can be read. Verified with real processes (`tests/test_windows_process_tree.py`).
2. **Tray "Exit GeoForge" skipped cleanup.** It called `os._exit(0)`, bypassing the new stop-everything hook, so calibration/download workers and agent CLIs outlived the app. Exit now runs that cleanup first.
3. **Chinese-locale (GBK) text handling.** The packaged app does not run in Python UTF-8 mode, and earlier Windows test runs set `PYTHONUTF8=1`, which hid a class of bugs. Receipts were read in the locale codec, so any receipt containing `—` or Chinese failed to record; planner YAML cards with non-ASCII text were silently skipped; KI docs and several child-process outputs were decoded as GBK. Our own files are now read and written as UTF-8, child output uses the correct codec with `errors="replace"`, and the whole suite runs under the real locale.
4. **Agent launchers under a Chinese user name.** `cmd.exe` decodes `.cmd` files in the console's *current* code page, which Codex and Claude Code's PowerShell switch to 65001. Launchers are now pure ASCII: a non-ASCII target is named by its 8.3 alias or through an ASCII junction beside the launcher (reached via `%~dp0`, which `cmd.exe` expands in Unicode); a venv keeps its `pyvenv.cfg` layout. Verified under both the OEM and the UTF-8 console code page.
5. **Installer quoting.** mac's cancellable install path ran string build commands as `[cmd, "/c", cmd]`, whose list quoting garbles every quoted argument for `cmd.exe`. It now passes the exact string `shell=True` builds. The directory-junction fallback (always broken by the same quoting) now uses `_winapi.CreateJunction`.
6. **Windowed-exe children.** A crash in any background command of the windowed exe opened PyInstaller's modal traceback dialog, so the parent (which waits without a timeout) hung. Every command except the app itself now exits with a traceback on stderr. The agent bridge parses arguments without touching process-wide streams (there are none in the windowed app). Scratch-directory cleanup on Windows no longer turns a sharing violation into a failed result.
7. **KI library update guard (Windows only).** The updater pulls from `main`, which has none of the 127 Windows installation notes or 23 Windows recipes. A snapshot that would remove current-platform guidance is refused (state `kept`, reason shown in Library and the launch notice); an install that had already activated such a snapshot falls back to the bundled library. macOS/Linux behaviour is unchanged.
8. Smaller fixes: executable named in "could not launch" errors (Windows' WinError text omits it); bounded retries when Windows refuses an atomic replace while a reader has the file open; the long-job rule says `nohup` on Windows; the frozen CLI lists all 12 Flow modules; the shared-package pin lists the Windows edits to carry upstream; the root `.gitignore` covers build, release and stress-test folders (`git add -A` previously would have staged 15 GiB).

## Verification

Source tests ran on Windows 11 with Python 3.11 under the real cp936 locale (no `PYTHONUTF8`), isolated profiles and a temporary Flow registry; no paid provider call and no network download.

- Desktop suite (`kiss/tests`): **1,449 passed, 35 skipped, 288 subtests passed, 0 failed** (329 s), on the committed tree. The 0.6.54 parity build recorded 1,182 passed under UTF-8 mode.
- Shared package (`ki_tools_common/tests` and `ki_tools_common/ki_tools_common/tests`): **326 passed, 7 skipped, 0 failed**. Skips are unavailable server references and POSIX-only cases; they are not counted as passes. `tests/test_debug_framework.py` is a standalone script, not a pytest module, and is not included.
- Frozen bundle (built from `dacc126` with PyInstaller 6.22.2): **passed** — 127 KIs, 127 Windows notes, 23 recipes, python311.dll, harness/Flow/calibration imports, 11 HTTP routes, both console-bridge modes without Python on PATH, and the Unicode bridge against a local fixture. The real windowed exe was also given a failing `_install-download-worker` request: it exited with status 1 and a traceback in 0.3 s instead of opening a dialog.
- Installer: silent install into a test folder whose path contains a space (exit 0), the same smoke check on the installed copy (passed), installed executable and registration version 0.6.54, all **4,789 installed files SHA-256-identical** to the portable bundle, silent uninstall (exit 0) removing the executable, registration and folder. The installer always creates its Start Menu shortcut; the uninstaller removed it. No existing GeoForge installation was present or touched.
- Raw evidence (local, git-ignored): `release-0.6.54-20260930/` holds `Windows-release-validation.json`, both smoke reports, the JUnit XML of both suites, the PyInstaller/Inno Setup build logs, the install/uninstall logs and `validate-final.ps1`, which reproduces the installer check.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `GeoForge-Desktop-Setup-v0.6.54-Windows-x64.exe` | 129,385,385 | `6ba1d4530a5175b386bf22e78e680fddaec1274a28a0265d129f94a8a507e653` |
| `GeoForge-Desktop-v0.6.54-Windows-x64.zip` | 188,204,213 | `544e75963fc863fcdf310af483e781d4e2d4d99a2b942d21e4d320f73c0ba00e` |

**Superseded:** the package below was rebuilt from `b443c16` after the end-to-end test fixes; see `WINDOWS_E2E_FSM2_2026-09-30.md` for the current artifacts.

To publish (not done): push `windows-version`, tag `windows-v0.6.54` (the `windows-` prefix keeps the older multi-platform `v*` workflow from firing), and upload both files, `SHA256SUMS-Windows.txt` and `Windows-release-validation.json` to the GitHub release.

## Known limits

- Detached jobs an agent started with `nohup … &` whose launching shell already exited are not reached by Stop or Exit (no living parent link). A Windows Job Object per agent would cover them and Desktop crashes; not implemented.
- The calibration engine starts each model evaluation without `CREATE_NO_WINDOW`, so console-subsystem models can flash a window per evaluation (pre-existing; needs a vendor-framework change).
- In a source (not frozen) run from a Python venv, graceful Stop kills the venv launcher's real interpreter child, so that attempt's `stopped` receipt can be lost. The packaged app is unaffected.
- No live DeepSeek/Kimi/Codex/Claude turn, authenticated GeoForge Database download, model simulation or calibration was run. The Windows model-installation snapshot remains the 2026-09-07 one (91 installed / 35 needs-user / 1 failed).
- Shared Flow edits are listed in `flow/UPSTREAM.json` but not yet carried to the server.
