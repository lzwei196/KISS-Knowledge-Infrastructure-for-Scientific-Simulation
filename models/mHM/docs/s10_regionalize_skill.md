# s10_regionalize Skill

## Purpose

Transfer calibrated MPR global parameters from a gauged source basin to a target basin. This is the main mHM regionalization workflow in this KI.

## Inputs

- Calibrated parameter namelist, normally `FinalParam.nml` or `mhm_parameter_calibrated.nml` from s9.
- Target basin run directory prepared through s0-s7 with the same L0 data-source families.
- Source and target basin names for reporting.

## Outputs

- Updated target-basin `mhm_parameter.nml`.
- Transfer report in the target run directory, including source/target metadata.
- Forward-run-ready target basin for s7 and s8.

## Procedure

Prepare the target basin through s0-s7 using the same HWSD, GLiM, AVHRR, DEM/MERIT conventions as the calibration basin. Then transfer calibrated MPR parameters:

```bash
python tools/s10_regionalize/transfer_mpr_params.py \
  --calibrated_nml runs/source_basin/FinalParam.nml \
  --target_dir runs/ungauged_basin \
  --source_basin Bengbu \
  --target_basin Wangjiaba
```

Run the target basin forward:

```bash
python tools/s7_execute/run_mhm.py \
  --run_dir runs/ungauged_basin \
  --mhm_binary KISSPATH_BINARIES/mhm/mhm
```

Parse and compare outputs with s8 when observations or proxy benchmarks exist.

## Verification

Check that the target parameter file changed and remains bounded:

```bash
test -s runs/ungauged_basin/mhm_parameter.nml
find runs/ungauged_basin -maxdepth 2 -type f | rg "transfer|mhm_parameter"
python - <<'PY'
from pathlib import Path
p=Path("runs/ungauged_basin/mhm_parameter.nml")
assert p.exists() and p.stat().st_size > 0
print("target parameter file present")
PY
```

Before trusting the run, compare the target setup metadata and s2 command history so soil, geology, and land-cover data sources match the calibrated source basin.

## Traps

- `dt_s03` in `../diagnostics/triplets.yaml`: transfer degrades when source and target use different L0 soil, geology, or land-cover data sources.
- `dt_r08`: transferred parameter values must remain inside each parameter's lower/upper bounds.
- `dt_s12`: using the wrong AVHRR legend in either basin invalidates land-cover-dependent MPR transfer functions.
- `dt_s09`: regionalization cannot fix a target basin with the wrong drainage area.

## Example

After calibrating Bengbu and preparing Wangjiaba with the same HWSD/GLiM/AVHRR conventions, run:

```bash
python tools/s10_regionalize/transfer_mpr_params.py \
  --calibrated_nml runs/bengbu/FinalParam.nml \
  --target_dir runs/wangjiaba \
  --source_basin Bengbu \
  --target_basin Wangjiaba
```
