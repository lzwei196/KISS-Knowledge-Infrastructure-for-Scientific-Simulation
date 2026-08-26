# s8_postprocess Skill

## Purpose

Extract and evaluate mHM outputs, especially routed discharge, actual ET, soil moisture, and cross-model discharge comparisons.

## Inputs

- mHM output directory from s7.
- Optional observed discharge file.
- Optional VIC discharge file for cross-model comparison.
- Warmup days to skip in metrics.

## Outputs

- Parsed discharge, ET, and soil-moisture summaries from `tools/s8_postprocess/parse_mhm_output.py`.
- Comparison metrics from `tools/s8_postprocess/compare_mhm_vic.py`.
- Performance quantities aligned with `docs/validation_convention.yaml`, including NSE, KGE, correlation, and PBIAS for streamflow.

## Procedure

Parse an mHM run:

```bash
python tools/s8_postprocess/parse_mhm_output.py \
  --output_dir runs/wangjiaba/output_b1 \
  --obs_file runs/wangjiaba/input/gauge/51030.txt \
  --warmup_days 365
```

Compare against VIC discharge if a matching VIC series exists:

```bash
python tools/s8_postprocess/compare_mhm_vic.py \
  --mhm_output runs/wangjiaba/output_b1/daily_discharge.out \
  --vic_discharge runs/vic/wangjiaba/discharge.txt \
  --obs_file runs/wangjiaba/input/gauge/51030.txt \
  --warmup_days 365
```

Use `docs/validation_convention.yaml` for pass-band interpretation and `docs/format_spec.yaml` for output units and observability.

## Verification

Check that discharge is nonzero and that metrics are computed after warmup:

```bash
test -d runs/wangjiaba/output_b1
find runs/wangjiaba/output_b1 -type f | rg "Fluxes_States|daily_discharge"
python tools/s8_postprocess/parse_mhm_output.py \
  --output_dir runs/wangjiaba/output_b1 \
  --obs_file runs/wangjiaba/input/gauge/51030.txt \
  --warmup_days 365
```

## Traps

- `dt_v001` in `../diagnostics/triplets.yaml`: all-zero `daily_discharge.out` with nonzero `mHM_Fluxes_States.nc` total runoff points to the geographic coordinate flag.
- `dt_v002`: nonzero `mRM_Fluxes_States.nc` routed flow with zero gauge discharge points to gauge/L11 placement.
- `dt_s13`: nonsensical Qobs metrics can come from a malformed gauge file, not from model skill.
- `dt_s09`, `dt_s10`, and `dt_s11`: stable large PBIAS after a technically successful run often traces to basin area, precipitation units, or PET setup.

## Example

For the Wangjiaba reference run in `SKILL.md`, report calibration and validation periods separately rather than one full-period score, because s9 optimizes only the configured `eval_Per`.
