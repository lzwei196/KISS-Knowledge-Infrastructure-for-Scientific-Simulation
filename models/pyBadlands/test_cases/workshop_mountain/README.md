# pyBadlands test case: workshop_mountain

## What it is
The official Badlands workshop example "mountain". A flat surface at 10 m is pushed up for
50 million years by the uplift map in `data/uplift.csv`. Rain is a uniform 1 m/a until 15 Myr,
then the orographic rain model (wind 2 m/s from the south). Rivers only erode (stream power
law with `dep=0`), and hillslopes move by linear creep. Output every 250 kyr (201 outputs).

## Source
- Inputs: https://github.com/badlands-model/badlands-workshop, folder `examples/mountain`,
  commit 1bfad47aba2554945c5b6b645b10056df91d3bbf (2023-08-07). The workshop is linked from
  the Badlands docs (`badlands/docs/examples.rst` in the Badlands repo: "git clone https://github.com/badlands-model/badlands-workshop.git").
- Files are copied unchanged from a fresh clone: `mountain.xml`, `data/nodes.csv`,
  `data/uplift.csv`, `data/rain_gradient.csv` (the last one is in the official folder but the
  XML does not use it).
- Licence: GPL-3.0 (workshop and Badlands).

## Engine
Badlands 2.3.1 (https://github.com/badlands-model/badlands, local source commit a6d7b3a),
installed in its own venv (python 3.12, numpy 1.26.4; Badlands needs numpy < 2).

## How to run
```
python run_reference.py    # finds the pyBadlands python: $PYBADLANDS_PYTHON, then this
                           # python / python3 on PATH if it imports badlands, then the server venv
python run_reference.py --pybadlands-python /path/to/venv/bin/python
PYBADLANDS_PYTHON=/path/to/venv/bin/python python run_reference.py
```
It copies `inputs/` to a fresh temp folder, runs the model with the KI tool
`tools/s5_run/run_badlands.py` (inside the temp folder, because Badlands opens the XML's files
relative to the current folder), reads the output with `tools/s6_output/parse_badlands_output.py`,
checks `expected.json`, and deletes the temp folder.
Exit codes: 0 PASS, 2 checks failed, 3 no python that imports badlands (not run).
Run time is about 100 s and about 165 MB of memory.

## Expected results
The workshop ships no reference output, so the values in `expected.json` come from our own
runs on 2026-10-06. Three full runs in fresh temp folders gave bit-identical values. Checks
(15): finished normally (KI tool status and Badlands' own "tNow = 50000000" line), end time 50 Myr, 201 outputs ending at tin.time200, 16480 nodes,
start height 10 m, final height min/max/mean (10 / 2494.35 / 890.99 m), final cumulative
erosion min/max/mean, total erosion, and max discharge. Counts and times must match exactly;
real numbers within a relative 1e-6 (absolute 1e-6 for the one check whose value is 0).
A value that is not a finite number fails. Any run or read error (timeout, missing output,
bad JSON) gives exit 2.

## Known KI gaps
- In this KISS copy, `run_badlands.py` has a placeholder default engine path
  (`KISSPATH_INTERNAL_NOT_SHIPPED/...`), so `run_reference.py` always passes
  `--pybadlands-python` to it.
- The engine lives only in a separate pyBadlands venv (numpy < 2, `triangle`, badlands from
  source), not in the HydroCraft `python_env`. The current preflight already uses that venv by
  default (or `PYBADLANDS_PYTHON`) and passes 23/23 on this server (2026-10-06); an older
  preflight log from 2026-10-05 15:31 had failed because it checked `python_env`.
