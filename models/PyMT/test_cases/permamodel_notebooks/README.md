# PyMT foundation test case: permamodel_notebooks

## What it is
The offline part of two official PyMT notebooks, `notebooks/frost_number.ipynb` and
`notebooks/ku.ipynb`. They load two permafrost models from the `pymt_permamodel` plugin
through PyMT, change a few settings, run one time step (1 year), and read the result:

- **FrostNumber**: air frost number for two air temperature ranges (2 runs).
- **Ku**: active layer thickness for five settings (air temperature, snow depth,
  soil water content) (5 runs).

The notebooks keep their printed results in saved output cells. We check our run against
those saved values. No network is used.

The later notebook cells download CSV files from raw.githubusercontent.com (a 6-year frost
number series and a Barrow 1961-2015 series). Those files are not on the server and a live
download is not repeatable, so those cells are NOT part of this case.

## Source
- Notebooks: https://github.com/csdms/pymt, `notebooks/`, last changed in commit 4129aff
  (2022-10-13). Read with `git show HEAD:` from the server checkout at c0544b6
  (v1.3.2-3), so they are the unmodified official files.
- Model default config: the official `pymt_permamodel` 0.2.3 release (pip wheel). The files
  in `inputs/pymt_permamodel_0.2.3_data/` (FrostNumber/, Ku/) are byte copies of the
  installed plugin files, which match the wheel's own RECORD hashes. PyMT reads these from
  the installed plugin; our copies are used to check the installed files are the official ones.
- Licence: MIT (pymt, CSDMS), MIT (pymt_permamodel, CSDMS), MIT (permamodel).

## Engine
`/home/server/knowledge-dissection-toolkit/auto_dissect/_work/PyMT/venv/bin/python`
with pymt 1.3.3.dev0 (git c0544b6), pymt_permamodel 0.2.3, permamodel 0.2.3, Python 3.12.3.

## How to run
```
python3 run_reference.py                 # finds the PyMT python by itself
python3 run_reference.py --pymt-bin /path/to/python   # or set PYMT_BIN
```
It works in a fresh temp dir (also used as TMPDIR, so the model setup folders go there),
runs each of the 7 steps through the KI tool `tools/run_model.py`, then runs the notebook
cells literally (one model object reused, like the notebook), checks `expected.json`, and
deletes the temp dir. Exit 0 = PASS, 2 = a check failed, 3 = no python with pymt +
pymt_permamodel. Takes about 1.5 minutes (each Ku run takes ~10 s).

## Expected results
From the saved notebook output cells (notebooks print 8 decimals, tol 1e-7):

| step | setting | value |
|---|---|---|
| fn_air_1 | T_air_min=-13.0, T_air_max=19.5 | frost number 0.42108743 |
| fn_air_2 | T_air_min=-40.9, T_air_max=19.5 | frost number 0.64127961 |
| ku_alt_1 | T_air=-15.21, A_air=18.51 | active layer 0.25622575 m |
| ku_alt_2 | + h_snow=0.0 | 0.12506836 m |
| ku_alt_3 | h_snow=0.4 | 0.29543607 m |
| ku_alt_4 | + vwc_H2O=0.2 | 0.46966741 m |
| ku_alt_5 | vwc_H2O=0.6 | 0.20328717 m |

All 7 match. FrostNumber now gives float32 values (0.42108744, 0.64127964), about 3e-8 from
the saved print, inside tol. Also checked: soil temperature of the first Ku run
(-12.35477449, own run, not printed in the notebook), the KI-tool and literal runs agree
exactly, 7 steps done, installed plugin defaults are the official files, and every run
finished normally. Two clean runs gave identical numbers.

## KI gaps (status 2026-10-06)

No KI tool fix for PyMT has landed in this checkout since the case was made (last PyMT commit `51c4b87`), so every item below is still open.

- **Still open:** `pymt` keeps `setup()` settings on the model object, so in the notebook each new
  `setup(...)` adds to the earlier settings (e.g. `vwc_H2O=0.6` is run with the earlier
  T_air, A_air and h_snow=0.4 still set). `run_model.py` makes a new model object each
  time, so to repeat a notebook step you must pass the full set of settings. Passing only
  `{"vwc_H2O": 0.6}` gives 0.3519 m, not the notebook's 0.2033 m. The KI docs do not say this.
- **Still open:** `run_model.py --run-dir` does not work: the tool passes it as `setup(path=...)`, but pymt
  takes the folder as the first plain argument, so `path` becomes a template setting and the
  model still sets up in a new `/tmp/tmpXXXX` folder (left behind). This case does not use
  `--run-dir`; it sets TMPDIR instead.
- **Still open:** With no `--duration`, `run_model.py` runs FrostNumber for 0 steps, because the plugin's
  default end time equals its start time (0 years). Use `--duration 1` (done here).
- **Still open:** Ku's `finalize()` writes `off.nc` into the current folder, so run it in a scratch folder.
