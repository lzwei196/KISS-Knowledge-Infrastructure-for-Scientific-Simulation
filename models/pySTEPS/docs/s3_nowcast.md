# s3_nowcast

## Purpose

Run the pySTEPS nowcast using imported rainfall fields and an estimated motion field. This stage is implemented by `tools/s3_nowcast/run_nowcast.py`, the KI manifest entry point, and supports deterministic extrapolation, STEPS ensemble nowcasting, and ANVIL.

## Inputs

- `--input_dir`: s1 output containing `radar_frames.npz` and `metadata.json`.
- `--motion_dir`: s2 output containing `motion_field.npz`.
- `--method`: `extrapolation`, `steps`, or `anvil`.
- `--n_leadtimes`: number of forecast frames.
- STEPS options: `--n_ens_members`, `--n_cascade_levels`, `--noise_method`, and optional `--seed`.

## Outputs

- `nowcast.npz` with `forecast` shaped `(n_leadtimes, ny, nx)` for deterministic methods or `(n_ens, n_leadtimes, ny, nx)` for STEPS.
- `nowcast_summary.json` with method, horizon, grid shape, forecast shape, unit, elapsed time, and memory estimate.
- `exceedance_prob.npz` for STEPS ensemble output, with probability maps for fixed mm/h thresholds.

## Procedure

Run the KI preflight and inspect the nowcast CLI:

```bash
cd KISSPATH_KI_ROOT/pySTEPS/knowledge_infrastructure
python3 preflight_check.py
python3 tools/s3_nowcast/run_nowcast.py --help
```

Run a deterministic extrapolation nowcast:

```bash
python3 tools/s3_nowcast/run_nowcast.py \
  --input_dir /tmp/pysteps_case/s1_data_import \
  --motion_dir /tmp/pysteps_case/s2_motion_estimation \
  --method extrapolation \
  --n_leadtimes 5 \
  --output_dir /tmp/pysteps_case/s3_nowcast
```

Run the STEPS ensemble path:

```bash
python3 tools/s3_nowcast/run_nowcast.py \
  --input_dir /tmp/pysteps_case/s1_data_import \
  --motion_dir /tmp/pysteps_case/s2_motion_estimation \
  --method steps \
  --n_leadtimes 12 \
  --n_ens_members 24 \
  --n_cascade_levels 6 \
  --noise_method nonparametric \
  --seed 42 \
  --output_dir /tmp/pysteps_case/s3_nowcast
```

The tool thresholds low rainfall, transforms STEPS inputs to dBR internally, runs real `pysteps.nowcasts.get_method(...)`, then converts output back to mm/h.

## Verification

Confirm unit, shape, and finite values:

```bash
python3 - <<'PY'
import json, numpy as np
from pathlib import Path
d = Path('/tmp/pysteps_case/s3_nowcast')
F = np.load(d / 'nowcast.npz')['forecast']
summary = json.loads((d / 'nowcast_summary.json').read_text())
print(F.shape, summary['unit'], summary['forecast_horizon_min'])
assert summary['unit'] == 'mm/h'
assert F.shape == tuple(summary['forecast_shape'])
assert np.isfinite(F).all()
assert np.nanmin(F) >= 0.0
PY
```

The offline end-to-end diagnostic uses this KI's supported nowcast family through `diagnostics/run_synthetic_advection.py` and writes `tester_result.json`.

## Traps

- `dt_pysteps_008`: nearly identical STEPS members mean ensemble spread is ineffective. Use at least 20 members and an active `--noise_method`.
- `dt_pysteps_010` and `dt_pysteps_017`: memory scales with ensemble members, cascade levels, and grid size. The tool logs an estimated peak memory before running.
- `dt_pysteps_011`: exceedance probabilities are unstable with too few members or thresholds in the wrong unit. This stage writes mm/h forecasts and mm/h exceedance thresholds.
- `dt_pysteps_012`: features can advect out of a cropped domain. Use enough spatial buffer before importing and mask boundary buffers during verification.
- `dt_pysteps_013`: semi-Lagrangian artifacts or negative values can occur. This tool clips negative forecast values to zero before writing output.

## Example

```bash
cd KISSPATH_KI_ROOT/pySTEPS/knowledge_infrastructure
python3 diagnostics/run_synthetic_advection.py
```

This example runs the KI's offline synthetic case: 4 past Gaussian mm/h frames, Proesmans motion, extrapolation nowcast for 5 lead times, and verification against held-out truth.
