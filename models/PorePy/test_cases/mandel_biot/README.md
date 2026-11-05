# PorePy — foundation test case: "mandel_biot"

Official foundation case: **Mandel's problem**, PorePy's own built-in example
(`src/porepy/examples/mandel_biot.py`) run the way PorePy's own functional test
(`tests/functional/test_mandel.py`) runs it. Mandel's problem is a classic
poroelastic (Biot) consolidation problem with an exact analytical solution, so the
model is checked against the exact answer, not only against an older run.
`inputs/` are the two unmodified files from the PorePy git tree.

| | |
|---|---|
| Engine | PorePy 1.12.0 (Python), git `e4a9a212f3d231aee37c7bc469b78e418f87015f` (2026-03-23) |
| Source | github.com/pmgbergen/porepy: `src/porepy/examples/mandel_biot.py`, `tests/functional/test_mandel.py` |
| Licence | GPL-3.0 (PorePy) |
| KI | `PorePy` |

## Run
```
python run_reference.py    # finds a Python with porepy (or $POREPY_PYTHON, --porepy-python); 0=PASS 2=FAIL 3=missing
```
It copies `inputs/` to a fresh temp dir and runs a small driver script there with the
engine Python (threads capped at 4):
- run A: `MandelModel`, times 0, 25, 50 s (dt 25 s), 612 cells. At 25 s and 50 s it
  computes the errors of pressure, flux, displacement, poroelastic force and the
  degree of consolidation against the exact solution.
- run B: one 10 s step, unscaled and scaled (mm, g) units; the errors must agree.
This is the same setup as the official test. pytest is not in the engine venv, so the
driver does the test's work directly. Runtime is about 1 s.

## Expected (official values)
The 12 error values and their tolerances (atol 1e-5, rtol 1e-3) are copied from
`desired_errors` in the official test; `run_reference.py` re-reads them from
`inputs/test_mandel.py` and fails if `expected.json` differs. Examples:
- t = 25 s: pressure 0.02492, flux 0.3589, displacement 0.000743, force 0.00774
- t = 50 s: pressure 0.01616, flux 0.1663, displacement 0.000708, force 0.00491
- scaled minus unscaled error (pressure, displacement) < 1.5e-4 (the test's `decimal=4`)
- plus: 2 result times saved, end time 50 s, return code 0 and the driver's success line.
Two clean runs on 2026-10-05 gave the same numbers.

## KI gaps (status 2026-10-06)
- **Fixed in `59460d6`:** `run_porepy.py --example` uses the porepy 1.12 class names
  (`MandelModel`, `TerzaghiModel`, `TracerFlowModel`) with the official settings, returns
  numbers, and finds the PorePy venv itself. Before: it imported `MandelSetup` (no such class
  in 1.12), ran with empty parameters and returned no numbers, so this case runs the engine
  directly. The workaround in `run_reference.py` is kept so the case also runs with older tool versions.
- **Still open:** `run_porepy.py` has no way to run a user script; `--model/--config` only builds a
  generic model, not this example.
- **Partly fixed in `7b33e8f`:** the preflight now shows the missing `pypardiso` as a plain
  optional warning (PorePy falls back to the SciPy solver); `pypardiso` is still not
  installed. Not needed for this case.
- **Still open:** The KI parse tool (`parse_porepy_output.py`) is not used: the test writes no files
  (`times_to_export: []`), the errors come straight from the model.
