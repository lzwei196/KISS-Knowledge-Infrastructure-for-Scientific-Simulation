# MOM6 foundation test case: tc1 (low-resolution benchmark)

## What it is
`tc1` is one of MOM6's own test cases from its test suite (`.testing/tc1`). It is a small
version of the classic `benchmark` ocean setup: a 10 x 8 Mercator grid (90 deg wide,
41S to the equator), 8 layers, wind-driven gyres and a linear surface restoring. The grid,
sea floor, starting state and forcing are all built inside the model, so the case needs no
data files. It runs 0.25 day (24 steps of 900 s) in about 2 seconds.

The case runs twice:
1. on 1 MPI rank (normal run), and
2. on 2 MPI ranks split as `LAYOUT=2,1`.

MOM6's own test suite needs both runs to give byte-identical `ocean.stats` and diagnostic
checksums (`chksum_diag`). This package checks the same thing.

## Source
- Repo: https://github.com/NOAA-GFDL/MOM6, folder `.testing/tc1` (tracked in MOM6 git)
- Commit: `f52a2b361de7c577a6ded6229de37633ec753ab8` (branch dev/gfdl, 2026-03-24)
- The four files in `inputs/` (`MOM_input`, `MOM_override` (empty), `input.nml`,
  `diag_table`) were taken with `git show HEAD:.testing/tc1/<file>`; they are unmodified.
- Licence: Apache-2.0 (MOM6 `LICENSE`).

## Engine
- `MOM6` from the MOM6 `.testing` symmetric build:
  `/home/server/knowledge-dissection-toolkit/auto_dissect/_work/MOM6/source/repo/.testing/build/symmetric/MOM6`
  (FMS 2025.02.01, gfortran 13.3, Open MPI 4.1.6).
- Note: the source tree used for this build has one local change, in the solo driver
  `config_src/drivers/solo_driver/MOM_surface_forcing.F90` (it reads surface air pressure
  through data_override). That code only runs when data_override is used. tc1 uses
  analytic forcing (`WIND_CONFIG = "gyres"`, `BUOY_CONFIG = "linear"`), so it never reaches
  that code.

## How to run
```
/mnt/disk1/Hydrocraft_server/python_env/bin/python run_reference.py [--mom6-bin PATH] [--keep]
```
Binary lookup: `--mom6-bin` -> `$MOM6_BIN` -> `which MOM6` -> server default path above.
`mpirun` must be on PATH (or in `/home/server/.local/bin`) for the 2-rank run.
The script copies `inputs/` into a fresh temp dir per run, makes empty `INPUT/` and
`RESTART/` dirs, runs MOM6 through the KI tool `tools/run_mom6.py`, reads `ocean.stats`
with the KI tool `tools/output_parser.py`, checks `expected.json`, and deletes the temp dirs.
Exit codes: 0 PASS, 2 checks failed, 3 engine/dependency missing.

The only change made at run time (temp copy only) is in the 2-rank run: `MOM_override` gets
the line `LAYOUT=2,1`, the same line MOM6's `.testing/Makefile` writes for its layout test.
The identical-output checks show it does not change results.

## Expected results
MOM6 ships no stored reference `ocean.stats`; its test suite compares runs with each other.
So the values in `expected.json` come from real runs on this server. Two 1-rank runs and
one 2-rank run gave byte-identical `ocean.stats` and `chksum_diag`.

| check | value |
|---|---|
| finished normally | KI tool exit 0, `exitcode` file = 0, clock table shows `Total runtime` and `Termination` |
| ocean.stats records / final step / final day | 3 / 24 / 0.25 |
| energy per mass, day 0 -> day 0.25 [m2 s-2] | 0.44260260910129862 -> 0.46271773941971323 |
| max CFL at day 0.25 | 0.00012 |
| mean sea level at day 0.25 [m] | -4.8829e-09 |
| total mass [kg] | 7.87940e+19 (same as day 0) |
| mean salinity / mean temperature | 35.0000 PSU / 4.5248 degC |
| fractional mass error | 5.57e-17 (round-off level) |
| velocity truncations | 0 |
| 1-rank vs 2-rank (LAYOUT=2,1): differing lines in ocean.stats / chksum_diag | 0 / 0 |

## Known KI gaps
- `tools/run_mom6.py` requires an `INPUT/` folder even when the case reads no files; the
  script makes an empty one (the tool then warns "INPUT is empty").
- `tools/run_mom6.py` reports `n_timesteps` as 4 for this case: it counts the units header
  line of `ocean.stats` as a step. The real number of records is 3 (`output_parser.py`
  counts them right).
- Neither tool reads the `Truncs` column: they look for the word `Truncs` in each data row,
  but MOM6 only writes that word in the header. The script reads the column itself, and also
  reads the mass / salinity / temperature / error columns itself.
- The KI has no tool to build a grid, initial state, `MOM_input` or `diag_table`; it only has
  forcing and topography converters. That is fine here because tc1 is fully analytic.
