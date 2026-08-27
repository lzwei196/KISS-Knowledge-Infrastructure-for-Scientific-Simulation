# s2 Parameter Setup

## Purpose

Build the parameter JSON consumed by `tools/run_wasp.py`. This stage uses `tools/convert_parameters_to_wasp.py` to assemble lake morphometry, Streeter-Phelps kinetic parameters, seasonal temperature parameters, thermal-profile parameters, and hypolimnetic depletion settings.

## Inputs

- `tools/convert_parameters_to_wasp.py`
- One built-in preset: `erie`, `degray`, `jordan`, or `mead`
- Or a CSV passed with `--from-csv`
- Or manual CLI values such as `--z-max-m`, `--area-km2`, `--kd`, `--ka`, `--bod0`, `--t-mean`, `--amplitude`, and `--phase`
- Unit flags: `--depth-unit m|ft`, `--area-unit km2|ha|m2`, `--volume-unit m3|acre-ft`, and `--rate-unit 1/d|1/h`

## Outputs

- A parameter JSON with `status`, `model`, `parameters`, `bounds`, `param_details`, and `log`
- `parameters.morphometry`: `z_max_m`, `z_mean_m`, `area_km2`, `volume_m3`
- `parameters.kinetics`: `kd`, `ka`, `BOD0`, `DO_offset`, `SOD`
- `parameters.thermal`: `T_surface`, `T_bottom`, `thermo_depth`, `thermo_width`
- `parameters.seasonal`: `T_mean`, `amplitude`, `phase`
- `parameters.hypo_depletion_rate` and `parameters.latitude`

## Procedure

Run from the KI root:

```bash
python preflight_check.py
python tools/convert_parameters_to_wasp.py --lake-preset erie --output /tmp/wasp_params.json
```

For manual setup:

```bash
python tools/convert_parameters_to_wasp.py \
  --z-max-m 25.6 \
  --z-mean-m 18.3 \
  --area-km2 25745 \
  --volume-m3 4.84e11 \
  --kd 0.10 \
  --ka 0.51 \
  --bod0 3.0 \
  --t-mean 9.53 \
  --amplitude 11.63 \
  --phase 129.5 \
  --output /tmp/wasp_params.json
```

Use `docs/format_spec.yaml` and `dag.yaml` to confirm parameter names and units before wiring this file into `tools/run_wasp.py`.

## Verification

- The command exits 0 and writes a JSON file.
- `status` is `success` or `warning`; warnings should be inspected before execution.
- `parameters.morphometry.z_mean_m` is not greater than `z_max_m`.
- `parameters.thermal.thermo_depth` is not deeper than `z_max_m` unless the lake is intentionally treated as unstratified.
- `parameters.kinetics.kd` and `parameters.kinetics.ka` are in 1/d, not 1/h.

## Traps

- `dt_wasp_006`: hectares supplied as km2 inflate area by 100x.
- `dt_wasp_009`: phase values outside the hemisphere's seasonal cycle can invert the annual temperature curve.
- `dt_wasp_010`: `ka` too close to `kd` creates a Streeter-Phelps singularity region.
- `dt_wasp_011`: excessive BOD0 drives unrealistic reaeration rates.
- `dt_wasp_014` and `dt_wasp_015`: thermocline width/depth can erase the modeled thermocline.
- `dt_wasp_019`: hypolimnetic depletion must match trophic state.
- `dt_wasp_022`: `kd` and `ka` from hourly literature must be converted to 1/d.

## Example

```bash
python tools/convert_parameters_to_wasp.py \
  --lake-preset degray \
  --kd 0.08 \
  --ka 0.35 \
  --output /tmp/degray_params.json
```

