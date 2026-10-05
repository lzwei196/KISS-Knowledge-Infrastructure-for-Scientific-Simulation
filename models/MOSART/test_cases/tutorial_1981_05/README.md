# MOSART foundation test case: tutorial_1981_05

## What it is
The official mosartwmpy tutorial run: river routing plus water management (reservoirs,
demand, ISTARF reservoir release rules) over the whole CONUS on the NLDAS 1/8 degree grid
(224 x 464 cells, 80053 active), from 1981-05-01 to 1981-05-30, 3-hour step, daily output.
Runoff comes from the tutorial runoff file (it is the output of another land model; MOSART
only routes it).

## Source
- Model: mosartwmpy, https://github.com/IMMM-SFA/mosartwmpy (Python MOSART-WM).
- `inputs/config.yaml` = the repo's own tutorial config `notebooks/config.yaml`, taken with
  `git show HEAD:notebooks/config.yaml` at commit 54d715e (repo version 0.7.0). Unchanged.
- `inputs/input/...` = the official tutorial data, Zenodo record 6959736
  (doi 10.5281/zenodo.6959736, `mosartwmpy_tutorial_1981_05.zip`, md5
  4a1cdd8329a2e2f82fa0653f2acc19ab). This is the file that
  `mosartwmpy.utilities.download_data('tutorial')` fetches (listed in
  `mosartwmpy/data_manifest.yaml`). Downloaded again on 2026-10-05: the md5 matched Zenodo
  and every file matched the copy on this server bit for bit. Unchanged.
- Licence: mosartwmpy code BSD 2-Clause (Copyright 2021 Battelle Memorial Institute);
  tutorial data: Zenodo licence "other-open".
- Inputs total about 25 MB. sha256 of every file is in `manifest.json`.

## Engine
mosartwmpy 0.6.2 (PyPI) in `/mnt/disk1/Hydrocraft_server/models/MOSART/venv/bin/python`
(Python 3.12, pandas 3.0.3, numpy 2.4.6).

## How to run
```
python3 run_reference.py                      # uses the server venv
python3 run_reference.py --mosart-python /path/to/python   # or set MOSART_PYTHON
python3 run_reference.py --print-values       # also print every computed value
```
It copies the inputs to a fresh temp dir, runs the model through the KI tool
`tools/run_mosartwmpy.py --config config.yaml`, reads the output with the KI tool
`tools/parse_mosart_output.py` (basin sums) and with xarray, checks `expected.json`, and
deletes the temp dir. About 6 minutes, about 2.5 GB RAM.
Exit 0 = PASS, 2 = checks failed, 3 = no python that can import mosartwmpy (NOT run).

Two run settings are made only inside `run_reference.py` (inputs and model code untouched):
1. When pandas is 3 or newer, a small launcher sets the pandas option
   `future.infer_string = False` before the KI tool starts. See "Known KI gaps".
2. `NUMBA_NUM_THREADS=1`, so the run repeats exactly (see below).

## Expected results
The tutorial ships no reference output, so the values were recorded from real runs on this
server (2026-10-05). Two full runs gave exactly the same value for every check. Tolerance is
1e-6 relative (0 for counts). Checks (14 numbers plus "finished normally"):
- finished normally: KI tool rc 0, `[run_mosartwmpy] SUCCESS`, model log `Simulation completed`
- 30 daily records, first day 1981-05-01, last day 1981-05-30; KI parse tool returns 30 rows
- mean surface and subsurface runoff, max river discharge (21695.6 m3/s), total discharge on
  the last day, total routing storage and total reservoir storage on the last day,
  totals of reservoir supply, demand and unmet demand, and the final-state max discharge and
  storage reported by the KI run tool.

Proof the pandas setting does not change numbers: with ISTARF turned off (the only way the
run works without the setting), runs with and without the setting gave bit-identical output
and restart files (one thread).

## Known KI gaps (plain words, not fixed here)
- The MOSART venv has pandas 3.0.3. With it, mosartwmpy 0.6.2 stops in the first time step
  of this official tutorial: `ValueError: operands could not be broadcast together with
  shapes (103936,) (80053,) (80053,)` in `reservoirs/istarf.py`. Cause: pandas 3 keeps text
  columns (the reservoir `fit` column) as Arrow string arrays, not numpy arrays, so the
  model's mask step skips them. ISTARF is on by default, so the KI run tool fails on the
  tutorial as it is. The pandas option above works around it; a lasting fix is pandas < 3 in
  the venv or a note/workaround in the KI.
- `h5py` is not installed in the MOSART venv. mosartwmpy's own unit test
  (`mosartwmpy/tests/test_model.py`, grid in `tests/grid.zip`) needs it
  (`Grid.from_files` opens NetCDF with engine h5netcdf), so that test cannot run here. That
  test also has no stored reference output, which is why the tutorial was chosen.
- With many numba threads, mosartwmpy results change a little from run to run (domain
  totals moved by about 1e-4 for routing and 1e-3 for water management between two runs).
  This is why the case uses one thread.
- The preflight `import mosartwmpy` check can pass 45 s on a cold disk cache (it took 17 s
  warm). The import works.
