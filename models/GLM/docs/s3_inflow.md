# s3 Inflow

## Purpose

Create GLM inflow boundary CSV files from CaMa-Flood, VIC routing, or a constant discharge. GLM uses inflow flow, temperature, and salinity to add water and insert it at the density-neutral depth.

## Inputs

- Simulation dates from s0.
- Meteorology CSV from s2 for air-temperature-based inflow temperature estimation.
- One discharge source: `--cama_outflow`, `--vic_routing_file`, or `--constant_flow`.
- Tool: `tools/s3_inflow/convert_inflow_to_glm.py`.

## Outputs

- Inflow CSV, usually `bcs/inflow_1.csv`, with `time,FLOW,TEMP,SALT`.
- Stderr JSON summary with mean/max flow, mean temperature, and warnings.

## Procedure

1. Convert CaMa-Flood output at the lake inlet cell:

```bash
python tools/s3_inflow/convert_inflow_to_glm.py \
  --cama_outflow model/cmf_v420_pkg/out/run1/outflw_YYYY.nc \
  --cell_idx 42 \
  --met_csv bcs/met.csv \
  --salinity 0.0 \
  --start_date 2000-01-01 --end_date 2010-12-31 \
  --output bcs/inflow_1.csv
```

2. Or convert VIC routing output:

```bash
python tools/s3_inflow/convert_inflow_to_glm.py \
  --vic_routing_file routing_output.day \
  --met_csv bcs/met.csv \
  --salinity 0.0 \
  --start_date 2000-01-01 --end_date 2010-12-31 \
  --output bcs/inflow_1.csv
```

3. For an uncoupled first run, use constant discharge from HydroLAKES `dis_avg` or other hydrologic data:

```bash
python tools/s3_inflow/convert_inflow_to_glm.py \
  --constant_flow 5.0 \
  --met_csv bcs/met.csv \
  --salinity 0.0 \
  --start_date 2000-01-01 --end_date 2010-12-31 \
  --output bcs/inflow_1.csv
```

## Verification

- `FLOW` is nonnegative and has the expected order of magnitude.
- `TEMP` exists and varies seasonally unless a measured constant temperature is intentionally supplied.
- `SALT` is `0.0` for freshwater lakes.
- Inflow timestamps use the same convention as the met CSV and s6 `timezone`.

## Traps

- `dt_004`: missing or all-zero inflow `TEMP` creates an artificial cold density current.
- `dt_016`: timezone mismatch shifts inflow timing relative to meteorology.
- `dt_017`: wrong CaMa inlet cell prevents water balance closure.
- `dt_022`: non-zero salinity in a freshwater lake inserts inflow too deep and silently distorts stratification.

## Example

```bash
python tools/s3_inflow/convert_inflow_to_glm.py \
  --constant_flow 12.0 \
  --met_csv bcs/met.csv \
  --temp_coeff_a 0.9 --temp_coeff_b 1.5 \
  --salinity 0.0 \
  --start_date 2014-01-01 --end_date 2020-12-31 \
  --output bcs/inflow_1.csv
```
