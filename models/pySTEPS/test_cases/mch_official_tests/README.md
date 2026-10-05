# pySTEPS foundation test case: official tests on the official MeteoSwiss radar sample

## What it is
pysteps ships its own test suite (`pysteps/tests`). Many of those tests read the official
example radar data from the pysteps-data repository and check results against fixed
values written in the test files (for example, the STEPS ensemble nowcast must reach a
CRPS below a set limit). This case runs those official tests on the official MeteoSwiss
(mch) sample, 2015-05-15 15:45 to 19:00 UTC, 5-minute frames.

It covers:
- nowcasts: STEPS, S-PROG, ANVIL, SSEPS, LINDA, nowcast utils
- motion: Lucas-Kanade, VET, DARTS, Proesmans
- semi-Lagrangian extrapolation, FFT noise generators, cascade
- verification scores (categorical, continuous, probabilistic)

## Source
- Code and tests: pysteps 1.20.0 (pip wheel, https://github.com/pySTEPS/pysteps), BSD-3-Clause.
  The tests come with the installed package (`pysteps.tests`); they are not copied here.
- Data: https://github.com/pySTEPS/pysteps-data, folder `radar/mch/20150515`, commit
  `e95a6efae3df33ae8cd1e54e6762ab5f83427a03`. All 40 files (2.3 MB) are in
  `inputs/radar/mch/20150515/`, unmodified. Each file was checked against its GitHub blob hash.
  pysteps-data has no licence file; it is the official pysteps example data.

## Engine
`/mnt/disk1/Hydrocraft_server/python_env/bin/python` with pysteps 1.20.0,
opencv 4.11.0, Pillow 10.4.0, pytest 9.0.3.

## How to run
```
python run_reference.py [--python /path/to/python]
```
Python lookup: `--python` -> `$PYSTEPS_PYTHON` -> the python running the script (if it has
pysteps) -> `/mnt/disk1/Hydrocraft_server/python_env/bin/python`.
Exit codes: 0 PASS, 2 checks failed, 3 dependency missing (nothing run).
Takes about 90 s and 1.4 GB RAM (thread pools are set to 4).

What the script does:
1. Copies the 40 GIF files to a fresh temp dir.
2. Writes a temp copy of the installed default `pystepsrc` where only the `mch` root_path
   is changed from the relative `./radar/mch` to the temp folder, and sets `$PYSTEPSRC`.
   This is a path change only; no data or setting that affects results is changed.
3. Runs 14 official test modules with pytest (list in `expected.json`). One test,
   `test_cascade::test_decompose_recompose`, is left out because it reads the Australian
   (bom) sample, which is not packaged.
4. Re-runs the 8 official STEPS skill settings from `test_nowcasts_steps.py` (seed 42)
   and records each CRPS.
5. Deletes the temp dir.

## Expected results
- 130 official tests pass, 0 failed, 0 errors, 0 skipped (the test files' own asserts).
- STEPS CRPS (+15 min, 5 members), official limit from the pysteps test file, and our value:

| case | setting | official limit | our value |
|---|---|---|---|
| 0 | default (no mask, no prob. matching), spatial | < 1.30 | 1.25653 |
| 1 | same, timesteps as list [3] | < 1.30 | 1.25709 |
| 2 | mask incremental | < 7.32 | 7.31281 |
| 3 | mask sprog | < 8.40 | 8.39315 |
| 4 | mask obs | < 8.37 | 8.36594 |
| 5 | prob. matching cdf | < 0.60 | 0.57799 |
| 6 | prob. matching mean | < 1.35 | 1.30602 |
| 7 | mask incremental + cdf, spectral | < 0.60 | 0.57591 |

The test counts and the CRPS limits are official. The exact CRPS values were recorded from
our own run on 2026-10-05; two clean runs gave identical values (tolerance 1e-4).

## Known KI gaps
The KI tools could not drive this case, so pysteps was run directly:
- The KI tools do not run the pysteps test suite (pytest); there is no tool for it.
- `tools/s1_data_import/import_radar_data.py --format mch_gif` fails on these official files:
  it calls `import_mch_gif(file)` without the required `product`, `unit`, `accutime`
  arguments, so every frame is skipped ("No frames successfully imported").
- `tools/s3_nowcast/run_nowcast.py --method steps` passes `R_thr=` to
  `pysteps.nowcasts.steps.forecast`; pysteps 1.20.0 has no such argument (it is now
  `precip_thr`) and takes no extra keyword arguments, so the STEPS call would raise a TypeError.
  (Checked from the function signature; not run end to end because s1 already fails.)
