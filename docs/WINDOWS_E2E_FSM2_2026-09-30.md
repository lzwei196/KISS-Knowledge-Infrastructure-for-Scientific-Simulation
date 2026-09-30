# Windows end-to-end test: FSM2 Alptal — 2026-09-30

## Setup

- Compiled Windows app (PyInstaller, Python 3.11, 0.6.54), run as `GeoForge Desktop.exe gui` with a dedicated workspace `D:\GeoForge-E2E-20260930`, driven through its real browser UI like a user.
- Provider: DeepSeek API (`deepseek-chat`), the user's saved settings. No GeoForge Database access.
- Request: run the official FSM2 Alptal example (winter 2004-2005, open and forest points, default physics), produce snow depth and SWE series with a plot, report peak SWE and melt-out per point.
- FSM2 was not installed in the workspace, so the test included installation.

## Run 1 (build from `dacc126`) — found five defects

What worked: chat and named project folder creation; sequential planning questions (melt-out definition) with the answer saved and credited; plan review and the Flow gate refusing an unexecutable plan; plan modification; **installation** (DeepSeek cloned the pinned FSM2 source, staged the private WinLibs compiler, compiled `FSM2.exe`, preflight passed, `status.json` ok); a real `FSM2.exe` run under a receipt.

What failed, each confirmed from files and code:

1. **No desktop project could reach COMPLETED.** `receipts.evidence()` counted `calibration/framework.json`, which the host writes into every chat at creation, as an unreceipted output (and later `artifacts/project-view.json`, which the host writes when the agent publishes a Project View). Fixture-based tests never create either file.
2. **Declared inputs counted as outputs.** Input files the approved inventory names under `inputs/` were also "unreceipted", and the notice told the user to remove their own inputs.
3. **FSM2 parser mislabelled every multi-point column.** `parse_fsm2_output.py` assumed point-major order; FSM2 writes Fortran arrays variable-major (and `Tsoil(Nsoil,Npnts)` column-major). "SWE" held flux values, and its range checks never ran for multi-point output, so the wrong CSV "passed". A column-count mismatch was silently "assigned what we can".
4. **The official example could not run inside a project.** The namelist names its forcing relatively, the staging step had no tool, and the execution agent may not write `runs/`, so the model ran in the installed software folder (outputs left there). There was no receipted way to compute peak SWE and melt-out.
5. **Plan validator error hid the field name** (`'ready' but names no local file`); the agent tried `path`, `files` and `local_path` and had to ask the user for `local_paths`.

The agents behaved well throughout: they refused to report numbers from mislabelled columns, refused to weaken the gate or invent paths, and stated limits honestly. The Flow gate correctly refused completion when the approved run step had no passing receipt.

## Fixes

- `flow/receipts.py`: host bookkeeping (`calibration/framework.json`, `artifacts/project-view.json`) and approved-inventory input files under `inputs/` are not unvouched outputs; a result cannot be declared into that set (only `inputs/` paths count). Regression test in `tests/flow/test_flow_core.py`; recorded in `flow/UPSTREAM.json` for the server.
- `flow/plan.py`: the validator message names `local_paths`.
- FSM2 KI: `parse_fsm2_output.py` names multi-point columns variable-major, fails loudly on a column-count mismatch, checks every point, and gains `--metrics` (peak SWE, peak depth, melt-out = first snow depth 0 after the SWE peak, or an explicit "snow remains at record end") and `--plot`; `run_fsm2.py` stages the namelist's relative forcing into `--run-dir`; `SKILL.md` documents both. Verified against the real two-point output (densities 362 and 305 kg m⁻³ at peak).
- `web/app.html`: after an app restart a started chat showed a local CLI instead of its API provider, because the provider kind was marked synced before provider detection finished; the next message posted that CLI, the server correctly refused to switch a locked chat (409), and the message was dropped with a misleading "connection stopped" note. Fixed, with a Node regression test that fails on the old page.

## Run 2 (rebuilt app with the fixes) — COMPLETED

Fresh chat, same request, same user choices, no manual file handling:

1. Intake → one planning question (study period: shipped case, recommended) → plan with three executable steps (preflight, `run_fsm2.py`, `parse_fsm2_output.py --metrics --plot`), no "cannot execute" items → approved on the first card.
2. `run_fsm2.py` staged the forcing into `outputs/FSM2/alptal_0405/` and ran the installed `FSM2.exe`; the parser wrote `series.csv`, `metrics.csv` and `snow.png`. Both receipts passed validation.
3. Flow state **COMPLETED**: assurance cryptographic, 5 bound receipts, 0 missing steps, 0 unreceipted artifacts, 0 rejected receipts.

| Point | Peak SWE | Peak SWE time | Peak depth | Melt-out |
|---|---:|---|---:|---|
| Open (VAI 0) | 348.2 kg m⁻² | 2005-03-17 08:00 | 1.138 m | 2005-04-05 12:00 |
| Forest (VAI 3.96, 25 m) | 155.7 kg m⁻² | 2005-03-15 09:00 | 0.579 m | 2005-03-27 14:00 |

These match an independent calculation from the raw `Alptal_stat.txt`. The open site holds 2.2× the forest SWE and melts out 9 days later, as expected for canopy interception and shading. This is a forward run of the official example, not a validation against observations.

## Not covered

- Other models, the GeoForge Database, CLI agents (Codex/Claude/Kimi) and calibration were not exercised.
- Installation was tested in run 1 only; run 2 reused the verified install in the same workspace.
- Run 1's first execution left `Alptal_*` output files in the installed FSM2 source folder (`fsm2\binaries\FSM2\source\repo`); they are harmless and were left for inspection.
