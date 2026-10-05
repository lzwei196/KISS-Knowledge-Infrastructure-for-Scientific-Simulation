# PFLOTRAN foundation test case: 543_flow

## What it is
PFLOTRAN's own official regression test `regression_tests/default/543/543_flow`.
It is a small 3D variably saturated (Richards) flow problem:

- structured grid 5 x 4 x 3 = 60 cells, 4 soil types placed from `543.h5`
- start pressure read from `543_initial_pressure.h5`
- west side: hydrostatic; east side: water level that changes with time;
  top: recharge 0.5 dm/yr; one injection well (1000 dm3/h)
- 10 days, 100 time steps of 0.1 d, direct LU solver, 1 MPI rank
- runs in about 1-2 seconds

## Source
- Repo: https://bitbucket.org/pflotran/pflotran, tag `v6.0`
  (commit `fab315dc6559306f2f93b27571bf5add812dd820`).
- All files in `inputs/` are taken unchanged from that commit with `git show HEAD:<path>`
  (sha256 in `manifest.json`):
  - `543_flow.in`, `543.h5`, `543_initial_pressure.h5` - the model input
  - `543_flow.regression.gold` - official reference result
  - `543.cfg` - official test settings and tolerances
  - `regression_tests.py` - PFLOTRAN's own test runner/checker (from `regression_tests/`)
- Licence: PFLOTRAN is released under the GNU LGPL (see `LICENSE` in the repo).

## Engine
`/mnt/disk1/Hydrocraft_server/models/PFLOTRAN/source/repo/src/pflotran/pflotran`
(PFLOTRAN v6.0, built with PETSc 3.21, HDF5 1.14, OpenMPI from miniconda3).

## How to run
```
/mnt/disk1/Hydrocraft_server/python_env/bin/python run_reference.py [--pflotran-bin PATH]
```
Binary lookup: `--pflotran-bin` -> `$PFLOTRAN_BIN` -> `which pflotran` -> server default path.
The script:
1. copies `inputs/` into a fresh temp dir,
2. runs PFLOTRAN (1 rank) through the KI tool `tools/run_pflotran.py`,
3. runs PFLOTRAN's own `regression_tests.py --check-only` on the result
   (official gold file + official tolerances from `543.cfg`),
4. checks the 14 numbers in `expected.json` itself,
5. deletes the temp dir.

Exit codes: 0 PASS, 2 checks failed, 3 engine or KI tool missing.

## Expected results
All expected values come from the official gold file `543_flow.regression.gold`,
and all tolerances are the official ones from `543.cfg` (pressure 1e-12 relative,
saturation 1e-12 absolute, counts exact, other values 1e-12 absolute). Main values:

| check | expected |
|---|---|
| pressure max / min / mean (Pa) | 407637.19684121 / -20158.416259121 / 204162.76766874 |
| liquid saturation min / mean | 0.13332489875118 / 0.73390829333077 |
| time steps / Newton / linear iterations / cuts | 100 / 234 / 234 / 0 |
| solution 2-norm / residual 2-norm | 2.0084450136586e6 / 7.8869263700965e-10 |

Run on 2026-10-05 (twice): both runs match the gold file digit for digit
(the only extra line in our output is the run time, which the gold file does not hold),
and `regression_tests.py --check-only` says "All tests passed.".
We also checked the official checker really catches errors: a changed gold value
(pressure max off by 0.1 Pa, 2.5e-7 relative) made it fail.

## KI gaps (status 2026-10-06)
- **Fixed in `1777b45`:** `run_pflotran.py` writes its own log to `<prefix>_run_log.txt`
  and keeps PFLOTRAN's own `.out` file. Before: the tool log was written to `<prefix>.out`
  and replaced PFLOTRAN's file.
- **Fixed in `1777b45`:** `run_pflotran.py` checks PFLOTRAN v6's end line
  `Wall Clock Time:` and looks for the output files the deck really asks for, so no false
  warnings. Before: it looked for "Simulation Complete", `<prefix>.h5` and
  `<prefix>-mas.dat` and printed three warnings on a good run.
- **Fixed in `1777b45`:** `parse_pflotran_output.py` now reads `.regression` files
  (`--regression-file`, writes `regression.csv`), plus v6 observation files and HDF5 cell
  data. Before: there was no KI tool for `.regression` files; `run_reference.py` reads it
  itself. The workaround in `run_reference.py` is kept so the case also runs with older tool versions.
