# LISFLOOD test case: lat_lon_short

## What it is

This is LISFLOOD's own official test case. It is the "short" run of the lat/lon use case
in the upstream test suite (`tests/test_latlon.py::TestLatLonShort`). It runs a small
catchment on a lat/lon grid for 32 days (01/01/2016 to 01/02/2016, daily steps) and checks
the river flow at one gauge (-122.55, 52.95) against the official reference results that
ship with the test.

## Source

- Repo: https://github.com/ec-jrc/lisflood-code
- Commit: fe94c33b6bd9fe09fa7be43a6dd4fdc8a11f744c (VERSION 4.3.1)
- Folder: `tests/data/LF_lat_lon_UseCase` and the test `tests/test_latlon.py`
- Licence: EUPL-1.2 (European Union Public Licence)

`inputs/` holds the unmodified official files, taken from `git show HEAD:` of that commit
(sha256 of every file checked against git). Only the 96 files the short run reads are kept
(found by tracing the file calls of a full run), plus the two reference files used for the
check. The full use case folder is 34 MB; this package is about 21 MB.

- `inputs/run_lat_lon.xml` - the official settings file
- `inputs/reference/lzavin.map`, `inputs/reference/avgdis.map` - start maps (read via PathInit)
- `inputs/reference/dis_short.tss` - official discharge result for the short run
- `inputs/reference/chanqWin_short.tss` - official channel inflow result for the short run
- `maps/`, `meteo/`, `landuse/`, `lai/`, `soilhyd/`, `wateruse/`, `mapstables/`, `inflow/`,
  `tables/` - the model inputs

## Engine and environment

- LISFLOOD (lisflood-model) 4.3.1, run as `lisflood <settings.xml>`.
- It needs LISFLOOD's OFFICIAL conda env, built from the repo's own `environment.yml`:
  python 3.7, numpy 1.21.6, xarray 0.20.2, dask 2022.2.0, pandas 1.3.5, netCDF4 1.5.8,
  pcraster 4.3.3, gdal 3.5.0, lisflood-utilities 0.12.19.
  On this server: `/home/server/miniconda3/envs/lisflood_official/bin/lisflood`.
- Why this env: the older GeoForge env (`/home/server/miniconda3/envs/lisflood`, python 3.11,
  newer xarray/dask) stops on these official files with an xarray/dask chunking error
  (the lat dimension is split into chunks inside `apply_ufunc`). The official env has the
  library versions the LISFLOOD team tested with.
- `lisflood-utilities` must be in the same env: its `TSSComparator` is the official checker.

## How to run

```
python run_reference.py [--lisflood-bin /path/to/official_env/bin/lisflood] [--keep]
```

Engine lookup order: `--lisflood-bin` -> `$LISFLOOD_BIN` -> `which lisflood` ->
`/home/server/miniconda3/envs/lisflood_official/bin/lisflood`. Any python 3 can run the
script; it uses the `python` next to the chosen `lisflood` for the official comparator.

The script copies `inputs/` to a fresh temp dir, makes the settings changes below in the
temp copy only, puts the engine's `bin/` first on PATH, starts LISFLOOD through the KI tool
`tools/run_lisflood.py` (its `run_model` function), checks the results, and deletes the
temp dir. Exit 0 = PASS, 2 = checks failed, 3 = engine or dependency missing.
A run takes a few seconds.

Settings changes (temp copy only, all path or date values):

| textvar | official file | used | why |
|---|---|---|---|
| StepStart | 02/01/1986 00:00 | 01/01/2016 00:00 | same as the upstream test |
| StepEnd | 01/01/2018 00:00 | 01/02/2016 00:00 | same as the upstream test |
| PathOut | $(PathRoot)/reference | $(PathRoot)/short | same as the upstream test |
| PathRoot | $(SettingsPath) | full temp path | same folder; the KI tool cannot read `$(SettingsPath)` |

The PathRoot change points to the same folder, so it does not change results: the output
values are byte-identical to the official reference files.

## Expected results

All expected numbers come from the official reference files `reference/dis_short.tss` and
`reference/chanqWin_short.tss`, with the official tolerance (atol 1e-4, rtol 1e-3).
The script checks:

1. finished normally: return code 0 and LISFLOOD's last step line `10988 - 01/02/2016 00:00`
2. the official `lisfloodutilities` `TSSComparator` passes for `dis_run.tss` and
   `chanqWin.tss` (this is exactly what `tests/test_latlon.py` checks for dis)
3. each of the 32 daily values within tolerance of the reference
4. summary numbers for dis and chanqWin: number of steps (32), first/last step (10957/10988),
   first, last, max, min and mean value

| output | first | last | max | min | mean (m3/s) |
|---|---|---|---|---|---|
| dis | 277.818 | 521.923 | 527.439 | 277.818 | 483.469 |
| chanqWin | 280.699 | 535.156 | 535.156 | 280.699 | 486.901 |

On 2026-10-05 the run matched the official reference files exactly (every value the same;
only the header line with the settings path and date differs). Two runs gave the same values.

## Known KI gaps

These are gaps in the KI run tool `tools/run_lisflood.py`; they were not fixed here.

1. The tool's command-line preflight rejects this official settings file. It does not
   expand nested `$(...)` values, and later `<lfbinding>` entries (like
   `MaskMap = $(MaskMap)`, `DtSec = $(DtSec)`) overwrite the real `<lfuser>` values, so it
   reports "MaskMap not found: .../$(MaskMap)" and "Invalid DtSec: $(DtSec)" and exits 1.
   So the script calls the tool's `run_model()` function directly instead of its CLI.
2. The tool does not expand `$(SettingsPath)`, so PathRoot is written as a full path in the
   temp copy.
3. The tool calls bare `lisflood` from PATH (then `python -m lisflood.main`); it has no way to
   choose the engine env. The script puts the official env's `bin/` first on PATH.
4. The tool's `validate_output` looks for `dis.nc`; this case writes only `.tss` files, so the
   script reads the `.tss` files itself (and with the official `TSSComparator`).
5. The KI's preflight (`preflight_check.py`) points at the older env
   `/home/server/miniconda3/envs/lisflood`, which fails on these official files (see above).
