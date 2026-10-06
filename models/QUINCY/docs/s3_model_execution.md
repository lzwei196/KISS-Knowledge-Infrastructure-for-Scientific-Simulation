# s3 — Model execution: `run_quincy_engine.py`

## Purpose
Run the real engine headless in a fresh directory with an honest success test.

## Inputs
`--mode land|plant|canopy` with `--climate_dir` (climate.dat + climate_meta.json) and `--site_config`;
or `--mode test_canopy|test_radiation`. Options: `--spinup_years` (default 500, 0 = static run),
`--spinup_cycle_years`, `--output_interval` (daily), `--output_set` (basic), `--param_list`,
`--nml group.key=value` (repeatable), `--reference_dir` (test modes).

## Outputs
In `--run_dir`: `qs.namelist`, `climate.dat`, engine text outputs `*_daily.txt` and
`*_spinup_yearly.txt`, `quincy_standalone.log/.err`, `stdout.log`, `run_manifest.json`
(namelist, binary sha256, forcing meta, status, problems).

## Procedure
```
$PY tools/run_quincy_engine.py --mode land --run_dir case/run --climate_dir case/climate \
    --site_config case/site_config.json --spinup_years 500
```
Transient protocol: the first `--spinup_cycle_years` forcing years are cycled for `--spinup_years`
from bare ground (yearly spin-up files), then the file is rewound and all forcing years are run.
Run time is about 1-4 s per simulated year at a 30-min step (machine-load dependent).

## Verification (what exit 0 means)
- engine exit code 0 AND "End QUINCY model" in stdout AND empty `quincy_standalone.err`
  AND no "Please check!" consistency warning in the engine log;
- the eight key daily files exist with `n_years × 365` rows; spin-up files have `spinup_years` rows;
- before the run: climate.dat rows/years equal climate_meta.json; every set namelist value reads back.
Exit codes: 2 bad input (engine not started), 3 engine failed, 4 outputs missing/short/different.

## Traps
- Engine `finish()` exits 0 (dt_quincy_026); short forcing is silently rewound (dt_quincy_027).
- A duplicated namelist group is ignored after the first copy (dt_quincy_031).
- Too short spin-up: low GPP, LAI still growing (dt_quincy_034).
- `run_dir` must be empty — the tool refuses a used one so old outputs cannot pass as new.

## Example
`outputs/quincy_fihyy_real_engine/run/run_manifest.json`.
