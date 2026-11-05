# DualSPHysics — foundation test case: "dambreak_val2d"

Official foundation case: the **2D dam-break validation case** `CaseDambreakVal2D` that ships
with DualSPHysics (`examples/main/01_DamBreak`). A water column 1 m wide and 2 m high collapses
in a 4 m long tank; the front runs along the floor and hits the far wall. The case ships its own
experiment file (front position vs time, Koshizuka & Oka 1996), which we use as the reference.
`inputs/` are the unmodified files from the DualSPHysics git (`git show HEAD:...`).

| | |
|---|---|
| Engine | DualSPHysics5 v5.4.355 CPU (`DualSPHysics5.4CPU_linux64`), GenCase v5.4.354.01, MeasureTool v5.4.266.01 |
| Source | github.com/DualSPHysics/DualSPHysics, `examples/main/01_DamBreak`, commit ef3721a (2025-04-16) |
| Licence | LGPL-2.1 or later (DualSPHysics) |
| KI | `DualSPHysics` (run through `tools/run_dualsphysics.py`) |
| Size | dp = 0.01 m, 21,001 particles, 2.0 s simulated, about 3 min on 8 CPU threads, < 30 MB RAM |

## Inputs (unmodified)
- `CaseDambreakVal2D_Def.xml` — case definition (geometry, gauges, solver settings, TimeMax 2.0 s)
- `EXP_X-DamTipPosition_Koshizula&Oka1996.txt` — official experiment data (front position)
- `xCaseDambreakVal2D_linux64_CPU.sh` — official run script, kept for reference only (not run)

## Run
```
python run_reference.py    # 0=PASS 2=FAIL 3=missing engine
                           # bin dir: --dsph-bin-dir -> $DSPH_BIN_DIR -> which -> server default
```
It copies `inputs/` to a fresh temp dir, runs GenCase + DualSPHysics (CPU, 8 OpenMP threads)
through the KI's `tools/run_dualsphysics.py`, then runs the official MeasureTool elevation step
(same command as the official script, plus `-threads:8`), then checks `expected.json`.
Nothing in the case is changed (TimeMax, output step and physics are the official ones).
Thread count does not change results: an older run with 64 threads gave byte-identical output.

## Expected (recorded 2026-10-05; deterministic — repeat runs were byte-identical)
- finished with `Finished execution (code=0).`; 21,001 particles (20,000 fluid); 201 part files; t = 2.0 s
- 69,913 time steps; 559 particles left the domain (splashing)
- front (gauge Swl_z003, z = 0.03 m) starts at x = 1.007 m, passes x = 3.9 m at t = 0.655 s, stops at the wall (3.991 m)
- vs official experiment (13 points before the wall): RMSE 0.272 m, max error 0.335 m;
  the simulated front runs ahead of the experiment by about 0.26 m on average.
  No official tolerance ships, so the check is that our value repeats (tol 0.02 m).
- water level at x = 0.2 m: 2.010 m at t = 0, 0.556 m at t = 1 s, 0.211 m at t = 2 s

## Not run from the official script
The official script also runs PartVTK, PartVTKOut, TracerParts and IsoSurface to make VTK
pictures. They make only visual files, and `TracerParts_linux64` is not in the server bin dir,
so they are not part of this test. The 3D case `CaseDambreak` in the same folder is not used
(no experiment data for it; much larger).

## KI gaps (status 2026-10-06)

No KI tool fix for DualSPHysics has landed in this checkout since the case was made (last DualSPHysics commit `14b4087`), so every item below is still open.

- **Still open:** `tools/run_dualsphysics.py` reads particle counts with a regex that stops at the comma
  ("21,001" -> 21), so its `total_particles` field is wrong; it also looks for `RUN.out`
  but the solver writes `Run.out` (the tool then only warns). The run itself works.
- **Still open:** `tools/parse_dsph_output.py --mode summary` fails on this real `Run.out`
  ("No PART data found in RUN.out"), so `run_reference.py` reads `Run.out` and the gauge CSVs directly.
- **Still open:** The solver binary `DualSPHysics5.4CPU_linux64` is not tracked in git (git-ignored build output);
  it was built on the server from the official source at commit ef3721a, with one compile-only
  local fix (`#include <cstdint>` in `src/source/JBinaryData.h`).
