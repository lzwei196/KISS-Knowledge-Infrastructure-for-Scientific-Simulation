# Ribasim test case: basic (official test model)

## What it is
The "basic" model from Ribasim's own test models (`ribasim_testmodels`). Ribasim's
developers build this model in their test suite and run it in
`core/test/run_models_test.jl` (testitem "basic model"), where they check the end-of-run
basin storage. It is a small water network: 17 nodes (4 basins, 2 flow boundaries, 2 level
boundaries, 2 linear resistances, 1 Manning resistance, 1 pump, 3 rating curves,
1 junction, 1 terminal) and 17 links, one year (2020-01-01 to 2021-01-01) with daily output and concentration
(tracer) tracking on.

## Source
- Repository: https://github.com/Deltares/Ribasim, commit `fcfb329a3831babc90c52d2f4d67bb7d26a674d8`
  (version 2026.1.0-rc2).
- Model definition: `python/ribasim_testmodels/ribasim_testmodels/basic.py`, function `basic_model()`.
- The files in `inputs/` were written by Ribasim's own generator script, unchanged:
  `python utils/generate-testmodels.py basic` (run from a scratch folder; it writes
  `generated_testmodels/basic/ribasim.toml` and `input/database.gpkg`). We used the
  `ribasim` and `ribasim_testmodels` Python packages 2026.1.0rc2 (same files as the repo
  commit above). Running the generator twice gave byte-identical files (sha256 in
  `manifest.json`). There are no Arrow input files in this model.
- Official check: `core/test/run_models_test.jl`, testitem "basic model".
- Licence: MIT (Ribasim developers / Deltares).

## Engine
`/mnt/disk1/Hydrocraft_server/models/Ribasim/bin/ribasim`: a small wrapper that runs the
Ribasim Julia core (`Ribasim.main(toml)`) from the commit above, Julia 1.12.5. A run takes
about 2-3 minutes, mostly Julia start-up and compiling; it uses about 2.5 GB RAM.

## How to run
```
/mnt/disk1/Hydrocraft_server/python_env/bin/python run_reference.py [--ribasim-bin PATH]
```
Engine lookup: `--ribasim-bin` -> `$RIBASIM_BIN` -> `which ribasim` -> server default path.
The script copies `inputs/` to a fresh temp folder, runs the model through the KI tool
`tools/run_ribasim.py`, reads `results/basin.nc`, `flow.nc` and `concentration.nc`,
checks `expected.json`, and deletes the temp folder.
Exit 0 = PASS, 2 = checks failed, 3 = engine or Python package missing (NOT run).
Python needs numpy, xarray and netCDF4 (all in python_env).

## Expected results
- Finished normally: tool exit code 0 and `The model finished successfully` in `results/ribasim.log`.
- End-of-run storage of basins 1, 3, 6, 9 (m3): official values from the Julia test,
  775.23576, 775.23365, 572.60102, 1130.005, with the official tolerance 1.5 m3.
  Our run: 775.2353, 775.2332, 572.6028, 1130.005 (all within 0.002 m3).
  `basin.nc` keeps storage at the start of each day, so the end storage is taken as last
  storage + last storage_rate x 86400 s; this matches the storage from the final levels
  in `basin_state.nc`.
- Concentration checks from the same official test: Continuity tracer = 1, source
  fractions add up to 1, residence time > 0.
- Water balance: largest balance_error about 1e-17 m3/s and relative_error about 6e-14,
  far inside Ribasim's own limits (1e-3 and 1e-2).
- Counts and totals from our own run: 366 daily records, 4 basins, 17 links, total
  precipitation 1464 m3, total evaporation 1285.628 m3, highest level 1.63 m.
  Two runs gave exactly the same output.

## KI gaps (status 2026-10-06)

No KI tool fix for Ribasim has landed in this checkout since the case was made (last Ribasim commit `06c8a26`), so every item below is still open.

- **Still open:** The KI's own model builder (`tools/build_network.py`) only turns hand-written CSV tables
  into a model; it cannot build this official test model. The inputs come from Ribasim's
  own generator instead.
- **Still open:** `/mnt/disk1/Hydrocraft_server/python_env` has no `ribasim` Python package (and no
  `pandera`/`datacompy`, and its pandas 3 is newer than ribasim allows), so the generator
  was run with the dissection venv
  `/home/server/knowledge-dissection-toolkit/auto_dissect/_work/Ribasim/venv`. Running the
  test case itself does not need the `ribasim` package.
- **Still open:** The copy of `tools/run_ribasim.py` in this KISS checkout is older than the live KI copy
  on disk1 (the live one adds output-freshness checks and stricter binary checks). Both
  ran this case fine.
- **Still open:** The KI parse tool `tools/parse_ribasim_output.py` was not used; results are read
  directly with xarray in `run_reference.py`.
