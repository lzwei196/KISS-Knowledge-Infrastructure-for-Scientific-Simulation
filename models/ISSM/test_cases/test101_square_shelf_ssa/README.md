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

## Known KI gaps (not fixed here)
- `run_issm.py --example <name>` does `os.chdir` into `$ISSM_DIR/examples/<name>` and runs
  `runme.py` there, so it writes run files into the model source tree. It also does not use
  the official NightlyRun tests or their archives. That is why this case uses the tool's
  custom mode instead.
- `run_issm.py` sets `md.cluster = generic(...)` without an `executionpath`, so by default
  `issm.exe` writes to `$ISSM_DIR/execution` (source tree). This case points it to the temp
  dir with ISSM's `generic_settings.py` hook.
- `run_issm.py` only adds some `src/m/*` folders to the path (not `src/m/miscellaneous`,
  `src/m/classes/clusters`, ...). With no extra `PYTHONPATH` it fails with
  `No module named 'MatlabFuncs'`. It works when `$ISSM_DIR/bin` and `$ISSM_DIR/lib` are on
  `PYTHONPATH` (as the KI preflight does).
- `run_issm.py` puts `$ISSM_DIR/bin` first on `PATH`, but `mpiexec` is not there; whatever
  `mpiexec` is on the user's `PATH` is used (on this server `~/.local/bin/mpiexec` is OpenMPI,
  while `issm.exe` is built with PETSc's MPICH). This case puts PETSc's MPICH `mpiexec` first.
- `run_issm.py` only saves velocity max/mean (and thickness if present) to `results.json`;
  full fields stay in memory. `parse_issm_output.py` reads `.npy` / NetCDF files, not ISSM's
  `.outbin`, so it is not used here; fields are read from `md.results` directly.
