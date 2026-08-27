# S5-S6: Model Parameters and Execution Skill

## Purpose

Select the parameter set and run this KI's Python HEC-HMS equivalent engine.
`tools/run_hec_hms.py` implements SCS Curve Number loss, SCS Unit Hydrograph
transform, Linear Reservoir baseflow, and the Muskingum routing function used
inside the executable method set.

## Inputs

| Input | Format | Required by |
|-------|--------|-------------|
| Converted forcing | CSV with `precip_mm` | `--forcing_csv` |
| Soil parameters | JSON from `convert_soil_to_hms.py` | `--soil_params` |
| Basin area | km2 | `--basin_area_km2` |
| Simulation dates | `YYYY-MM-DD` | `--start_date`, `--end_date` |
| Optional overrides | numeric | `--cn`, `--ia_ratio`, `--tp_hr`, `--k_recession`, `--q_base_init`, `--recharge_fraction` |

## Outputs

| Output | Format | Produced by |
|--------|--------|-------------|
| Simulation CSV | CSV | `--output_csv` |
| `runoff_mm` | mm | SCS-CN loss stage |
| `loss_mm` | mm | SCS-CN loss stage |
| `q_direct_m3s` | m3/s | SCS Unit Hydrograph |
| `q_base_m3s` | m3/s | Linear Reservoir |
| `q_total_m3s` | m3/s | total simulated discharge |

## Procedure

1. Prepare forcing and soil files with the preceding tools:

   ```bash
   cd KISSPATH_KI_ROOT/HEC_HMS/knowledge_infrastructure
   python3 tools/convert_forcing_to_hms.py \
     --forcing_dir KISSPATH_FORCING/huai/Data_forcing_01dy_025deg/ \
     --basin_shp KISSPATH_DATA/shp/bengbu_shp/bengbu_clip.shp \
     --start_date 1980-01-01 \
     --end_date 1990-12-31 \
     --output_dir ./forcing_out

   python3 tools/convert_soil_to_hms.py \
     --soil_file KISSPATH_STATIC/HWSD_China_Geo.img \
     --landcover_file KISSPATH_DATA/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif \
     --basin_shp KISSPATH_DATA/shp/bengbu_shp/bengbu_clip.shp \
     --output_file ./params/soil_params.json
   ```

2. Run the actual KI engine. Do not replace it with a simplified equation or toy
   script; this is the executable package named in `preflight_check.py`.

   ```bash
   python3 tools/run_hec_hms.py \
     --forcing_csv ./forcing_out/basin_avg_forcing.csv \
     --soil_params ./params/soil_params.json \
     --basin_area_km2 121330 \
     --start_date 1980-01-01 \
     --end_date 1990-12-31 \
     --ia_ratio 0.05 \
     --k_recession 0.95 \
     --q_base_init 50 \
     --recharge_fraction 0.05 \
     --output_csv ./output/sim_discharge.csv
   ```

3. If calibrated parameters are available from `tools/calibrate_hms.py`, pass their
   values as execution overrides.

## Verification

- Confirm `./output/sim_discharge.csv` exists and contains `q_total_m3s`.
- Confirm the log prints SCS-CN, SCS UH, and baseflow sections.
- Confirm `q_total_m3s` has no negative values and the specific discharge warning
  from `validate_outputs` is absent or explained.
- Discard the first year when evaluating Bengbu 1981-1990 validation, because the
  baseflow state is initialized at `q_base_init`.

## Traps

- **dt_103**: CN must be within the valid range. If `soil_params.json` contains
  bad CN, rerun soil conversion and check raster overlap.
- **dt_104** and **dt_113**: An overly large Ia ratio suppresses runoff from many
  daily storms and biases total volume low.
- **dt_105** and **dt_116**: A daily interval that is too coarse relative to Tp, or
  a Tp unsuitable for Bengbu-scale basin area, clips or shifts peaks.
- **dt_106**: Muskingum K/X choices must keep routing coefficients non-negative.
- **dt_107**: `k_recession` is a dimensionless ratio, not a conductivity or rate.
- **dt_114**: Runoff-depth to discharge conversion must use
  `Q = runoff_mm * area_km2 * 1000 / 86400`.

## Example

```bash
cd KISSPATH_KI_ROOT/HEC_HMS/knowledge_infrastructure
mkdir -p output
python3 tools/run_hec_hms.py \
  --forcing_csv ./forcing_out/basin_avg_forcing.csv \
  --soil_params ./params/soil_params.json \
  --basin_area_km2 121330 \
  --start_date 1980-01-01 \
  --end_date 1990-12-31 \
  --ia_ratio 0.05 \
  --output_csv ./output/sim_discharge.csv
```
