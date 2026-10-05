# PySWMM — foundation test case: "storage_pump_outfall"

Official case: the pyswmm test model `pyswmm/tests/data/model_storage_pump.inp`, which
ships in the pyswmm git repo and is checked by pyswmm's own tests
(`pyswmm/tests/test_nodes.py`, `test_storage_7` and `test_outfalls_8`).
A small sewer: one subcatchment, junctions J1 and J2, pump P1 lifting water into storage
unit SU1, outfall J3. A steady 20 cfs inflow with a pollutant "test" enters at J1; SU1
fills to its full 5 ft and overflows. Dynamic-wave routing at 1 s, 2015-11-01 14:00 to
2015-11-04 00:00 (about 2 s to run).
`inputs/model_storage_pump.inp` is the unmodified file (`git show HEAD:...` at tag v2.1.0).

| | |
|---|---|
| Engine | pyswmm 2.1.0 + swmm-toolkit 0.17.0 (EPA SWMM 5.2.4), in `/mnt/disk1/Hydrocraft_server/python_env` |
| Source | https://github.com/pyswmm/pyswmm, tag v2.1.0 (commit 80b9d55), `pyswmm/tests/data/model_storage_pump.inp` |
| Licence | BSD-2-Clause (pyswmm) |
| KI | `PySWMM`, run tool `tools/run_pyswmm.py` |

## Run
```
python run_reference.py    # finds a python with pyswmm (or $PYSWMM_PYTHON_BIN, --python-bin); 0=PASS 2=FAIL 3=missing
```
It copies `inputs/` to a fresh temp dir, then:
1. runs the model through the KI's own `tools/run_pyswmm.py` and reads the `.rpt` it writes
   (start/end lines, continuity errors, outfall load);
2. runs the model once more the same way pyswmm's own tests do, and reads the SU1 storage
   and node statistics and the J3 outfall statistics those tests check.
The temp dir is deleted after the run.

## Expected results (recorded 2026-10-05)
Official values from `pyswmm/tests/test_nodes.py` (14 checks). Where the official test
gives two values (for example 4979 and 4980), the check takes the middle with a band of
half the gap plus 0.1%.
- SU1: max volume 5000 ft3, mean volume 4979–4980 ft3, max depth 5 ft, mean depth 4.9–5 ft,
  peak inflow and peak overflow about 3 cfs, overflow 57–58 h, overflow volume 621390–621393 ft3
- J3: 208796 steps, pollutant load 1756–1756.2 lbs, mean flow 8.9–9.0 cfs, peak 9.0–9.1 cfs,
  total inflow 1876800–1876900 ft3

This run gives 621394.5, 208797, 1756.2078 and 1876901.2 for the last ones: each within
0.001% of the official number. The official test uses `pytest.approx(rel=1)` (meant as 1%,
read by pytest as 100%), so its own band is very loose; the band here is much tighter.

Own-run checks (two clean runs gave the same numbers): the KI tool steps 208800 times
and reports status `completed`; report runoff continuity error 0.000%, flow routing
continuity error -0.002%, J3 total "test" load 1756.208 lbs. The report must contain
"Analysis begun on" and "Analysis ended on" and no ERROR.

## KI gaps (status 2026-10-06)
- **Fixed in `5bec039`:** `tools/parse_swmm_output.py` now asks for real swmm.toolkit output names and checks the `.out` file first. Before: with `--nodes`/`--system` it stopped with "Invalid Property: outflow", with `--links C2,P1` with "Invalid Property: setting", so output was read from the `.rpt` and from pyswmm statistics directly.
  The workaround in `run_reference.py` is kept so the case also runs with older tool versions.
- **Fixed in `5bec039`:** `tools/run_pyswmm.py` now reads the continuity errors after SWMM ends the run. Before: it reported `runoff_error` and `routing_error` as 0.0 (read too early), while the report says -0.002% routing error.
- **Still open:** SKILL.md names `build_inp.py` and `convert_domain_to_inp.py`, but these tools are not in
  `tools/` (only forcing and soil converters, the run tool and the parse tool exist).
  This case uses the official `.inp` as is, so it does not need them.
