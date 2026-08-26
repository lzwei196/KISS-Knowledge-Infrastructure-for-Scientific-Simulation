# s3_mpr Skill

## Purpose

Create `mhm_parameter.nml`, the global MPR transfer-function parameter file. These are process parameters, not per-cell calibrated maps, and later s9/s10 stages modify or transfer them.

## Inputs

- `config.json` from s0.
- Climate preset, one of the presets accepted by `tools/s3_mpr/generate_mhm_parameters.py`; `SKILL.md` documents `humid_subtropical`, `semi_arid`, `cold_alpine`, and `tropical`.
- Completed s2 physiographic inputs for meaningful MPR evaluation at model startup.

## Outputs

- `<run_dir>/mhm_parameter.nml`.

## Procedure

Generate climate-zone-aware default MPR parameters:

```bash
python tools/s3_mpr/generate_mhm_parameters.py \
  --config runs/wangjiaba/config.json \
  --climate_zone humid_subtropical
```

Keep this file as the baseline defaults. Calibration in s9 writes the optimized parameter file; transfer in s10 copies calibrated values into a target basin's `mhm_parameter.nml`.

## Verification

Check that the file exists and that parameter rows keep the mHM lower, upper, value, FLAG, SCALING structure:

```bash
test -s runs/wangjiaba/mhm_parameter.nml
rg -n "^[[:space:]]*[0-9.+-]" runs/wangjiaba/mhm_parameter.nml | head
```

Before running mHM, scan for obvious out-of-bound edits if the file was manually changed:

```bash
python - <<'PY'
from pathlib import Path
for n,line in enumerate(Path("runs/wangjiaba/mhm_parameter.nml").read_text().splitlines(),1):
    parts=line.replace(",", " ").split()
    if len(parts) >= 3:
        try:
            lo,hi,val=map(float, parts[:3])
        except ValueError:
            continue
        assert lo <= val <= hi, (n, lo, hi, val)
print("parameter bounds OK")
PY
```

## Traps

- `dt_r08` in `../diagnostics/triplets.yaml`: mHM aborts when a parameter value is outside its lower/upper bounds.
- `dt_s06`: low interflow storage capacity can silently zero interflow.
- `dt_s03`: MPR transfer only remains valid when source and target basins use the same L0 soil, geology, and land-cover data sources.

## Example

For the humid subtropical Wangjiaba reference setup in `SKILL.md`, use:

```bash
python tools/s3_mpr/generate_mhm_parameters.py \
  --config runs/wangjiaba/config.json \
  --climate_zone humid_subtropical
```
