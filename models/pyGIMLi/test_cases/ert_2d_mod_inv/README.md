# pyGIMLi foundation test case: 2D ERT modelling and inversion

## What it is
pyGIMLi's own documentation example "2D ERT modelling and inversion"
(`doc/examples/3_ert/plot_01_ert_2d_mod_inv.py`). The script:

1. builds a 2D earth: three layers (100, 75, 50 Ohm m) with two buried bodies
   (an ellipse of 150 Ohm m and a polygon of 25 Ohm m),
2. simulates a dipole-dipole survey on 21 electrodes (-15 to 15 m), adding fixed noise
   (1% + 1 uV, `seed=1337`), giving 171 readings and the file `simple.dat`,
3. inverts the data on an automatic mesh (lam=20) and on a regular grid (lam=20),
4. checks its own results with two upstream asserts: chi^2 about 0.7 and about 1.4.

The data are synthetic, but they are made by the official script itself with a fixed
seed, so this is the model's own official test, not local data.

## Source
- Repo: https://github.com/gimli-org/gimli
- File: `doc/examples/3_ert/plot_01_ert_2d_mod_inv.py` at tag `v1.5.5.post1`
  (commit d0ed6ed4), the same release as the installed engine. Copied unchanged into
  `inputs/` (sha256 in `manifest.json`). The newer git HEAD (e792d84b) differs only by
  one spelling fix in a comment.
- Licence: Apache-2.0 (pyGIMLi).

## Engine
- pygimli 1.5.5.post1 + pgcore 1.5.5 (pip wheels) in
  `/home/server/knowledge-dissection-toolkit/auto_dissect/_work/pyGIMLi/venv/bin/python`.
- Not importable from the server `python_env`.

## How to run
```
OMP_NUM_THREADS=4 python run_reference.py [--pygimli-python /path/to/python]
```
Python lookup: `--pygimli-python` -> `$PYGIMLI_PYTHON` -> the Python running the script
(if it can import pygimli) -> `python3` on PATH -> the server venv above.
Exit 0 = PASS, 2 = checks failed, 3 = no Python with pygimli (prints
`MISSING DEPENDENCY: ... NOT run.`). Takes about 4 seconds and < 300 MB RAM.

What `run_reference.py` does, in a fresh temp dir that is deleted at the end:
1. copies the official script and runs it with a small driver (`runpy`) under the
   non-GUI matplotlib backend `Agg` (set by env var; the script text is not changed),
   then reads the final objects (data, meshes, models, chi^2);
2. inverts the script's `simple.dat` again through the KI tool `tools/run_pygimli.py`
   (`--lam 20 --max-iter 20`, the same call as the script's first inversion) and reads
   the result with the KI tool `tools/parse_gimli_output.py`;
3. compares with `expected.json`.

## Expected results
- Official checks (values asserted inside the upstream script, upstream tolerance
  |chi^2 - value| < 0.1): first inversion chi^2 = 0.7 (we get 0.7038), regular-grid
  inversion chi^2 = 1.4 (we get 1.4163). The script also runs these asserts itself.
- Own-run checks (21 values): data count 171, 21 electrodes, mesh 3544 cells, simulated
  apparent resistivity 42.79-104.20 Ohm m, inverted model ranges, grid inversion chi^2
  1.4163 and RMS 1.196%, KI-tool inversion chi^2 0.70379 in 3 iterations on 287 cells,
  model 22.96-146.74 Ohm m (mean 80.46).
- Repeat runs: 12 clean runs of the script and 4 of the KI tool. Exactly the same every
  time: the simulated data (`simple.dat` byte-identical), the mesh, the regular-grid
  inversion and the KI-tool inversion. Not bit-repeatable: the script's own first
  inversion (automatic mesh), which gave 3 slightly different results (chi^2
  0.7038-0.7082, min 22.960-22.966, max 146.710-146.741 Ohm m). Those two checks have
  wider tolerances (0.05 and 0.1 Ohm m); all stay well inside the upstream assert.

## Known KI gaps
- The KI preflight checks `pygimli` in the server `python_env`, where it is not
  installed, so 3 import checks fail there. pyGIMLi only runs from the dissection venv
  above, and `preflight_check.py` has no setting to point at another Python.
- `tools/run_pygimli.py` cannot build a custom geometry or simulate data on a
  layered/anomaly model (its forward mode only does a uniform half-space). So the
  modelling half of the official example runs through the official script, and the KI
  tool is used for the inversion of the script's data file.
- `tools/run_pygimli.py` sets `--max-iter` default 10, while pyGIMLi's own default is 20;
  this case passes `--max-iter 20` to match the official call (it stops after 3 anyway).
- `pygimli.__version__` in this venv depends on the current folder (it asks git in the
  cwd), so it can print a wrong version; `run_reference.py` reads the package metadata
  instead.
