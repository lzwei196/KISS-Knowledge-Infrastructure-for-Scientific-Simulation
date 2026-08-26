# s5 Calibration

## Purpose

Calibrate the seasonal temperature and dissolved-oxygen models against observations using `tools/run_wasp.py --mode calibrate`. This stage uses Nelder-Mead optimization to estimate the three seasonal temperature parameters and four seasonal DO parameters, then reports calibration and validation metrics.

## Inputs

- `tools/run_wasp.py`
- Forcing JSON from `tools/convert_forcing_to_wasp.py` with temperature and dissolved oxygen records
- Parameter JSON from `tools/convert_parameters_to_wasp.py`
- `--cal-split`, a fraction between 0 and 1
- `docs/validation_convention.yaml` for how to interpret reported metrics

Calibration is meaningful only when the forcing contains enough accepted temperature and DO observations. The implementation fits temperature first; DO calibration depends on the calibrated seasonal temperature parameters.

## Outputs

- A calibration JSON with `status`, `model`, `mode: calibrate`, `output`, and `log`
- `output.calibrated_params.seasonal`: `T_mean`, `amplitude`, `phase`
- `output.calibrated_params.kinetics`: `kd`, `ka`, `BOD0`, `DO_offset`
- `output.temperature.calibration_metrics` and `output.temperature.validation_metrics`
- `output.dissolved_oxygen.calibration_metrics` and `output.dissolved_oxygen.validation_metrics`
- `output.cal_split`

## Procedure

Run from the KI root after stages 1 and 2:

```bash
python tools/run_wasp.py \
  --mode calibrate \
  --forcing /tmp/wasp_forcing.json \
  --params /tmp/wasp_params.json \
  --cal-split 0.6 \
  --output /tmp/wasp_calibrated.json
```

Parse the calibrated output with the stage 4 parser:

```bash
python tools/parse_output_wasp.py \
  --input /tmp/wasp_calibrated.json \
  --metrics-json /tmp/wasp_calibrated_metrics.json
```

Do not edit `diagnostics/triplets.yaml` to force a calibration to pass. Use triplets only to diagnose actual symptoms and then rerun the tool.

## Verification

- The calibration command exits 0 and writes a JSON file with `mode: calibrate`.
- The log reports total, calibration, and validation counts for temperature and DO when enough records exist.
- Temperature calibration should report calibrated `T_mean`, `amplitude`, and `phase`.
- DO calibration should report calibrated `kd`, `ka`, `BOD0`, and `DO_offset`.
- Check that calibrated kinetic values remain physically plausible before using them in production simulation.

## Traps

- `dt_wasp_009`: the seasonal phase can converge to the wrong hemisphere if initialized poorly.
- `dt_wasp_010`: `ka` close to `kd` hits the Streeter-Phelps degenerate region.
- `dt_wasp_011`: high BOD0 can force unrealistic `ka`.
- `dt_wasp_016`: Nelder-Mead can fail to converge when parameter scales dominate the simplex.
- `dt_wasp_018`: rejected or preliminary WQP records reduce calibration skill.
- `dt_wasp_020`: incorrect DOY alignment can make a visually reasonable seasonal model score poorly.
- `dt_wasp_024`: NaN or infinite objectives indicate invalid parameter combinations.

## Example

```bash
python tools/convert_parameters_to_wasp.py --lake-preset erie --output /tmp/erie_params.json
python tools/run_wasp.py \
  --mode calibrate \
  --forcing /tmp/erie_forcing.json \
  --params /tmp/erie_params.json \
  --cal-split 0.7 \
  --output /tmp/erie_calibrated.json
```

