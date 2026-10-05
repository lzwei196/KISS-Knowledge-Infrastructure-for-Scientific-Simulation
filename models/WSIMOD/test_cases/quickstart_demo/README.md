# WSIMOD foundation test case: quickstart_demo

## What it is
WSIMOD's own quickstart example. One land area (10 urban + 100 rural area units) gets daily
rain, temperature and et0 for the "oxford_land" site from 2009-03-03 to 2013-02-25
(1456 daily steps). Water goes from the land to a sewer, to groundwater and to a river node,
and leaves through an outlet. The model writes `flows.csv`, `tanks.csv` and `surfaces.csv`.

## Source
- Repo: https://github.com/ImperialCollegeLondon/wsi (WSIMOD), commit
  `2f55314d054dd7b29253da1b9c3514f496d4648f` (2026-03-23).
- Files (unmodified, taken with `git show HEAD:<path>`):
  - `docs/demo/examples/quickstart_demo.yaml` -> `inputs/quickstart_demo.yaml`
  - `docs/demo/data/processed/timeseries_data.csv` -> `inputs/timeseries_data.csv`
- Upstream runs this exact file in `tests/test_example_files.py` (it only checks the three
  output CSVs are written).
- Licence: BSD-3-Clause.

## Engine
Python package `wsimod` version `0.1.dev1+g2f55314d0`, run from the repo source by putting the
repo folder on `PYTHONPATH` (it is not pip-installed in python_env). Python 3.12.3,
pandas 3.0.0, numpy 2.4.4 (`/mnt/disk1/Hydrocraft_server/python_env/bin/python`).

## How to run
```
/mnt/disk1/Hydrocraft_server/python_env/bin/python run_reference.py [--wsimod-src <wsi repo dir>]
```
wsimod lookup: `--wsimod-src` -> `$WSIMOD_SRC` -> already importable -> server default
`/home/server/knowledge-dissection-toolkit/auto_dissect/_work/WSIMOD/source/repo`.
The script copies `inputs/` to a fresh temp dir, runs the KI tool `tools/run_wsimod.py
--mode api` (same code path as the official `wsimod` CLI), reads the output with
`tools/parse_wsimod_output.py --summary` and pandas, checks `expected.json`, and deletes the
temp dir. Exit 0 = PASS, 2 = checks failed, 3 = wsimod (or a dependency) missing.
The run takes about 1 second.

The only setting changed at run time is the output folder: `--outputs <temp>/out` replaces
`outputs: results/quickstart_results` from the yaml. This is the official CLI option; no input
file is edited.

## Expected results
No official reference numbers ship with this demo, so the values in `expected.json` were
recorded from real runs on this server (2026-10-05). Two clean runs through the KI tool and one
run through the official `python -m wsimod quickstart_demo.yaml -i . -o out` gave byte-identical
output files, so the run is deterministic.

| check | value |
|---|---|
| daily steps | 1456 |
| flow / tank / surface records | 8736 / 7280 / 2912 |
| outlet flow total / max / mean | 121.568137 / 0.510288 / 0.0834946 |
| baseflow total | 65.411520 |
| sewer storm outflow total | 16.172 |
| rain total / evaporation total | 325.149 / 155.753295 |
| final groundwater storage | 26.343380 |
| final rural soil storage | 14.676065 |
| water balance (rain - evap - outlet - end storage) | about 2e-14 (closes) |

Extra check (not in this package): the upstream unit test
`tests/test_model.py::TestModel::test_run` (same network, one day, hand-set inputs, asserts
outlet flow 0.05 and urban storage 0.03) was run on this server and passed.

## KI gaps (status 2026-10-06)
- **Fixed in `b8854c6`:** the preflight now imports `wsimod` from the repo source on `PYTHONPATH`, as the KI tools do, and no longer says to pip install. Before: it failed on `import wsimod` in python_env and said to pip install.
- **Still open:** `tools/run_wsimod.py` only works when the caller sets `PYTHONPATH` to the wsimod source;
  its own error message also says to pip install.
- **Still open:** `tools/run_wsimod.py --mode cli` calls `python` from PATH, not the current interpreter
  (not used here; this case uses `--mode api`).
- **Still open:** No KI tool builds the settings yaml (nodes/arcs graph): the forcing tool takes a user CSV and
  the parameter tool takes typed-in numbers. This case uses the official yaml as-is.
