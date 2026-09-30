# Windows 0.6.54 — known issues (2026-09-30)

Open issues known when `windows-v0.6.54` was published. None lets a wrong result pass silently as a finished project: GeoForge marks a project **Completed** only when every approved step has a passing, signed run record. Ordered by importance.

## 1. Approval can record one data source and use another — medium-high

**What happens.** The approval card lets you choose the data source for an input (for example dataset B instead of the agent's draft A). When you click **Approve** in the app, your choice is sent and the plan is switched to B before signing, which is correct. If an approval arrives *without* the choice attached, GeoForge still signs: the signed decision says "B" while the data list, and so the download and the model run, still use "A". Nothing checks that the two agree. Separately, a source that is not in the GeoForge catalogue (for example NASA POWER weather) is dropped from the card, so it cannot be chosen.

**Status.** Confirmed in the code at `420958d` (`kiss_cli/plan_review.py`: `_data_choices`, approve handling without a `choices` map, `decision_records`; `flow/plan.py` only checks that options are a list). The mac 2026-09-29 round changed approval handling (uploads bound at Approve, Database activation rechecked); whether it closed this gap is being rechecked. The normal Approve click is not known to trigger it.

**Fix direction.** At signing, refuse or re-issue the card when a decided data source differs from the inventory item it governs; keep non-catalogue sources as selectable options.

## 2. Stop / Exit do not reach detached agent jobs on Windows — medium

**What happens.** GeoForge stops a tool, an agent CLI and everything they started by walking the Windows process tree. A job an agent started with `nohup … &` whose launching shell has already exited has no living parent link, so **Stop** and tray **Exit** do not reach it; it keeps running until it ends or is killed in Task Manager. The long-job instructions tell CLI agents to use `nohup`, so long ad-hoc runs by Codex/Claude/Kimi are the likely case. Receipted model runs (`run-tool`) are stopped normally, and files a stray job writes later block **Completed** rather than count.

**Fix direction.** Put each agent CLI (and optionally each launched tool) in a Windows Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`; Stop terminates the job. This also covers a Desktop crash.

## 3. The installation agent may run a model simulation during setup — low

**What happens.** In the end-to-end test the setup agent ran FSM2's example simulation while installing it, although the KI says not to; outputs were left in the software folder. No host rule prevents model execution in setup turns. Such runs cannot count toward a project's completion, so the cost is time, API tokens and clutter.

**Fix direction.** In setup turns, allow only installation commands and bounded startup probes for the model binary (as installation-only tests already do).

## 4. Calibration can flash console windows on Windows — low

**What happens.** The calibration engine starts each model evaluation without `CREATE_NO_WINDOW`; console-subsystem models can open a window per evaluation. Cosmetic.

**Fix direction.** Give the calibration worker one hidden console that children inherit, or pass `CREATE_NO_WINDOW` in the pinned runner.

## 5. Shared Flow changes not yet carried to the server; untested areas — process

- `ki_tools_common/flow/UPSTREAM.json` lists the Windows and 2026-09-30 edits to the shared Flow package (receipt-registry locking on Windows, UTF-8 file handling, completion evidence, validator message). If the server copy is synced over this package without them, those fixes are silently undone, including the one that lets projects reach **Completed**.
- Exercised end to end on Windows: FSM2 with the DeepSeek API (plan, install, run, results, Completed). **Not yet exercised** with the compiled app: Codex / Claude / Kimi CLI agents live, GeoForge Database downloads, calibration, and the other KIs. The Windows model-installation snapshot (91 installed / 35 need user action / 1 failed) dates from 2026-09-07.

## 6. Smaller known items

- Pushing a `v*` tag from `windows-version` would start the older four-platform release workflow; Windows releases use the `windows-v*` tag.
- The packaged app does not include raster readers (rasterio / pyproj / rioxarray), so it cannot inspect raster file contents itself.
- netCDF4 compression-filter plugins show unresolved DLL warnings in the build (their libraries ship under mangled names).
- The planner can quote a catalogue product's whole size (for example CMFD) as if it were the project's download.

See also: [Windows end-to-end test](../WINDOWS_E2E_FSM2_2026-09-30.md), [Windows / mac sync](../WINDOWS_MAC_SYNC_2026-09-30.md).
