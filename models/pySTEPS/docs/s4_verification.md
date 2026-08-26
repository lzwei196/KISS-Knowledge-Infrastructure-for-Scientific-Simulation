# s4_verification

## Purpose

Score a pySTEPS forecast against observed future radar frames. This stage is implemented by `tools/s4_verification/verify_nowcast.py` and computes deterministic grid scores from either a deterministic nowcast or the ensemble mean of a STEPS forecast.

## Inputs

- `--nowcast_dir`: s3 output containing `nowcast.npz`.
- `--obs_dir`: observed future frames in the same `radar_frames.npz` format as s1.
- `--thresholds`: comma-separated rainfall thresholds in mm/h for categorical scores.
- `--fss_scales`: comma-separated spatial scales in pixels for Fractions Skill Score.

## Outputs

- `verification_scores.json` with per-leadtime RMSE, MAE, NSE, Pearson `r`, categorical CSI/POD/FAR/HSS by threshold, and FSS by scale.
- `verification_summary.json` with mean scores and best/worst lead time by NSE.

## Procedure

Inspect the stage CLI:

```bash
cd KISSPATH_KI_ROOT/pySTEPS/knowledge_infrastructure
python3 tools/s4_verification/verify_nowcast.py --help
```

Run verification against held-out observed frames:

```bash
python3 tools/s4_verification/verify_nowcast.py \
  --nowcast_dir /tmp/pysteps_case/s3_nowcast \
  --obs_dir /tmp/pysteps_case/observed_future \
  --thresholds 0.1,1.0,5.0 \
  --fss_scales 1,5,10,20 \
  --output_dir /tmp/pysteps_case/s4_verification
```

If `nowcast.npz` contains a STEPS ensemble shaped `(n_ens, n_leadtimes, ny, nx)`, the tool computes deterministic scores on the ensemble mean.

## Verification

Check that the score file has at least one lead time and mean scores:

```bash
python3 - <<'PY'
import json
from pathlib import Path
d = Path('/tmp/pysteps_case/s4_verification')
scores = json.loads((d / 'verification_scores.json').read_text())
summary = json.loads((d / 'verification_summary.json').read_text())
print(scores['parameters']['n_leadtimes_verified'], summary.get('mean_CSI'), summary.get('mean_FSS'))
assert scores['per_leadtime']
assert 'mean_scores' in scores
PY
```

For a fully offline analytical check, run `python3 diagnostics/run_synthetic_advection.py`; it uses `pysteps.verification.det_cat_fct` and `pysteps.verification.fss` directly and writes `diagnostics/last_run.json`.

## Traps

- `dt_pysteps_003`: pySTEPS forecasts are rates in mm/h. Do not compare rate frames to accumulated rainfall depths without multiplying by `metadata['accutime'] / 60`.
- `dt_pysteps_011`: probability thresholds must be in the same unit as nowcast output; this tool expects mm/h thresholds.
- `dt_pysteps_015`: NaN scores or metric errors usually mean all-zero arrays, shape mismatch, wrong threshold units, or FSS scales larger than the domain.
- `dt_pysteps_012`: boundary losses from advection can degrade scores. Mask spatial buffers if the import domain was cropped tightly.

## Example

```bash
cd KISSPATH_KI_ROOT/pySTEPS/knowledge_infrastructure
python3 diagnostics/run_synthetic_advection.py
python3 - <<'PY'
import json
from pathlib import Path
p = Path('diagnostics/last_run.json')
run = json.loads(p.read_text())
print(run['mean_CSI'], run['mean_FSS'])
PY
```

Expected KI diagnostic behavior from `SKILL.md`: mean CSI above 0.95 and mean FSS above 0.99 for the synthetic translating Gaussian case.
