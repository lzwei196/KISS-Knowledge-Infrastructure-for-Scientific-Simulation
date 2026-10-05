# BMI — foundation test case: "heat_example"

BMI is an interface standard, not a model, so it has no data of its own. The official
example is the CSDMS reference model **BmiHeat** (2D heat equation on a plate) from
`csdms/bmi-example-python`. This case runs that example the way upstream shows it:
`examples/heat.yaml` plus the notebook `examples/run-model-from-bmi.ipynb`
(put a 100 K spike in the centre of a 6 x 8 plate, run 10 steps of 0.25 s).
`inputs/` are the unmodified upstream files (taken with `git show HEAD:<path>`).

| | |
|---|---|
| Engine | bmi-heat 2.1.3.dev0 (package `heat`, class `BmiHeat`), bmipy 2.0.1, numpy 2.4.3, scipy 1.17.1 |
| Source | https://github.com/csdms/bmi-example-python, commit `07016091d721410894ef8b16127fbe2ed063f0dd` (2024-10-21) |
| Licence | MIT (CSDMS) — `inputs/LICENSE` |
| KI | `BMI` |

## Files
- `inputs/heat.yaml` — official config (shape 6 x 8, spacing 1, origin 0, alpha 1)
- `inputs/run-model-from-bmi.ipynb` — official example notebook (the run script)
- `inputs/tests/*.py` — the 28 upstream unit tests
- `inputs/LICENSE` — upstream licence

## Run
```
python run_reference.py    # 0=PASS 2=FAIL 3=missing engine
```
It looks for a Python that can import `heat.bmi_heat`: `--heat-python` -> `$BMI_HEAT_PYTHON`
-> `python3` on PATH -> server default
`/home/server/knowledge-dissection-toolkit/auto_dissect/_work/BMI/venv/bin/python`.
It copies `inputs/` to a fresh temp dir and, in that Python:
1. runs the notebook's code cells in order (only the `!cat heat.yaml` shell line is skipped);
2. runs the same case through the KI's own `tools/bmi_runner.py`
   (`validate_inputs` -> `run_model` -> `validate_outputs`, spike injected at t=0 with
   `inject_schedule`, `end_time` 2.5) and the KI's `tools/compliance_checker.py` on `BmiHeat`;
3. calls each upstream unit test function (no pytest needed).
Then it checks `expected.json` and deletes the temp dir.

## Expected (recorded 2026-10-05; two clean runs gave identical numbers)
- dt 0.25 s, 48 cells, 10 steps, end time 2.5 s
- centre after 1 step 50.0; centre / max after 10 steps 6.084105186164379; min 0.0
- final plate sum 65.01314109191298 (the notebook's last printed number; heat leaves at the edges)
- KI runner: 10 steps, 10 CSV rows, final sum equal to the notebook's to 1e-9
- KI compliance checker: 41 functions implemented; BmiHeat follows BMI 2.0, so the checker (fixed in bac69b4) reports 41/41 required — get_bmi_version is BMI 2.1 only
- upstream unit tests: 28 passed, 0 failed

The notebook is saved without outputs and the repo has no reference output files, so the
values come from our own run, not from an official file. The case is deterministic: the
spike `set_value` replaces the random start field.

## Run-time tweak (no file changed)
The server venv's `heat` package is missing `heat/__init__.py` (its install RECORD lists it,
so it was removed after install). So `from heat import BmiHeat` fails there, while
`heat.bmi_heat` works. `run_reference.py` sets `heat.BmiHeat = heat.bmi_heat.BmiHeat` in
memory before the notebook and tests run. This only gives back the name that `__init__.py`
would export; the model code is the same file-for-file as upstream commit 0701609.

## KI gaps (status 2026-10-06)
- **Fixed in `077b3ba`:** `preflight_check.py` now checks `heat.bmi_heat.BmiHeat` in the BMI venv
  (override with `BMI_HEAT_PYTHON`). Before: it checked for modules `bmi` and `BmiHeat`, which do
  not exist, and only in `python_env`, so it showed 2 FAIL even when the example worked.
- **Fixed in `bac69b4`:** the `tools/bmi_runner.py` command line now imports `importlib` before use.
  Before: the CLI always failed with "Cannot load BMI class", so this case uses the tool's Python
  functions instead. The workaround in `run_reference.py` is kept so the case also runs with older
  tool versions.
- **Fixed in `bac69b4`:** `tools/compliance_checker.py` checks a class without `get_bmi_version` as
  BMI 2.0, so BmiHeat now gives 41/41. Before: it always checked 42 functions (BMI 2.1) and
  reported FAIL 41/42.
- **Still open:** `SKILL.md` quick start says grid shape `[10, 20]`; that is the default with no config.
  With the official `heat.yaml` the shape is `[6, 8]`.
