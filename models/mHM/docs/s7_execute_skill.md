# s7_execute Skill

## Purpose

Run the actual mHM binary for the prepared basin. This stage must execute `KISSPATH_BINARIES/mhm/mhm` or the binary path in the run config; do not replace it with a simplified formula.

## Inputs

- Complete run directory from s0-s6.
- mHM binary path.
- Timeout in seconds.
- Morphology, forcing, gauge, latlon, namelist, and parameter files already present.

## Outputs

- mHM logs and model outputs under the run directory.
- `output_b1` NetCDF files such as `mHM_Fluxes_States.nc` and `mRM_Fluxes_States.nc`.
- Gauge discharge output such as `daily_discharge.out` when configured.

## Procedure

Run preflight, then execute through the stage wrapper:

```bash
python preflight_check.py

python tools/s7_execute/run_mhm.py \
  --run_dir runs/wangjiaba \
  --mhm_binary KISSPATH_BINARIES/mhm/mhm \
  --timeout 3600
```

If the wrapper reports a model error, check `../diagnostics/triplets.yaml` before changing tools or inputs.

## Verification

Confirm that mHM finished and wrote expected output files:

```bash
find runs/wangjiaba -maxdepth 3 -type f | rg "mHM_Fluxes_States|mRM_Fluxes_States|daily_discharge|ConfigFile"
rg -n "mHM: Finished|Finished|ERROR|WARNING|L2_variable_init|POSITION_NML" runs/wangjiaba -g "*.log" -g "*.out" || true
```

If the process exits cleanly during calibration, also verify calibration artifacts in s9; Fortran `stop` can return status 0.

## Traps

- `dt_r09` in `../diagnostics/triplets.yaml`: undefined class ids or nodata leakage can produce NaN output.
- `dt_r10`: excessive L0 cell count can make runtime far slower than expected.
- `dt_v001`: near-zero gauge discharge with nonzero gridded runoff usually means a coordinate-system flag problem.
- `dt_v002`: nonzero routed field with zero gauge column can mean the gauge is on the wrong L11 cell.
- `dt_r13`: a flow-direction cycle can make startup hang after `Initialize domains ...`.

## Example

After s6 writes namelists for `runs/wangjiaba`, execute:

```bash
python tools/s7_execute/run_mhm.py --run_dir runs/wangjiaba --timeout 3600
```
