# s9_calibration Skill

## Purpose

Configure and run mHM's built-in DDS or SCE optimizer, then extract the best MPR global parameters for later forward validation or s10 transfer.

## Inputs

- A fully working forward-run directory from s0-s8.
- `mhm.nml`, `mhm_parameter.nml`, forcing, morphology, and gauge files.
- Optimizer method: `1` for DDS or `3` for SCE.
- Discharge objective function, normally `1` for `1 - NSE(Q)` or `9` for `1 - KGE(Q)`.
- Iteration count, at least 6 and realistically hundreds or thousands.
- Optional basin type preset such as `humid_subtropical`.

## Outputs

- Calibration-enabled `mhm.nml`.
- mHM optimizer outputs such as `FinalParam.nml` and DDS/SCE result files when the binary completes.
- Parsed calibrated parameter file or report from `tools/s9_calibration/setup_mhm_calibration.py --parse_results`.

## Procedure

Configure calibration:

```bash
python tools/s9_calibration/setup_mhm_calibration.py \
  --run_dir runs/wangjiaba \
  --opti_method 1 \
  --opti_function 1 \
  --n_iterations 2000 \
  --basin_type humid_subtropical
```

Verify optimizer settings immediately before execution:

```bash
rg -n "opti_function|nIterations|opti_method" runs/wangjiaba/mhm.nml
```

Execute calibration with the real mHM binary:

```bash
python tools/s9_calibration/setup_mhm_calibration.py \
  --run_dir runs/wangjiaba \
  --execute
```

Parse results:

```bash
python tools/s9_calibration/setup_mhm_calibration.py \
  --run_dir runs/wangjiaba \
  --parse_results
```

## Verification

Do not rely on exit code alone:

```bash
test -s runs/wangjiaba/FinalParam.nml
find runs/wangjiaba -maxdepth 2 -type f | rg "FinalParam|dds|sce|Opti|Param"
rg -n "opti_function|nIterations" runs/wangjiaba/mhm.nml
```

Then regenerate s6 forward namelists over the calibration plus validation period with `--param_nml runs/wangjiaba/FinalParam.nml` and score both periods separately in s8.

## Traps

- `dt_r14` in `../diagnostics/triplets.yaml`: DDS with `nIterations < 6` can stop with status 0 and no `FinalParam.nml`.
- `dt_r15`: `opti_function=10` is soil-moisture KGE in mHM v5.13.1, not discharge KGE; use `1` or `9` for discharge.
- `dt_r16`: wrapper invocations must not rewrite `mhm.nml` with default optimizer flags during `--execute` or `--parse_results`.
- `dt_s04`: multi-basin calibration can bias toward the largest basin if the objective is not normalized.

## Example

For Wangjiaba, calibrate on 1981-1985 with 1980 as spin-up using DDS:

```bash
python tools/s9_calibration/setup_mhm_calibration.py \
  --run_dir runs/wangjiaba \
  --opti_method 1 \
  --opti_function 1 \
  --n_iterations 2000 \
  --basin_type humid_subtropical
```
