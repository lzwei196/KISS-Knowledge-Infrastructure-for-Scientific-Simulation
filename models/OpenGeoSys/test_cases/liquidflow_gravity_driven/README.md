# OpenGeoSys foundation test case: LiquidFlow GravityDriven

## What it is
The official OpenGeoSys benchmark `Tests/Data/Parabolic/LiquidFlow/GravityDriven`
(ctest name `LiquidFlow_GravityDriven`). Water sits in a 1 m x 1 m 2D box under gravity.
The top is held at pressure 0. The model solves for pressure and Darcy velocity. The right
answer is known: pressure grows with depth (p = rho g depth, 9810 Pa at the bottom) and
the water does not move (velocity 0).

## Source
- Repo: https://github.com/ufz/ogs, master commit `a5c00a5059a8704fafb64cdf1756494ace6b727f` (2026-03-24).
- Files in `inputs/` are byte-for-byte the git HEAD versions (`git show HEAD:...`), not changed.
  Only the three files the case needs are kept: `gravity_driven.prj`, `gravity_driven.gml`, `mesh2D.vtu`.
- Licence: OpenGeoSys LICENSE.txt (BSD-3-Clause style), Copyright (c) 2012-2026 OpenGeoSys Community.

## Engine
OpenGeoSys 6.5.7 (`ogs`, serial, pip wheel build) and `vtkdiff` from the same install.
Server path: `/home/server/knowledge-dissection-toolkit/auto_dissect/_work/OpenGeoSys/venv/bin/`.
Note: the benchmark files come from master (newer than 6.5.7); this case runs and passes on 6.5.7.

## How to run
```
python run_reference.py [--ogs-bin PATH] [--vtkdiff-bin PATH]
```
Binary lookup: argument -> `$OGS_BIN` / `$VTKDIFF_BIN` -> `which` -> next to ogs -> server default.
Needs python with numpy and meshio (e.g. `/mnt/disk1/Hydrocraft_server/python_env/bin/python`).
The script copies the inputs to a fresh temp dir, runs ogs through the KI tool
`tools/run_ogs.py`, reads pressure stats with the KI tool `tools/parse_ogs_output.py`,
runs the official vtkdiff checks, compares with `expected.json`, and deletes the temp dir.
It sets `OMP_NUM_THREADS=1` in the run environment (if not already set); this does not change
any input file, and a run with all threads gave the same result. Takes about 1 second.
Exit codes: 0 PASS, 2 checks failed, 3 engine or python package missing.

## Expected results
The reference is official: the analytic fields `AnalyticPressure` and `v_ref` that ship
inside `mesh2D.vtu`. The official test (`ProcessLib/LiquidFlow/Tests.cmake`) runs
`vtkdiff mesh2D.vtu <output> -a AnalyticPressure -b pressure --abs 1e-8 --rel 1e-8` and the
same for `v_ref` vs `v`. `expected.json` has 11 checks: ogs return code, both official
vtkdiff checks, max point error of pressure and velocity (tol 1e-8), pressure max 9810,
min 0 and mean 4898.944397332519 (all read from the official analytic field), node count 409,
2 output files, final time 1 s.

Seen on 2026-10-05 (two runs, same numbers each time): pressure max error 6.9e-11 Pa,
velocity max error 2.9e-19 m/s. PASS.

## Known KI gaps (not fixed here)
- `run_ogs.py` keeps only the first 500 characters of the ogs log, so the ogs end line
  ("OGS terminated with exit code 0") cannot be checked through the tool; the case uses the
  return code and the tool's `status: success` instead.
- `run_ogs.py` warns "t_end very short, did you forget days->seconds" and "storage = 0, no
  time change" for this case. Both are false alarms here: the benchmark is a steady case
  on purpose.
- `run_ogs.py` has no way to compare output to a reference (no vtkdiff step); the case
  calls vtkdiff itself.
- `parse_ogs_output.py --stats`: the JSON summary `pressure_summary` gives min/max/mean of the
  per-step means (e.g. "max" 4898.9), not of the field; the per-step CSV rows are right and
  are what this case uses. The ogs .pvd lists the last step twice, so the tool reports 3
  steps for 2 output files.
