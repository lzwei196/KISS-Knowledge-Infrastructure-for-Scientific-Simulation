# Amanzi_ATS foundation test case: official regression test richards_steadystate / fv

## What it is
ATS has an official regression suite (ats-regression-tests). Each test is an ATS input
file, a "gold" checkpoint written by an earlier ATS, and a config file with the allowed
differences. This case is `01_richards_steadystate`, test `fv`: steady-state Richards
(variably saturated) flow in a generated column of 1 x 1 x 100 cells, finite-volume
discretization, one step to steady state. The new run is compared with the gold
checkpoint by the official checker with the official tolerances.

## Source
- Test files: https://github.com/amanzi/ats-regression-tests, folder `01_richards_steadystate`,
  commit `1f1e27e5238c9f0b61f82bdee11a21cc9e264e5d` (2026-09-29). The case files are
  identical at `28ca01bb`, the commit that ATS 86114e29 records for this submodule.
  BSD licence (`inputs/official_checker/LICENSE.ats-regression-tests`, `COPYRIGHT.ats-regression-tests`).
- `inputs/fv.xml`, `inputs/richards_steadystate.cfg`, `inputs/fv.regression.gold/` (gold
  checkpoint + `ats_version.txt`): unmodified (`git show 1f1e27e5:01_richards_steadystate/...`).
  The gold was written by ATS `ats-1.3-dev-71-gf01049fe`.
- Official checker, unmodified: `inputs/official_checker/regression_tests.py` (same repo and
  commit) and `inputs/official_checker/test_manager.py` (ATS `tools/testing/test_manager.py`
  at ATS commit `86114e29df238a800013d5f3318d81a4453fcb38`, BSD licence, `LICENSE.ats`,
  `COPYRIGHT.ats`). They are packaged so the case checks itself with the official
  comparison code; they need only python 3 + numpy + h5py.

## Engine
ATS 1.6.0_86114e29 (Amanzi core 42cadd93; Release; OpenMPI 4.1.6; geochemistry off as in
the official `build_ATS_generic.sh`), `/home/server/engine_builds_20261006/ats/amanzi-install-master42cadd9-Release/bin/ats`,
built 2026-10-06 (`/home/server/engine_builds_20261006/ats/BUILD_LOG.md`). It runs
without any environment set. Serial run (1 rank).

## How to run
```
python run_reference.py [--ats-bin /path/to/ats]
```
Use a python with numpy + h5py (e.g. `/mnt/disk1/Hydrocraft_server/python_env/bin/python`).
ATS lookup: `--ats-bin` -> `$ATS_BIN` -> server default path above. PATH is not searched
(same rule as the KI tool). Without `--ats-bin`/`$ATS_BIN` the KI tool is called without
`--binary`, so the tool's own default lookup is tested.
Exit codes: 0 PASS, 2 checks failed, 3 dependency missing (nothing run). Takes a few seconds.

What the script does:
1. Copies `fv.xml`, `richards_steadystate.cfg` and `fv.regression.gold/` to a fresh temp dir.
2. Runs ATS through the KI tool: `tools/run_amanzi.py --xml_file fv.xml --run_dir <tmp>/fv.regression`
   (the run-dir name is the one the official test manager uses).
3. Runs the official checker: `regression_tests.py richards_steadystate.cfg --check-only -e <ats> -t fv`.
4. Checks `expected.json` and deletes the temp dir.

## Expected results
Official checker: 1 test run, "All tests passed". Each official criterion, its official
tolerance (max-norm of the difference to gold) and our value:

| quantity | official tolerance | our difference |
|---|---|---|
| pressure.cell.0 [Pa] | 2e-4 absolute | 1.126e-4 |
| water_content.cell.0 | 1e-8 relative (floor 140) | 3.26e-9 |
| water_flux.face.0 | 1e-8 relative (floor 0.2) | 1.44e-9 |
| saturation_liquid@current.boundary_face.0 | 1e-6 absolute | 0 |
| saturation_liquid@current.cell.0 | 1e-6 absolute | 1.52e-9 |
| time | 1e-4 absolute | 0 |

Also: KI tool and ATS exit 0, one checkpoint (as gold), ATS reports
"success: 4 nonlinear itrs" (recorded on this server). The pass rule is the official one
(gold file + official tolerances). Two clean runs gave identical results; the checkpoint
from the KI tool is bit-identical to a direct `ats --xml_file=../fv.xml` run.
A changed gold value (pressure + 1 Pa) makes the case fail (exit 2), as it should.

## Known KI gaps
- **Fixed 2026-10-06 (live KI):** `tools/run_amanzi.py` and `preflight_check.py` only looked
  for `ats`/`amanzi` on PATH, where nothing is installed, so preflight failed and the tool
  stopped with "binary not found". Now: `--binary` (tool) -> `$ATS_BIN` -> the server build.
- **Fixed 2026-10-06 (live KI):** `tools/run_amanzi.py` checked every ParameterList input for
  Amanzi's own block names (`Mesh`, `Regions`, `Material Properties`, `Initial Conditions`), so
  it refused every native ATS input. It now detects native ATS input (sublists `cycle driver`
  and `PKs`) and checks `mesh`, `regions`, `cycle driver`, `PKs`, `state` (all 167 official
  regression inputs have them).
- **Open:** `tools/parse_amanzi_output.py --vis_file ats_vis_data.h5` finds no variables (it
  expects `<var>.cell.<n>` datasets; ATS writes groups `<var>/<cycle>`), writes no CSV, and
  still exits 0. This case reads the output with the official checker instead.
- Engine note (not a KI gap): this build has no Alquimia chemistry (22 official reactive
  transport tests cannot run) and 5 official `column_*` integrated-hydro tests crash
  (segfault in Richards hydrostatic initialisation); the KI tool reports those runs as failed
  (exit 1).
