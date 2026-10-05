# ISSM — foundation test case: "test101_square_shelf_ssa"

Authentic foundation case: ISSM's own NightlyRun **test101**
(`SquareShelfConstrainedStressSSA2d`). A square ice shelf (1000 km x 1000 km, fully floating,
thickness 300–1000 m) on a 50 km triangle mesh (340 vertices, 614 elements). It solves the 2D
SSA stress balance on 2 MPI ranks and reports ice velocity, pressure, deviatoric stress and the
ice flux across 6 gates. ISSM ships the official answer for this test (`Archives/Archive101.arch`)
and a tolerance for every field (in `test101.py`).
`inputs/` are the unmodified files from the ISSM git tree (taken with `git show HEAD:<path>`).

| | |
|---|---|
| Engine | ISSM 2026.1 (git ab809d35b83c5c34f2d80a959324b9ee1a0853f3, 2026-03-18), `bin/issm.exe`, PETSc 3.23, MPICH 4.3.0, Python API in `bin/` + `lib/` |
| Source | https://github.com/ISSMteam/ISSM — `test/NightlyRun/test101.py`, `test/Exp/Square.exp`, `test/Exp/MassFlux1-6.exp`, `test/Par/SquareShelfConstrained.py`, `test/Data/SquareShelfConstrained.arch`, `test/Archives/Archive101.arch` |
| Licence | BSD 3-Clause (California Institute of Technology) |
| KI | `ISSM` |

## Run
```
python run_reference.py              # 0=PASS 2=checks failed 3=engine/dependency missing
python run_reference.py --issm-bin /path/to/ISSM/bin/issm.exe   # or $ISSM_BIN
```
Use a python with numpy + scipy (the server's `/mnt/disk1/Hydrocraft_server/python_env` is used
by default). `ISSM_DIR` is taken from the folder that holds `bin/issm.exe`. `mpiexec` is taken
from `$ISSM_DIR/externalpackages/petsc/install/bin` (the MPICH that `issm.exe` is linked
with). `OMP_NUM_THREADS=4`, 2 MPI ranks. It takes about 2 seconds.

It copies `inputs/` to a fresh temp dir and does two runs:
1. **Official test101**: runs `test101.py` the way ISSM's `test/NightlyRun/runme.py` does, then
   checks all 13 fields against `Archive101.arch` with runme.py's own formula
   (`max|run - archive| / (max|archive| + eps)`) and test101.py's own tolerances.
2. **KI tool**: the same case through the KI's `tools/run_issm.py` (custom mode:
   `--domain Exp/Square.exp --ocean_mask all --par_file Par/SquareShelfConstrained.py
   --flow_equation SSA --solution Stressbalance --nprocs 2`). Its velocity max and mean must
   match max and mean of the official `Vel` archive field.

The only thing added at run time is a `generic_settings.py` file in the temp run folders. This
is ISSM's own user-settings hook for its `generic` cluster class; it only sets
`executionpath` to the temp dir, so `issm.exe` does not write into `$ISSM_DIR/execution`.
It does not change the model, so the results do not change (they match the official archive).

## Expected (all from the official ISSM file Archive101.arch, not from our run)
- Vx, Vy, Vel: relative difference <= 4e-13 (our run: 1.4e-14, 8.6e-15, 8.7e-15)
- Pressure: <= 1e-13 (our run: 1.0e-16)
- DeviatoricStress xx / yy / xy: <= 2e-13 (our run: 4.6e-14, 4.3e-14, 3.6e-14)
- MassFlux1-6: <= 1e-13 (our run: 2e-15 to 6e-15)
- KI tool: max ice speed 1639.6506 m/yr, mean 903.7193 m/yr (from Archive101 Vel), tol 1e-6
- Finished normally: driver exits 0, `md.results.StressbalanceSolution` exists, `issm.exe`
  writes a non-empty `.outbin` and an empty `.errlog`; KI tool returns `"status": "success"`.

A missing `issm.exe`, Python API or `mpiexec` is reported (exit 3), never faked.

## KI gaps (status 2026-10-06)
- **Partly fixed in `68fa97c`:** `run_issm.py --example <name>` now runs a copy of the example in the output folder, not inside `$ISSM_DIR/examples`; still open: it does not use the official NightlyRun tests or their archives, so this case still uses the tool's custom mode.
- **Fixed in `68fa97c`:** `run_issm.py` now sets the cluster `executionpath` so run files stay out of `$ISSM_DIR/execution`. Before: `issm.exe` wrote into the source tree; this case points it to the temp dir with ISSM's `generic_settings.py` hook.
- **Fixed in `68fa97c`:** `run_issm.py` now sets its own `PYTHONPATH` and `LD_LIBRARY_PATH`. Before: it added only some `src/m/*` folders and failed with `No module named 'MatlabFuncs'` unless `$ISSM_DIR/bin` and `$ISSM_DIR/lib` were on `PYTHONPATH`.
- **Fixed in `68fa97c`:** `run_issm.py` now uses PETSc's MPICH `mpiexec`. Before: it used whatever `mpiexec` was on `PATH` (OpenMPI on this server, while `issm.exe` is built with MPICH); this case puts PETSc's MPICH `mpiexec` first.

  The workarounds in `run_reference.py` (`generic_settings.py` hook, MPICH `mpiexec` first) are kept so the case also runs with older tool versions.
- **Partly fixed in `68fa97c`:** `parse_issm_output.py` now reads ISSM's `.outbin` (with `--outbin`); still open: `run_issm.py` still saves only velocity and thickness max/mean to `results.json`. This case reads fields from `md.results` directly.
