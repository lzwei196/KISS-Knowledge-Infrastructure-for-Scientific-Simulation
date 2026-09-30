# Windows 0.6.54 — known issues (2026-09-30)

Open issues known when `windows-v0.6.54` was published, each re-verified against the code at `6410305` (the released code) with reproductions where practical. GeoForge marks a project **Completed** only when every approved step has a passing, signed run record; issue 1 is the one case where the *approved* data itself can differ from what runs.

## 1. Approval can record one data source and download another — HIGH

**What happens.** A plan names the data for an input in two places: the data list (which drives the download and the model run) and the "data source" choice shown on the approval card. GeoForge never checks that they match, and the card silently drops any source that is not in the GeoForge Database catalogue (for example the NASA POWER weather provider).

**How a user hits it — with the normal Approve button.** The planner recommends a non-catalogue source (say NASA POWER) while the data list pins a catalogue dataset (say CMFD). The card hides the NASA POWER option, pre-selects nothing, and still says "defaults to NASA POWER unless you pick another". The user clicks **Approve**; no choice is sent; GeoForge signs an approval recording *both* "NASA POWER accepted" and "CMFD", downloads CMFD, and gives the execution agent both as instructions. When every option is non-catalogue the data-choice row disappears from the card entirely, yet the approval still signs the value. The same mismatch happens for catalogue sources whenever an approval arrives without the choice attached (API or other clients); in the browser that case is masked because a pre-checked choice is re-pinned before signing. A real planning session (APEX, Harbin; `docs/issues/APEX-PLAN-AND-ACTIVITY-2026-09-27.md`) produced exactly this plan shape.

**Impact.** The wrong forcing dataset can be used in a scientific run, and the signed approval record cannot be used to audit which data the user accepted. The agent-chosen value is also labelled as a "KI protocol default" in the record.

**Where.** `kiss/kiss_cli/plan_review.py`: `_data_choices` drops non-catalogue ids (~313-316); `picked` is never checked against the options or the item (~337); with no `choices` in the action nothing is re-pinned (~107-126); `decision_records` signs the item (~698-710) and the choice (~738-744) without cross-checking. `ki_tools_common/.../flow/plan.py` only checks that `options` is a list. Existing tests do not cover a choice that disagrees with its item.

**Fix direction.** (1) Before issuing the card, send back any plan whose data-source choice disagrees with the inventory item it governs, or whose pick is not among its options. (2) Show non-catalogue sources as selectable "external" options instead of dropping them. (3) When Approve carries no choice, re-pin to the card's shown recommendation (as the browser path does) or refuse. (4) In `decision_records`, refuse to sign a choice whose value differs from its item.

## 2. Stop / Exit miss agent jobs started through Git Bash wrappers — medium

**What happens.** GeoForge stops work on Windows by following parent/child links between processes. When an agent CLI (Claude Code runs commands through Git Bash) starts a job with `nohup`, and also `timeout`, `env`, `sh -c` or a bash script, Git Bash breaks that link immediately, even while the shell is still running. **Stop** and tray **Exit** then leave that job running until it ends or is killed in Task Manager. The long-job instructions tell agents to use `nohup`, so long ad-hoc runs are the likely case. Receipted model runs (`run-tool`) are stopped normally; files a stray job writes later block **Completed** rather than count.

**Fix direction.** Start each agent CLI and tool in its own Windows Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (no breakaway allowed; assign while suspended), and stop by terminating the job; keep the snapshot walk as a fallback. A prototype stopped every escaped job, including after a Desktop crash.

## 3. Setup turns can run the full scientific model — medium

**What happens.** After approval, software setup is handed to an agent. "Install only; do not run the model" is enforced only for the separate installation-only test, not for in-project setup. In the end-to-end test the setup agent ran the whole FSM2 example and left about 15 MB of results and scripts in the shared software folder. Those results carry no receipt and cannot mark a project complete, but they cost time and tokens and clutter a folder every future project reuses.

**Fix direction.** Treat a setup turn inside a project like installation-only for commands (installation steps and bounded startup probes only); the host already runs the real preflight afterwards.

## 4. Calibration opens a console window per model evaluation — medium

**What happens.** In the packaged app, each calibration evaluation starts the model without hiding its console, so a black window appears for every evaluation (hundreds or thousands per calibration) and stays until that evaluation ends. Closing one makes that evaluation count as a failure. Running from source does not show it.

**Fix direction.** Give the calibration worker one windowless console that model runs inherit (`AllocConsoleWithOptions` with no window where available), without changing the pinned calibration engine.

## 5. Shared Flow fixes not yet on the server; untested areas — medium (process)

- `ki_tools_common/flow/UPSTREAM.json` lists 16 pending edits to the shared Flow package. If the server copy is synced over it ("server = reference") before they are carried upstream, the Windows build breaks: the Flow package would fail to load on Windows (POSIX-only locking), projects could never reach **Completed**, catalogue cards with non-ASCII text would be silently dropped on Chinese Windows, and Claude file permissions would be written in a form Windows does not match. Carry them upstream before the next sync.
- Exercised end to end in the compiled Windows app: FSM2 with the DeepSeek API only. **Not yet exercised:** Codex / Claude / Kimi CLI agents live, GeoForge Database downloads, calibration, and the other KIs. The Windows model-installation snapshot (91 installed / 35 need user action / 1 failed) dates from 2026-09-07.

## 6. Smaller items — low

- **Release tags.** Pushing a `v*` tag (for example `v0.6.55`) from `windows-version` would publish a public multi-platform release whose Windows build is not the tested one. Windows releases use `windows-v*` tags; pushing the branch triggers nothing.
- **No raster reader in the packaged app** (rasterio / pyproj / rioxarray excluded): a delivered GeoTIFF subset covering the wrong area is kept as "pending" rather than rejected.
- **Outdated instructions** inside the bundled GeoForge Database KI docs still name removed tools.
- **Whole-product sizes** from the catalogue (for example CMFD ≈ 649 GB) can be quoted to the planner as if they were the project's download.
- **netCDF4 compression-filter plugins** cannot load in the packaged app (their DLLs ship under different names); compressed netCDF variables using those filters would fail to read.

See also: [Windows end-to-end test](../WINDOWS_E2E_FSM2_2026-09-30.md), [Windows / mac sync](../WINDOWS_MAC_SYNC_2026-09-30.md).
