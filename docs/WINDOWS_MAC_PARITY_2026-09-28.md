# Windows / mac source parity — 2026-09-28

## Source scope

- Windows baseline: `fbed40b08f2d7c552c5c332a912b5a65f3d8855c` (0.6.53).
- Previously imported mac checkpoint: `41817af`.
- Latest mac checkpoint integrated: `963164e8598d6c40ad6e0932dabecabd633d7acf`, 17 new commits. Remote head rechecked before final packaging.
- Main checked: `9e5e649e895bc21360df9cb883ae5ef3043effc7`. Its changes since the recorded KI snapshot are database API documentation, not a new model-library snapshot. `OBS_ACCESS_API.md` and the addendum are included; desktop integration documentation includes the newer mac work.
- Version: **0.6.54**, build label **windows-mac-parity-20260928**. This is a local Windows build, not a published GitHub release. September 27–28 mac work is an explicitly unreleased checkpoint on top of its September 19 release.

This is a real ancestry merge of mac-version into windows-version. Previously imported changes were reconciled against the recorded mac checkpoint, rather than replacing Windows files with the mac tree. Existing Windows-only changes and unrelated local stress-test artifacts were preserved.

## Update review

| Upstream changes | Windows integration |
| --- | --- |
| `17eb1eb`: installation manifests and verified runtime probes | Imported mac notes/recipes under their platform names; shared preflight and model-identity corrections integrated. Retained all Windows notes/recipes and dependency recovery. |
| `463f072`, `0f42157`: one-flow host acquisition | Imported acquisition owner, receipt-bound inputs, data contracts, database access/subsets and system KI; bundled netCDF4. |
| `1049d02`, `f1b89e5`: settings/database browser | Integrated sidebar settings, catalogue browser and MCP location; retained explicit Windows Kimi permission choice. |
| `efd2876`: audit scripts and ignore rules | Integrated scoped scripts/docs; did not run network/download campaigns or remove user data. |
| `49f8a4a`: native binary-kind test | Retained platform-correct executable fixtures, including a real Windows executable receipt test. |
| `3f2a568`, `1d8f3ee`: shared Flow and planner vocabulary | Imported shared contracts, vocabulary/aliases, forcing metadata and integrity manifest together. |
| `3edce27`, `232a86d`, `ea9b7bf`, `96ac8a5`: decision provenance | Integrated canonical decision schema, answer/review provenance, open-question gates and parity tests. |
| `bdf2522`: evidence/execution/review/status owners | Integrated all owners and tests, with Windows locking, path, process-tree and NTFS cache fixes. |
| `9f1ccfa`, `45ac25a`: sequential questions and project inputs | Integrated API/CLI question handoff, custom answers, project-bound paths/runtime ownership, safe uploads and planning audit. |
| `963164e`: named project folders | Integrated editable names, matching path preview/creation, Chinese names and stable existing-project identities. |

## Windows-specific corrections found during integration

1. The receipt registry imported `fcntl`, unavailable on Windows. It now uses a bounded Windows byte-range lock with fail-closed errors; four real concurrent processes preserve all 20 registry updates.
2. Absolute drive paths, rooted paths, POSIX-style project-relative paths and Claude read/execute grants are handled explicitly. Windows interpreter names such as `python.exe`, `Rscript.exe` and `powershell.exe` cannot masquerade as compiled model binaries.
3. Frozen CLI flow/database helpers no longer depend on `py -3` or Python on PATH. A bundled console bridge executes only the shipped IPC adapters. Local-fixture tests exercise database queries and planning questions with real UTF-8 Chinese text and process-scoped capability headers. The bridge does not expose persistent database credentials.
4. Frozen Python ignores the usual UTF-8 startup environment flag; bridge stdout/stderr are explicitly UTF-8. This fixed a failure reproduced against the actual compiled bridge, not just source mocks.
5. Shared execution cancels Windows child process trees, hides incidental console windows and reports the missing executable path. Portable runtime/DLL environment handling remains in verification and execution.
6. Windows Python 3.11 reports creation time in `st_ctime`. Project-status caching now reads NTFS ChangeTime so a same-size edit with restored mtime cannot retain stale proof status.
7. The import-contract scanner preserves optional imports and Windows helper signatures while adopting real-import/isolated-startup verification. Explicit Python/native hybrid contracts remain supported; an interpreter or unrelated dependency alone is not model-installation proof.
8. Deferred provider checks remain non-blocking. Settings opened before detection completes now refreshes provider and proxy cards without losing the saved default. Provider help links strip surrounding punctuation; folder wording no longer says Finder on Windows.

## Preserved Windows behavior

