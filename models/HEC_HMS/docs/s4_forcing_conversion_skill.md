# S4: Forcing Conversion Skill

## Purpose

Convert basin-overlapping CMFD/MSWX-style NetCDF forcing into the daily CSV format
used by this KI's Python HEC-HMS engine. The implemented converter,
`tools/convert_forcing_to_hms.py`, extracts basin-average precipitation,
temperature, and radiation, applies unit conversions, computes PET, and writes
`basin_avg_forcing.csv` plus `basin_info.json`.

## Inputs

| Input | Format | Required by |
|-------|--------|-------------|
| Forcing directory | NetCDF files by year/variable | `--forcing_dir` |
| Basin shapefile | `.shp`, readable by geopandas | `--basin_shp` |
| Start and end dates | `YYYY-MM-DD` | `--start_date`, `--end_date` |

## Outputs

| Output | Format | Produced by |
|--------|--------|-------------|
| `basin_avg_forcing.csv` | daily CSV | `tools/convert_forcing_to_hms.py` |
| `basin_info.json` | JSON area and bounds | `tools/convert_forcing_to_hms.py` |
| `precip_mm` | mm/day | model forcing column |
| `temp_c` | degC | model forcing column |
| `pet_mm` | mm/day | model forcing column |

## Procedure

1. Run preflight from the KI directory:

   ```bash
   cd KISSPATH_KI_ROOT/HEC_HMS/knowledge_infrastructure
   python3 preflight_check.py
   ```

2. Convert the Bengbu CMFD forcing to the CSV expected by `tools/run_hec_hms.py`:

   ```bash
   python3 tools/convert_forcing_to_hms.py \
     --forcing_dir KISSPATH_FORCING/huai/Data_forcing_01dy_025deg/ \
     --basin_shp KISSPATH_DATA/shp/bengbu_shp/bengbu_clip.shp \
     --start_date 1980-01-01 \
     --end_date 1990-12-31 \
     --output_dir ./forcing_out
   ```

3. Use `./forcing_out/basin_avg_forcing.csv` as `--forcing_csv` for
   `tools/run_hec_hms.py` and `tools/calibrate_hms.py`.

## Verification

- Confirm `./forcing_out/basin_avg_forcing.csv` has a daily date index and the
  columns `precip_mm`, `temp_c`, and usually `pet_mm`.
- Confirm `./forcing_out/basin_info.json` reports area in km2, not m2.
- Check converter output statistics: annual precipitation should not be near zero
  or above several thousand mm/yr for the Huai/Bengbu run.
- Check mean temperature is in Celsius-scale values, not Kelvin-scale values.

## Traps

- **dt_101**: CMFD precipitation rate/depth handling must match the model timestep.
  `convert_forcing_to_hms.py` detects small rate-like precipitation and multiplies
  by 86400 to produce mm/day.
- **dt_102**: CMFD temperature must be Celsius before PET calculations. The converter
  checks for Kelvin-scale values and subtracts 273.15.
- **dt_110**: Radiation must be converted from W/m2 to MJ/m2/day before PET.
- **dt_117**: Missing precipitation days filled as zero create artificial dry spells;
  inspect gap warnings before accepting the forcing CSV.
- **dt_115**: The requested simulation period must be covered by available forcing files.

## Example

```bash
cd KISSPATH_KI_ROOT/HEC_HMS/knowledge_infrastructure
mkdir -p forcing_out
python3 tools/convert_forcing_to_hms.py \
  --forcing_dir KISSPATH_FORCING/huai/Data_forcing_01dy_025deg/ \
  --basin_shp KISSPATH_DATA/shp/bengbu_shp/bengbu_clip.shp \
  --start_date 1980-01-01 \
  --end_date 1990-12-31 \
  --output_dir ./forcing_out
```
