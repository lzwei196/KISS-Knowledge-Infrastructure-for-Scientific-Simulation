# s2_motion_estimation

## Purpose

Estimate the precipitation advection field from consecutive imported radar frames. This stage is implemented by `tools/s2_motion_estimation/estimate_motion.py` and calls real `pysteps.motion` methods, with Lucas-Kanade (`LK`) as the default and `proesmans`, `VET`, or `DARTS` available through the CLI.

## Inputs

- `--input_dir`: output from `docs/s1_data_import.md`, containing `radar_frames.npz` and `metadata.json`.
- `--method`: `LK`, `VET`, `proesmans`, or `DARTS`.
- Lucas-Kanade controls: `--max_corners`, `--quality_level`, and `--win_size`.
- Imported precipitation fields must be linear rainfall rate in mm/h, not dBZ.

## Outputs

- `motion_field.npz` containing `V` shaped `(2, ny, nx)` in pixels per frame.
- `motion_summary.json` with method, input shape, mean and maximum speed in pixels per frame and km/h.

## Procedure

Inspect the stage CLI:

```bash
cd KISSPATH_KI_ROOT/pySTEPS/knowledge_infrastructure
python3 tools/s2_motion_estimation/estimate_motion.py --help
```

Run Lucas-Kanade on imported frames:

```bash
python3 tools/s2_motion_estimation/estimate_motion.py \
  --input_dir /tmp/pysteps_case/s1_data_import \
  --method LK \
  --max_corners 500 \
  --quality_level 0.1 \
  --win_size 50 \
  --output_dir /tmp/pysteps_case/s2_motion_estimation
```

Use `--method proesmans` for a uniform-translation case like the KI's synthetic diagnostic in `diagnostics/run_synthetic_advection.py`.

## Verification

Confirm the vector field shape matches the imported grid:

```bash
python3 - <<'PY'
import json, numpy as np
from pathlib import Path
s1 = Path('/tmp/pysteps_case/s1_data_import')
s2 = Path('/tmp/pysteps_case/s2_motion_estimation')
R = np.load(s1 / 'radar_frames.npz')['data']
V = np.load(s2 / 'motion_field.npz')['V']
summary = json.loads((s2 / 'motion_summary.json').read_text())
print(V.shape, summary['mean_speed_px_per_frame'], summary['max_speed_px_per_frame'])
assert V.shape == (2, R.shape[1], R.shape[2])
assert np.isfinite(V).all()
PY
```

For the KI's offline diagnostic, `diagnostics/run_synthetic_advection.py` verifies the compiled Proesmans path and records timing in `diagnostics/last_run.json`.

## Traps

- `dt_pysteps_001`: dBZ input can produce chaotic vectors; this tool explicitly rejects `metadata['unit'] == 'dBZ'`.
- `dt_pysteps_007`: all-zero or wrong motion fields usually mean LK feature parameters are not suited to the precipitation coverage. Adjust `--max_corners`, `--quality_level`, or `--win_size`, or try `--method proesmans`.
- `dt_pysteps_016`: missing compiled pySTEPS extensions affect Proesmans and VET. Run `python3 preflight_check.py` before relying on compiled motion paths.
- `dt_pysteps_018`: pySTEPS high-level archive discovery can fail if `pystepsrc` is missing; this stage consumes the explicit files produced by s1 and avoids archive discovery.

## Example

```bash
cd KISSPATH_KI_ROOT/pySTEPS/knowledge_infrastructure
python3 tools/s2_motion_estimation/estimate_motion.py \
  --input_dir /tmp/pysteps_case/s1_data_import \
  --method proesmans \
  --output_dir /tmp/pysteps_case/s2_motion_estimation
```

Expected next-stage input: `/tmp/pysteps_case/s2_motion_estimation/motion_field.npz`.