- Self-contained Python 3.11 x64 application with browser frontend and Windows tray; no return to the freezing embedded webview path.
- Native clipboard support, tray exit, portable dependency repair, setup process cleanup and unlimited installation-agent step count.
- Kimi remains disabled under unsupported project-scoped Windows security; the user can explicitly accept full-computer access in Settings. This integration did not change the user's permission choice.
- **127 scientific KIs**, **127 Windows installation notes**, **23 Windows recipes**. The new GeoForge Database system KI is counted separately.
- Auto-fetch remains **main**, not windows-version or mac-version. Recipes remain platform-specific; imported Homebrew/mac build instructions are not represented as Windows installation successes.
- User settings, credentials, model installation locations and existing projects are not migrated or overwritten by source integration or acceptance tests.

## Verification

Source regression and packaged checks are run on Windows with Python 3.11. Source tests isolate user-home/settings/flow registries; packaged checks use temporary profiles and disable database credential access. No paid provider request is made.

- Desktop suite: **1,182 passed, seven skipped, 286 subtests passed** on the final rerun (250.79 seconds). The embedded release manifest records the earlier completed 1,181-test run plus the 15-test focused check; this report records the final expanded suite.
- Shared package/Flow suite: **313 passed, six skipped**. Skips cover unavailable external/server references; they are not counted as passes.
- Final focused Windows suite: **15 passed**, including UTF-8 streams, interpreter rejection, IPC/question contracts and settings link/startup behavior.
- Frozen executable: **passed**, including all 127 bundled KIs, recipe-copy consistency, included Python DLL, harness/Flow loading, calibration backend imports, 11 HTTP routes, main KI-update source and both console bridge modes without Python on PATH.
- Frozen bridge transport: **passed against a local HTTP fixture** for Chinese database queries and planning questions. This is not a live DeepSeek/Codex/Claude/Kimi turn or a live database service acceptance test.
- Browser UI: checked the compiled app, Chinese project creation/path preview, Settings and database status. Testing found the help-link punctuation and early-settings provider-card race and drove the fixes above. No token or permission was changed.
- Installer acceptance: **passed**. The production Setup executable installed silently into an initially absent test directory with spaces (exit 0), without shortcuts or restarting applications. That installed copy passed the complete frozen smoke check. The Desktop EXE, bridge EXE, manifest and frontend matched the portable bundle byte-for-byte. Uninstall returned 0; the test executable and registration were removed. No pre-existing GeoForge registration was present; existing source/portable installations were not touched.

Local raw evidence lives in `.parity-check-20260928/` (`app-tests.xml`, `shared-tests.xml`, `windows-frozen-smoke.json`, installed smoke report and UI screenshot), with `.parity-*-20260928.log` build/test logs in the repository root. These transient profiles and build directories are not source-control inputs.

## Known limits — do not describe this as all scientific workflows certified

The mac checkpoint itself still documents incomplete full plan-to-download acceptance, scientific-recommendation evidence, parent-product/subset wording and source-choice/inventory consistency. AquaCrop period and database-activation gating remain tracked upstream. See `PLANNER-IMPLEMENTATION-2026-09-28.md`, `issues/PLANNER-CATALOGUE-ACCEPTANCE-2026-09-28.md` and `issues/AQUACROP-SCOPE-AND-DATABASE-GATING-2026-09-28.md`.

This turn is source parity, Windows regression and packaging acceptance. It does **not** rerun installation, simulation or calibration of all 127 KIs, or certify live DS/CLI agent behavior. The manifest's 91 installed / 35 needs-user / one failed snapshot is dated **September 7**, retained as historical evidence rather than relabeled as fresh results. Calibration import readiness does not imply that project-specific observations or a valid scientific setup exist.

## Final local artifacts

The source tree, portable application directory and Windows Setup executable are local outputs. No push, tag or GitHub asset replacement is performed by this integration request.

- `dist-0.6.54-20260928/GeoForge Desktop 0.6.54 Windows/GeoForge Desktop.exe`
- `release-0.6.54-20260928/GeoForge-Desktop-Setup-v0.6.54-Windows-x64.exe` — 129,390,166 bytes; SHA-256 `ce5b6b3424f5d3363e4e3ebc78b9d1ca0063479d71140472beba267ec7c8312f`.
- `release-0.6.54-20260928/GeoForge-Desktop-v0.6.54-Windows-x64.zip` — 191,026,628 bytes; SHA-256 `0ec0af9b9263d23d411acb751fe605590d46963bfc3af62a8989c61882a9093e`.
- Structured summary: `WINDOWS_MAC_PARITY_2026-09-28.json` beside this report.

The temporary installed copy was removed after testing; its logs remain and it can be recreated with the retained installer. Older user stress-test downloads and model installations were not deleted. Temporary test servers and the browser test tab were closed.
