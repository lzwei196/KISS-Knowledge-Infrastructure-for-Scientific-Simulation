# Elmer/Ice foundation test case: Friction_Weertman (ISMIP-HOM B020)

## What it is
The official Elmer/Ice test `elmerice/Tests/Friction_Weertman`. It is the ISMIP-HOM
B020 set-up: a 2D flow line of ice, 20 km long, sliding down a 0.5 degree slope over a
sine-shaped bed. The ice follows Glen's law (n = 3) and is solved with full Stokes.
The bed uses the Weertman sliding law (beta = 0.02, exponent 1/3). The left and right
sides are periodic. It is a steady run (one step). Units in the .sif are m, years, MPa.

The test ships its own official answer: the line
`Solver 3 :: Reference Norm = Real 56.70374` in the .sif. ElmerSolver checks itself
against this number and writes `TEST.PASSED` = 1 when it matches (the official ctest rule).

## Source
- Repo: ElmerCSC/elmerfem, https://github.com/ElmerCSC/elmerfem
- Path: `elmerice/Tests/Friction_Weertman`, commit `0a0fcfe991e506e6a0c6c81b3e1c0f4759021306`
- Reference set by L. Tavard (LGGE), 26.11.2015, rev 522ee2e (see `inputs/README.txt`)
- Licence: Elmer is GPL-2.0 / LGPL-2.1; the Elmer/Ice code is GPL.

`inputs/` holds the unmodified official files (taken with `git show HEAD:...`):
`ismip_weertman.sif`, `rectangle.grd`, `ELMERSOLVER_STARTINFO`, `README.txt`. About 5 KB.

## Engine
Elmer 26.1-devel (Rev 0a0fcfe, compiled 2026-06-23), built with Elmer/Ice.
Server default: `/home/server/knowledge-dissection-toolkit/auto_dissect/_work/Elmer_Ice/install_ice/bin/ElmerSolver`
and `ElmerGrid` in the same folder. Serial run (1 rank), OMP_NUM_THREADS=4. Takes about 1 s.

## How to run
```
/mnt/disk1/Hydrocraft_server/python_env/bin/python run_reference.py
#   options: --elmersolver-bin PATH  --elmergrid-bin PATH  --keep
```
Binary lookup: `--elmersolver-bin` / `--elmergrid-bin` -> `$ELMERSOLVER_BIN` / `$ELMERGRID_BIN`
-> `which` -> server default above. The script copies `inputs/` to a fresh temp folder,
runs `ElmerGrid 1 2 rectangle.grd` (same as the official runTest.cmake), then runs
`ElmerSolver ismip_weertman.sif` through the KI tool `tools/run_elmerice.py`, reads the
log and the VTU output, checks `expected.json`, and deletes the temp folder.
Exit 0 = PASS, 2 = checks failed, 3 = engine or Elmer/Ice libraries missing (not run).

## Expected results
- Official: ElmerSolver's own compare says `PASSED all 1 tests`, TEST.PASSED = 1, and the
  final Stokes norm is 56.70374 within Elmer's default tolerance (1e-5 relative).
  Our run: Norm = 56.7037392, relative error 1.4e-8.
- Recorded from our own run (two clean runs gave the same numbers to 9 digits):
  32 Stokes iterations, 451 nodes, 500 cells, 41 surface and 41 bed nodes,
  max speed 111.35 m/a, mean surface along-flow speed 81.35 m/a, max surface speed
  108.05 m/a, mean bed sliding speed 55.70 m/a, max pressure 13.24 MPa, mean pressure 4.42 MPa.
- Plus: return code 0 and ElmerSolver's own line `*** Elmer Solver: ALL DONE ***`.

## Known KI gaps
1. The engine named by the KI preflight (`/mnt/disk1/Hydrocraft_server/models/Elmer_Ice/bin/bin/ElmerSolver`,
   and the copy in `.../_work/Elmer_Ice/install/bin/`) is plain Elmer without the Elmer/Ice
   libraries. It cannot load `ElmerIceUSF` / `ElmerIceSolvers`, so this case (and any case
   using Elmer/Ice solvers or user functions) does not run with it. The Elmer/Ice build is in
   `.../_work/Elmer_Ice/install_ice/`; this case uses that. The preflight still says PASSED
   because it only checks that ElmerSolver starts.
2. `tools/run_elmerice.py` reports `"status": "success"` with return code 0 even when
   ElmerSolver stops early because a library is missing (ElmerSolver itself returns 0).
   It also looks for `.vtu` only in the run folder, but Elmer writes it in the mesh folder,
   so it wrongly warns "No VTU files produced". It keeps only the last 20 stdout lines.
3. `tools/parse_vtu_output.py` cannot read Elmer's default VTU (binary "appended raw" data);
   it fails with an XML parse error. `run_reference.py` reads the VTU itself.
4. No KI tool builds the mesh; `ElmerGrid` is run directly.
