# s6 Namelist

## Purpose

Assemble `glm3.nml`, the Fortran namelist consumed by the GLM v3.3.3 binary. This stage combines morphometry, initial profiles, meteorology, inflow, outflow, and calibrated physical parameters into GLM setup blocks.

## Inputs

- `morphometry.json` from s1.
- `bcs/met.csv` or `bcs/met_hourly.csv` from s2.
- Optional `bcs/inflow_1.csv` from s3.
- Optional `outflow_config.json` and `bcs/outflow.csv` from s4.
- Optional `init_profiles.json` from s5.
- Tool: `tools/s6_namelist/generate_glm_nml.py`.

## Outputs

- `glm3.nml`.
- Stdout JSON summary with output file and warnings.

## Procedure

1. Generate a thermodynamic-only namelist:

```bash
python tools/s6_namelist/generate_glm_nml.py \
  --morphometry morphometry.json \
  --init_profiles init_profiles.json \
  --met_csv bcs/met.csv \
  --start_date 2000-01-01 \
  --end_date 2010-12-31 \
  --timezone 0 \
  --output glm3.nml
```

2. Include inflow and managed outflow:

```bash
python tools/s6_namelist/generate_glm_nml.py \
  --morphometry morphometry.json \
  --init_profiles init_profiles.json \
  --met_csv bcs/met.csv \
  --inflow_csv bcs/inflow_1.csv \
  --outflow_config outflow_config.json \
  --start_date 2000-01-01 \
  --end_date 2010-12-31 \
  --timezone 8 \
  --lw_type LW_IN \
  --nsave 24 \
  --output glm3.nml
```

3. Tune core thermal parameters only with evidence from observations:

```bash
python tools/s6_namelist/generate_glm_nml.py \
  --morphometry morphometry.json \
  --init_profiles init_profiles.json \
  --met_csv bcs/met.csv \
  --inflow_csv bcs/inflow_1.csv \
  --start_date 2000-01-01 --end_date 2010-12-31 \
  --kw 0.5 --coef_wind_stir 0.3 --wind_factor 0.8 \
  --max_layer_thick 0.5 \
  --output glm3.nml
```

## Verification

- Strings in `glm3.nml` use single quotes.
- `bsn_vals` equals the length of `H` and `A`.
- `timefmt` matches date strings (`YYYY-MM-DD HH:MM:SS`) or integer seconds.
- `meteo_fl`, `inflow_fl`, and outflow file paths are resolvable from the run directory used by s8.
- `&snowice` includes `dt_iceon_avg` and `min_ice_thickness`.
- If AED2 is used, manually inspect `&wq_setup`, `&inflow`, and `&init_profiles`; `generate_glm_nml.py` does not fully wire AED2 water quality.

## Traps

- `dt_005`: double-quoted strings cause Fortran namelist parse errors.
- `dt_008`: `bsn_vals` length mismatch crashes startup.
- `dt_010`: `num_inflows=0` with inflow files silently ignores inflow.
- `dt_019`: excessive `Kw` can suppress stratification.
- `dt_021`: `coef_wind_stir` or `wind_factor` too high can overmix sheltered lakes.
- `dt_025`: `timefmt` must match the `start` and `stop` format.
- `dt_027`: missing `dt_iceon_avg` and `min_ice_thickness` silently disables ice.
- `dt_030` and `dt_033`: AED2 WQ namelist wiring is manual and must match variable counts and output strategy.

## Example

```bash
python tools/s6_namelist/generate_glm_nml.py \
  --morphometry morphometry.json \
  --init_profiles init_profiles.json \
  --met_csv bcs/met.csv \
  --inflow_csv bcs/inflow_1.csv \
  --outflow_config outflow_config.json \
  --start_date 2014-01-01 --end_date 2020-12-31 \
  --timezone 0 --lw_type LW_IN --nsave 24 \
  --output glm3.nml
```
