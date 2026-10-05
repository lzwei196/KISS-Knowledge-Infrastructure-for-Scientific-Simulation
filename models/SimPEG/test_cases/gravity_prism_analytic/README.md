# SimPEG foundation test case: gravity_prism_analytic

## What it is
SimPEG's own gravity forward test, `tests/pf/test_forward_Grav_Linear.py`. It builds a
small 3-D model of two nested dense blocks (an outer 3.2 m cube of 1 g/cc with an inner
1.6 m cube of 2 g/cc), computes the gravity field at a 5 x 5 grid of receivers 3 m up, and
compares it with the exact (analytic) prism answer from `geoana`. Because the reference is
an exact formula, this is a strong check that the SimPEG gravity engine is right.

The case has two parts:

- **Part A - official tests.** Runs the official pytest tests
  `test_accelerations_vs_analytic`, `test_tensor_vs_analytic` and `test_guv_vs_analytic`
  (selection `-k "analytic and geoana"`). That is 36 tests: tensor and tree mesh, serial and
  parallel, sensitivities in RAM / on disk / forward only. The tolerances are the ones
  written in the test file (gx/gy/gz: rtol 1e-9, atol 1e-6 mGal; gradients: rtol 2e-6,
  atol 1e-6 Eotvos).
- **Part B - same model, set up like the KI tool.** Takes the mesh, blocks, density and
  receivers straight from the official test fixtures (nothing re-typed), writes them as the
  KI tool's `mesh_config.json` / `model_config.json`, runs gz forward with all cells active
  and zero density outside the blocks (as `tools/run_simpeg.py` does), and compares the 25
  gz values with the official analytic gz, using the official tolerance.

## Source
- Repo: https://github.com/simpeg/simpeg, commit `ba60041a81907bb7b50f5e59c6be21441959ed8f`
  ("Cherry-pick changelog for v0.25.2"). Files taken with `git show HEAD:<path>` from the
  dissection copy, so they are pristine.
- `inputs/tests/pf/test_forward_Grav_Linear.py`, `inputs/tests/conftest.py`, and the two
  `__init__.py` files - unmodified.
- Licence: MIT (SimPEG Developers).
- All model data is defined inside the official test file. No download, no server data.

## Engine
- Python: `/mnt/disk1/Hydrocraft_server/python_env/bin/python` (3.12), the one the KI
  preflight checks.
- SimPEG 0.25.2 installed in python_env site-packages (the `potential_fields` code is the
  same as the git commit above), discretize 0.12.0, geoana 0.8.1, numpy 2.4.4, pytest 9.0.3.
- `choclo` (optional fast engine) is not installed, so the choclo test variants are left
  out by the `-k` selection. Nothing else is left out of the three analytic tests.

## How to run
```
python run_reference.py                       # uses python_env by default
python run_reference.py --python-bin /path/to/python
SIMPEG_PYTHON_BIN=/path/to/python python run_reference.py
```
The script copies `inputs/` to a fresh temp dir, runs everything there with
OMP_NUM_THREADS=4 and MPLBACKEND=Agg, checks `expected.json`, and deletes the temp dir.
Exit 0 = PASS, 2 = a check failed, 3 = no python with simpeg/discretize/geoana/pytest.
Run time is about 30 s, under 0.5 GB RAM.

## Expected results
From the official analytic reference (not from our own run), official tolerance:

| check | expected |
|---|---|
| official pytest | 36 passed, 0 failed, return code 0 |
| mesh cells / cells in blocks | 74088 / 4096 |
| receivers, finite values, values within official tol | 25 / 25 / 25 |
| gz min (centre, above the blocks) | -0.0256046422 mGal |
| gz max (grid corner) | -3.2077721e-05 mGal |
| gz mean | -0.00120689804 mGal |
| largest abs difference vs analytic | under 1e-6 mGal (seen 1.2e-15) |

Two clean runs gave the same numbers.

## Known KI gaps
- `tools/run_simpeg.py` cannot run this case (or any gravity / magnetics forward) with the
  installed SimPEG 0.25.2. In `build_simulation()` it calls
  `gravity.survey.Survey(source_list=[source])` (and the same for magnetics), but SimPEG
  0.25 wants `Survey(source_field)`. It stops with
  `TypeError: Survey.__init__() missing 1 required positional argument: 'source_field'`.
  So Part B calls the engine directly with the same set-up as the KI tool. The script still
  tries the KI tool once and prints whether it works, but the checks do not depend on it.
- The KI tool only supports tensor meshes with all cells active and the `gz` component, so
  the tree-mesh and gradient parts of the official test are covered only by Part A.
