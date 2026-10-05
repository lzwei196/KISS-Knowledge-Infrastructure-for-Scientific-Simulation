# ELMFIRE foundation test case: Tutorial 01 (constant wind)

## What it is
ELMFIRE's own first tutorial: one fire starting at a point on flat ground, in GR2 grass
(fuel model 102), with a steady 15 mph wind from the north. The grid is 400 x 400 cells of
30 m (12 km square, centre at 0,0). The fire starts at (0, 3000) m at time 0 and the run
stops at 19800 s (5.5 h). The wind pushes the head fire south about 8.2 km.

## Source
- Repo: https://github.com/lautenberger/elmfire (official ELMFIRE git)
- Commit: 6500728e96ee3e8d95cee38d962452fa39bf6803 (2026-03-15)
- Files (unchanged, taken with `git show HEAD:<path>`; git blob hashes checked):
  - `inputs/01-constant-wind/01-run.sh` = `tutorials/01-constant-wind/01-run.sh`
  - `inputs/01-constant-wind/elmfire.data.in` = `tutorials/01-constant-wind/elmfire.data.in`
  - `inputs/functions/functions.sh` = `tutorials/functions/functions.sh` (the run script loads it)
- Docs: `docs/tutorials/tutorial_01.rst` in the same repo.
- Licence: Eclipse Public License 2.0.

The tutorial has no input data files. Its script `01-run.sh` makes all input rasters
(wind, moisture, fuel, slope, canopy...) as constant GeoTIFFs with GDAL. So the inputs
here are the script, the namelist template and the helper functions, nothing else.

## Engine
ELMFIRE 2025.1002, binary `elmfire_2025.1002`
(server: `/home/server/knowledge-dissection-toolkit/auto_dissect/_work/ELMFIRE/source/repo/build/linux/bin/`).
Also needs GDAL command line tools (`gdalwarp`, `gdal_calc.py`, `gdal_translate`,
`gdal_contour`), `bc`, `bash`, and a Python with `osgeo.gdal` + `numpy` to read results.
Runs in one process, about 7 s, about 105 MB RAM.

## How to run
```
/mnt/disk1/Hydrocraft_server/python_env/bin/python run_reference.py [--elmfire-bin PATH]
```
Engine lookup: `--elmfire-bin` -> `$ELMFIRE_BIN` -> `which elmfire_2025.1002` -> server path.
The script copies `inputs/` to a fresh temp dir, puts the engine on PATH as
`elmfire_2025.1002` (the name `01-run.sh` calls), runs `./01-run.sh` as the docs say,
reads the output GeoTIFFs and checks `expected.json`, then deletes the temp dir.
Exit 0 = PASS, 2 = checks failed, 3 = engine or tool missing (nothing run).
`--record` prints the measured values; `--keep` keeps the temp dir.

### One small change in the temp copy only
The official `elmfire.data.in` has `PATH_TO_GDAL = '/usr/bin'`. This server has no GDAL in
`/usr/bin`, and ELMFIRE then stops with `gdal_translate: not found`. In the temp copy
`run_reference.py` sets `PATH_TO_GDAL` to the folder that holds `gdal_translate` on PATH.
This only says where `gdal_translate` is (ELMFIRE uses it to turn input .tif into .bsq).
No model setting changes. The files in `inputs/` stay unchanged.

## Expected results
ELMFIRE ships no reference outputs for this tutorial, and its `verification/` folder has
scripts only, no results. So the values in `expected.json` come from real runs on this
server. Three clean runs gave byte-identical output GeoTIFFs (the model is deterministic).

Checks:
- finished normally: `01-run.sh` return code 0 and the engine line
  `End of simulation reached successfully` (the script always ends with `exit 0`, so the
  line is the real test)
- output time 19804 s; fire area printed by ELMFIRE 3852.1 acres
- burned cells 17320 (= 3851.88 acres, matches the printed area)
- time of arrival max 19804.2 s, mean 13193.8 s
- fireline intensity max 1218.3 kW/m, mean 916.1 kW/m
- spread rate max 81.13 ft/min, mean 61.01 ft/min
- burned area runs from y = 3135 m (a little north of the ignition, backing fire) to
  y = -5235 m (head fire runs south with the wind)
- 9 lines in `hourly_isochrones.shp`

Note: the tutorial doc text says the stop time is 22200 s, but the tracked `01-run.sh` sets
19800 s. The script is what runs.

## KI gaps (status 2026-10-06)
- **Fixed in `7cba7ea`:** `tools/run_elmfire.py` takes `--case-dir` so input folders resolve the
  way ELMFIRE's own layout expects, and it checks ELMFIRE's success line. Before: it looked for
  input folders relative to `inputs/` and stopped with
  `Fuels/topo directory not found: .../inputs/./inputs`, so the case is run with the official
  `01-run.sh` and the engine directly. The workaround in `run_reference.py` is kept so the case
  also runs with older tool versions.
- **Fixed in `7cba7ea`:** `tools/parse_elmfire_output.py` reads the `vs_*` spread-rate files and,
  when `fire_size_stats.csv` is gone, counts the area from the time-of-arrival raster. Before: it
  reported 0 acres (it needed `fire_size_stats.csv`, which the official script deletes) and 0
  spread rate (it looked for `spread_rate*`). `run_reference.py` reads the GeoTIFFs directly;
  the workaround is kept so the case also runs with older tool versions.
- **Partly fixed in `7cba7ea`:** `tools/run_elmfire.py` now checks that `PATH_TO_GDAL` holds
  `gdal_translate` and, if not, names the folder on PATH to use; still open: the KI does not set
  it by itself. Before: the official namelist hard-codes `PATH_TO_GDAL = '/usr/bin'`; on hosts
  where GDAL is elsewhere the KI should set it (see the change above).
