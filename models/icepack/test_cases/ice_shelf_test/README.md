# icepack foundation test case: official ice-shelf test (exact solution)

## What it is
icepack ships its own unit tests in `test/`. `test/ice_shelf_test.py` checks the ice-shelf
momentum (diagnostic) solver against an exact solution: a floating ice shelf 20 km x 20 km,
thickness falling linearly from 500 m to 400 m, inflow speed 100 m/yr, temperature
-19 C (254.15 K). The exact velocity comes from Greve & Blatter. The test solves on finer
and finer meshes and checks how fast the error shrinks (the "convergence slope").

It has 4 tests, each with its own official limit:
- `test_diagnostic_solver_convergence[icepack]` and `[petsc]`: for CG degree 1, 2, 3 the
  slope must be above degree + 0.8 (two solver back-ends).
- `test_diagnostic_solver_parameterization`: same, with the viscosity written in terms of
  the rheology B; slope (degree 2) must be above 1.95.
- `test_diagnostic_solver_side_friction`: friction at the side walls must slow the shelf.

## Source
- https://github.com/icepack/icepack, `test/ice_shelf_test.py` at master commit
  `c9a29780cd0f7d068d206cb5a170fa367a7655b0` (2026-10-05). GPL-3.0-or-later.
- `inputs/ice_shelf_test.py` is the unmodified file (`git show c9a29780:test/ice_shelf_test.py`,
  git blob `f9f72a43`). The test makes its own mesh and fields; there are no data files.

## Engine
`/home/server/engine_builds_20261006/firedrake/venv/bin/python` (Python 3.12.3):
firedrake 2026.10.0, PETSc / petsc4py 3.26.0, icepack upstream master c9a29780 (version
string 1.1.0), pytest. Built on 2026-10-06 (`/home/server/engine_builds_20261006/firedrake/BUILD_LOG.md`).
The venv works without sourcing `fd_env.sh`.
Note: the icepack source copy kept with the KI (b3528bed) does not work with this
Firedrake (geometric_dimension TypeError); upstream fixed it, so upstream master is used.

## How to run
```
python run_reference.py [--python /path/to/python]
```
Python lookup (same as the KI preflight): `--python` -> `$ICEPACK_PYTHON` -> server default
`/home/server/engine_builds_20261006/firedrake/venv/bin/python`. An explicit choice is used
as-is (no fallback). The script itself can be started with any python 3 (e.g. python_env).
Exit codes: 0 PASS, 2 checks failed, 3 dependency missing (nothing run).
Takes about 40 s and 0.65 GB RAM, serial, 1 thread.

What the script does:
1. Copies `inputs/ice_shelf_test.py` to a fresh temp dir.
2. Runs it with pytest (JUnit report with the printed output kept).
3. Reads the 7 printed slopes and checks the counts and slopes in `expected.json`.
4. Deletes the temp dir.

## Expected results
- 4 official tests pass, 0 failed, 0 errors, 0 skipped (the test file's own asserts).
- Convergence slopes, official limit and our value:

| test | degree | official limit | our value |
|---|---|---|---|
| convergence, solver icepack | 1 | > 1.8 | 1.90382 |
| convergence, solver icepack | 2 | > 2.8 | 2.91626 |
| convergence, solver icepack | 3 | > 3.8 | 3.89358 |
| convergence, solver petsc | 1 | > 1.8 | 1.90382 |
| convergence, solver petsc | 2 | > 2.8 | 2.91626 |
| convergence, solver petsc | 3 | > 3.8 | 3.91985 |
| parameterization (rheology B) | 2 | > 1.95 | 2.49858 |

The limits are official. The slope values were recorded from our own runs on 2026-10-06
(no official reference file ships with the test); three clean runs gave the same values to
all 6 printed digits. A check passes when the slope is above the official limit AND within
0.001 of our value (the test prints 6 significant digits).

## Known KI gaps
- **Open:** the KI run tool `tools/run_icepack_simulation.py` cannot run this test, so pytest
  is run directly with the KI's model interpreter. The tool starts from zero velocity (so the
  inflow boundary holds u = 0, not 100 m/yr), gives the ice-shelf model no side walls, and has
  no mesh-refinement loop or exact-solution error. Its rectangle geometry, thickness ramp
  (500 m, -100 m) and temperature do match this test.
- **Open:** `tools/parse_icepack_output.py --type checkpoint` only lists `.h5` files; it does
  not read fields from Firedrake checkpoints.
- **Fixed 2026-10-06 (live KI):** the KI could not reach a working icepack: preflight checked
  python_env (no firedrake, no icepack) and the manifest named an old venv with icepack but
  no firedrake. Now preflight, the run tool (`--python` / `$ICEPACK_PYTHON` / server venv,
  re-launches itself under it) and the SKILL.md tool index use the Firedrake venv.
