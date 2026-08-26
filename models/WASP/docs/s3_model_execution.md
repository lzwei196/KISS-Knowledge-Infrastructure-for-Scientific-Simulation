# s3 Model Execution

## Purpose

Run the real WASP analytic reimplementation in `tools/run_wasp.py`. The tool implements the KI's seasonal temperature model, Benson-Krause DO saturation, Streeter-Phelps BOD-DO coupling, logistic thermocline profile, 1-D DO profile, and Carlson TSI support. It has three modes: `simulate`, `calibrate`, and `profile`.

## Inputs

- `tools/run_wasp.py`
- Parameter JSON from `docs/s2_parameter_setup.md`
- For `simulate`: forcing JSON from `docs/s1_forcing_preparation.md`
- For `calibrate`: forcing JSON with enough temperature and DO observations
- For `profile`: parameter JSON only, plus optional `--z-max` and `--z-step`

## Outputs

- A model output JSON with `status`, `model`, `mode`, `output`, and `log`
- `simulate` can emit `seasonal_temp`, `seasonal_do`, `profiles`, `tsi`, and `streeter_phelps`
- `profile` emits `depths_m`, `T_profile_c`, `DO_profile_mg_l`, `DOsat_profile_mg_l`, `stats`, and profile settings
- `calibrate` emits `calibrated_params`, calibration metrics, validation metrics, and `cal_split`

## Procedure

Run from the KI root after stages 1 and 2:

```bash
python tools/run_wasp.py \
  --mode simulate \
  --forcing /tmp/wasp_forcing.json \
  --params /tmp/wasp_params.json \
  --output /tmp/wasp_simulation.json
```

For a profile-only execution path using only a parameter file:

```bash
python tools/convert_parameters_to_wasp.py --lake-preset erie --output /tmp/wasp_params.json
python tools/run_wasp.py \
  --mode profile \
  --params /tmp/wasp_params.json \
  --z-max 25 \
  --z-step 1 \
  --output /tmp/wasp_profiles.json
```

Do not replace this stage with a hand-coded approximation. `SKILL.md` requires running the actual model tool.

## Verification

- The command exits 0 and writes the requested JSON file.
- `status` is `success`.
- For seasonal runs, inspect `output.seasonal_temp.metrics` and `output.seasonal_do.metrics` when observations are present.
- For profile runs, `output.stats.DO_min_mg_l` should be nonnegative and `output.stats.T_range_c` should match the intended stratification.
- The log should include the mode-specific summary, such as `WASP Simulation`, `WASP Calibration`, or `WASP Profile Generation`.

## Traps

- `dt_wasp_012`: negative DO should not appear after model clipping.
- `dt_wasp_013`: the seasonal DO mode is a steady-state Streeter-Phelps approximation and can violate transient mass-balance expectations.
- `dt_wasp_016`: unscaled Nelder-Mead calibration can return initial parameters unchanged.
- `dt_wasp_021`: fixed thermocline profiles are summer-stratification profiles, not spring/fall turnover profiles.
- `dt_wasp_024`: invalid parameter combinations can make the calibration objective NaN or infinite.

## Example

```bash
python tools/convert_parameters_to_wasp.py --lake-preset mead --output /tmp/mead_params.json
python tools/run_wasp.py --mode profile --params /tmp/mead_params.json --z-step 2 --output /tmp/mead_profile.json
```

