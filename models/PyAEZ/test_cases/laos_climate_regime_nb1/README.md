# PyAEZ test case: laos_climate_regime_nb1

## What it is
The official PyAEZ demo for Module I (Climate Regime), the same run as the official
tutorial notebook `tutorials/NB1_ClimateRegime.ipynb`. It takes monthly climate data for
Lao PDR (194 x 169 grid, 12 months, 6 variables) plus an admin mask and an elevation map,
and works out the basic farming-climate maps: thermal climate, thermal zone, thermal
growing periods (LGPt0/5/10), temperature sums (Tsum0/5/10), length of growing period
(LGP) and LGP-equivalent. 9762 grid cells lie inside the Laos mask.

Settings are the notebook's own: lat 13.87 to 22.59, mask value 0, monthly data
(`daily = False`), `getLGP(Sa=100, D=1)`.

## Source
- Repo: https://github.com/gicait/PyAEZ (FAO / GIC-AIT), commit
  `792e1d4231f6fa75beb98bbeed162a4fa9efbb56` (2026-02-10), PyAEZ version 2.2.
- `inputs/` = unmodified files from `data_input/` at that commit (taken with `git archive`):
  `climate/*.npy` (6 monthly arrays) + `climate/Metadata.txt`, `LAO_Admin.tif`,
  `LAO_Elevation.tif`, and `input_crop_TSUM_parameters_maiz_sugar.xlsx` (not used by
  Module I; the KI run tool only checks it exists).
- `reference/NB1/` = the official Module I output rasters, unchanged, from
  `data_output/NB1/` (committed upstream in a3b1f5b, 2023-07-03).
- Licence: MIT (Copyright 2023 GIC-AIT, FAO-UN).

## Engine
PyAEZ Python package run from source: `PYTHONPATH=/mnt/disk1/Hydrocraft_server/models/PyAEZ/source/repo`
with `/mnt/disk1/Hydrocraft_server/python_env/bin/python_with_gdal` (Python 3.12,
numpy 2.4.4, numba 0.64.0, GDAL 3.12.4).

## How to run
```
python run_reference.py [--python /path/to/python_with_gdal] [--pyaez-src /path/to/PyAEZ/repo]
```
Lookup: `--python` -> `$PYAEZ_PYTHON` -> `which python_with_gdal` -> server default;
`--pyaez-src` -> `$PYAEZ_SRC` -> server default. The script copies `inputs/` to a fresh
temp dir, runs the KI tool `tools/run_pyaez.py --modules 1`, reads the output rasters,
compares them with `reference/NB1/` and `expected.json`, then deletes the temp dir.
Exit 0 = PASS, 2 = checks failed, 3 = engine or dependency missing. Takes about 1 minute.

## Expected results
- Finished normally: return code 0 and the tool line
  `All pipeline outputs validated successfully`.
- Eight rasters (thermal climate, thermal zone, LGPt0, LGPt5, LGPt10, Tsum0, Tsum5,
  Tsum10) match the official rasters exactly on all 9762 mask cells (tolerance 0).
  Summary values from the official files: Tsum0 mean 8445.1187 deg-days, LGPt10 min 310
  days, thermal climate max class 4.
- LGP and LGP-equivalent use values from our own run (mean LGP 259.83 days, min 209;
  mean LGP-equivalent 293.309 days). Two clean runs gave byte-identical output rasters.

Why LGP is not checked against the official file: the official `LAO_LGP.tif` (mean 262.44)
differs on 2295 of 9762 cells (up to 55 days), and `LAO_LGPEquivalent.tif` by at most
0.0124 day. These files were made in July 2023, before two upstream fixes to the LGP water
balance in January 2024 (0a02583 "fix sb_old,wb_old initialization" in ClimateRegime.py,
4348400 "fix Sb365 bug in else section of EtaCalc" in LGPCalc.py). The climate inputs,
mask and elevation are byte-identical between the 2023 commit and today's. All other
Module I maps still match exactly.

Note: the official rasters keep real numbers outside the mask (older save code), while
today's run writes -999 there, so all checks use the 9762 mask cells only.

## Known KI gaps
- `tools/run_pyaez.py` does not set `PYTHONPATH` to the PyAEZ source; `pyaez` is not
  installed in python_env, so the tool fails with "No module named 'pyaez'" unless the
  caller sets `PYTHONPATH` (the preflight sets it itself). `run_reference.py` sets it.
- `tools/run_pyaez.py` Module I writes only 2-D maps; it skips the temperature profile
  (3-D), multi-cropping zones, frost index / permafrost, fallow and AEZ classification
  that the NB1 notebook also makes. It also needs `--crop-name` / `--crop-params` even when
  only Module I is run.
- `tools/parse_output.py` requires output folders NB1 to NB6 and cannot read a Module I
  only run, so the rasters are read directly with GDAL.
