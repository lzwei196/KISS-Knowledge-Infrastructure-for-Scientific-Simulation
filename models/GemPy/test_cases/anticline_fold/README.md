# GemPy foundation test case: anticline_fold

## What it is
GemPy's own official **anticline (fold) example model** (`ExampleModel.ANTICLINE`).
Two layers (rock2 on top of rock1, plus basement) are bent into an anticline. GemPy builds
a 3D geological model from 36 surface points and 2 orientations by implicit interpolation
(universal co-kriging) on an octree grid.

- Box: 0-1000 m in x, y and z. Octree refinement 5 (finest level = 32 x 32 x 32 cells).
- One series `Strat_Series` = (rock2, rock1). NumPy backend.

## Source (official only)
- Model code: `gempy/API/examples_generator.py::_generate_anticline_model`,
  GemPy git `cgre-aachen/gempy` commit `e46fee7` (2026-03-23, v2026.0.1a1 line).
- Test that asserts the result: `test/test_model_types/test_example_models_I.py::test_generate_fold_model`.
- Input data: `cgre-aachen/gempy_data`, commit `cf00bc907d3e6962967da38ae2ad19d770df956e`,
  `data/input_data/jan_models/model2_surface_points.csv` and `model2_orientations.csv`
  (the files GemPy's generator reads from GitHub). Copied unmodified into `inputs/`.
- Official reference: `reference/anticline_scalar_field.approved.txt` is an unmodified copy of
  GemPy's approved test file
  `test/test_model_types/test_example_models_I.test_generate_fold_model.Anticline Scalar Field.approved.txt`.
- Licences: GemPy EUPL-1.2; gempy_data LGPL-3.0.

## Engine
gempy `2026.0.1a2.dev0+ge46fee77b`, gempy_engine `2026.0.1a0`, Python 3.12, numpy 2.4.3,
in `/home/server/knowledge-dissection-toolkit/auto_dissect/_work/GemPy/venv/bin/python`
(gempy is not installed in the shared python_env). This is the Python the KI preflight uses.

## How to run
```
python3 run_reference.py                       # finds the GemPy Python by itself
python3 run_reference.py --gempy-python /path/to/python   # or set GEMPY_PYTHON
```
It copies `inputs/` to a fresh temp dir, runs, checks `expected.json`, and deletes the temp dir.
Exit 0 = PASS, 2 = checks failed, 3 = no Python with gempy found. Takes a few seconds.

The run uses the same calls as GemPy's generator. The only change: the two CSV paths point to
the local copies in `inputs/` instead of the GitHub URL (same bytes, sha256 in manifest.json).

## Expected results
- **Main check (official):** the 51 scalar-field values that GemPy's own test samples
  (every int(n/50)-th finest-level octree center) must match the approved file with GemPy's own
  tolerance (`np.allclose`, rtol = atol = 1e-5). Our run matches to about 5e-9.
- **Extra checks (own run, two clean runs gave identical numbers):** 5 octree levels,
  7808 finest-level points, 32768 block cells split 11628 / 6500 / 14640 between rock2 / rock1 /
  basement, min / max / mean of the finest-level scalar field, and the KI parse tool reading
  1 group, 2 surfaces and 32768 grid points from the saved model.
- Finished check: the engine script exits 0 and prints `DRIVER_OK` after compute and save.

## Known KI gaps
- `tools/run_gempy_model.py` (params + CSV mode) builds and **computes** this model fine, but then
  calls `gp.save_model(model, path=..., name=...)`. This GemPy version's `save_model` has no
  `name` argument, so the tool stops with "save_model() got an unexpected keyword argument
  'name'" and reports `status: error` with no model file. Because of this, `run_reference.py`
  runs the engine directly (official generator code) and only calls the KI run tool for
  information (its message is printed as `[info]`).
- `tools/run_gempy_model.py --example horizontal_strat` is not GemPy's official horizontal
  example: it builds a hand-made model with one point per layer on a 20 x 20 x 20 grid. It is not used here.
- `tools/parse_gempy_output.py --extract summary` works on the saved model and is used for
  three checks. Its summary shows `project_name: "unknown"` (the name is not read back).
