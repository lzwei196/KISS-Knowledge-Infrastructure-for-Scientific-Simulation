# s9 Output Analysis

## Purpose

Parse GLM thermal, lake-integrated, and AED2 outputs into summaries, fixed-depth time series, plots, and calibration diagnostics. This stage converts GLM's adaptive Lagrangian layers into observation-comparable products.

## Inputs

- `output/output.nc` and `output/lake.csv` from s8.
- Optional AED2 output variables in `output.nc`.
- Optional observation CSVs for temperature, dissolved oxygen, chlorophyll, or nutrients.
- Tools:
  - `tools/s9_output_analysis/parse_glm_output.py`
  - `tools/s9_output_analysis/parse_aed_output.py`
  - `tools/s9_output_analysis/plot_glm_results.py`
  - `tools/s9_output_analysis/calibrate_glm.py`
  - `tools/s9_output_analysis/load_ntl_lter_obs.py`
  - `tools/s9_output_analysis/load_ismn_obs.py`

## Outputs

- JSON thermal summary, for example `results.json`.
- Optional time-series CSV, fixed-depth temperature CSV, WQ summary JSON, WQ time series, and plots.
- Calibration result JSON when `calibrate_glm.py` is used.

## Procedure

1. Parse core GLM outputs:

```bash
python tools/s9_output_analysis/parse_glm_output.py \
  --output_nc output/output.nc \
  --lake_csv output/lake.csv \
  --summary results.json \
  --timeseries lake_timeseries.csv
```

2. Interpolate adaptive GLM layers to fixed depths before comparing to thermistors or profiles:

```bash
python tools/s9_output_analysis/parse_glm_output.py \
  --output_nc output/output.nc \
  --lake_csv output/lake.csv \
  --depths "0.5,1,5,10" \
  --depth_timeseries temp_fixed_depths.csv \
  --summary results.json
```

3. Parse AED2 output when enabled:

```bash
python tools/s9_output_analysis/parse_aed_output.py \
  --output_nc output/output.nc \
  --lake_csv output/lake.csv \
  --summary wq_summary.json \
  --timeseries wq_timeseries.csv
```

4. Plot GLM results:

```bash
python tools/s9_output_analysis/plot_glm_results.py \
  --output_nc output/output.nc \
  --lake_csv output/lake.csv \
  --output glm_results.png \
  --title "GLM Simulation"
```

5. Load supported observation sources instead of hand-rolled readers:

```bash
python tools/s9_output_analysis/load_ntl_lter_obs.py \
  --lakeid SP --variable wtemp --start 2000-01-01 --end 2010-12-31 \
  --output ntl_obs.csv --meta_out ntl_meta.json
python tools/s9_output_analysis/load_ismn_obs.py \
  --lat 46.0 --lon -89.7 --radius_km 50 --list
```

## Verification

- Temperature validation against fixed-depth observations uses `--depths` and `--depth_timeseries`; do not compare `temp[:, k]` directly.
- Summary metrics follow `docs/validation_convention.yaml` and `dag.yaml` observability.
- Thermal analysis uses daily or finer `nsave`; sparse output can create visual artifacts.
- AED2 WQ output is finite before calculating nutrient, oxygen, or chlorophyll metrics.

## Traps

- `dt_018`: large `nsave` misses layer dynamics and creates stripy heatmaps.
- `dt_033`: older AED2 parser behavior missed 4-D `(time,z,lat,lon)` WQ variables; verify non-empty WQ timeseries.
- `dt_034`: depth-resolved WQ needs one-timestep-at-a-time NetCDF reads; bulk padded reads can segfault.
- `dt_035`: depthless dissolved oxygen observations should be scored as surface DO, not invented column means.
- `dt_036`: GLM layer index is not fixed depth; interpolate to depth below surface.
- `dt_037`: use `load_ismn_obs.py` for ISMN read-only WAL, depth, QC, and sensor aggregation handling.

## Example

```bash
python tools/s9_output_analysis/parse_glm_output.py \
  --output_nc output/output.nc \
  --lake_csv output/lake.csv \
  --depths "0.5,5,10" \
  --depth_timeseries temp_depths.csv \
  --summary results.json
python tools/s9_output_analysis/plot_glm_results.py \
  --output_nc output/output.nc \
  --lake_csv output/lake.csv \
  --output glm_results.png
```
