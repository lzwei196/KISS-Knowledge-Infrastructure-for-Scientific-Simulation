# S4 Inflow

## Purpose
Create the daily reservoir inflow CSV required by Pywr catchment/dataframe parameters. This KI supports VIC-derived inflow through `../tools/s4_inflow/convert_vic_to_inflow.py` and observed-discharge inflow through `../tools/s4_inflow/convert_obs_to_inflow.py`.

## Inputs
- VIC result directory containing flux files: `outputs/{run}/vic_result/`.
- VIC grid NetCDF: `outputs/{run}/vic_temp/grid/*.nc`.
- Dam latitude and longitude from S2/S3.
- Start and end years for VIC conversion.
- Optional observed discharge file for the observed path.
- Coupling reference: `model_couplings.yaml` entry `coupling_vic_to_pywr_inflow`.

## Outputs
- Inflow CSV for S7, normally with daily dates and inflow in `m3/s`.
- Optional summary JSON from `--output_json` with cell counts and inflow statistics.

## Procedure
Convert VIC runoff and baseflow to Pywr inflow:

```bash
KI=KISSPATH_KI_ROOT/Pywr/knowledge_infrastructure
PYWR_PYTHON="KISSPATH_HOME/桌面/test/hydro-claude/python_env/bin/python3"

"$PYWR_PYTHON" "$KI/tools/s4_inflow/convert_vic_to_inflow.py" \
  --vic_dir outputs/bengbu_1980-1990_025deg/vic_result \
  --grid_nc outputs/bengbu_1980-1990_025deg/vic_temp/grid/grid_bengbu_1980-1990_025deg_025deg.nc \
  --dam_lat 31.43 \
  --dam_lon 115.92 \
  --method all \
  --start_year 1980 \
  --end_year 1990 \
  --output /tmp/pywr_inflow.csv \
  --output_json /tmp/pywr_inflow_summary.json
```

Convert observed discharge when VIC output is unavailable:

```bash
"$PYWR_PYTHON" "$KI/tools/s4_inflow/convert_obs_to_inflow.py" \
  --obs_file data/obs/WJB/HUAIH-51030-wangjiaba.txt \
  --station_area_km2 30630 \
  --dam_area_km2 1094 \
  --start_date 1981-01-01 \
  --end_date 1990-12-31 \
  --output /tmp/pywr_inflow.csv
```

## Verification
- Confirm `/tmp/pywr_inflow.csv` covers every daily timestep that S7 will request.
- If `--output_json` was used, check `cells_found > 0` and mean inflow is positive for a non-dry basin.
- Check inflow values are non-negative and plausible for the basin area.
- Date range must align with `--start_date` and `--end_date` in S7.

## Traps
- `dt_pywr_005`: all-zero inflow usually means wrong upstream cells or VIC flux filename mismatch; check `cells_found` and `cells_missing`.
- `dt_pywr_015`: VIC `mm/day` to Pywr `m3/s` must divide by `1000` and `86400`.
- `dt_pywr_013`: inflow date coverage must match the model timestepper dates used in S7.

## Example
```bash
KI=KISSPATH_KI_ROOT/Pywr/knowledge_infrastructure
PYWR_PYTHON="KISSPATH_HOME/桌面/test/hydro-claude/python_env/bin/python3"
"$PYWR_PYTHON" "$KI/tools/s4_inflow/convert_vic_to_inflow.py" \
  --vic_dir outputs/bengbu_1980-1990_025deg/vic_result \
  --grid_nc outputs/bengbu_1980-1990_025deg/vic_temp/grid/grid_bengbu_1980-1990_025deg_025deg.nc \
  --dam_lat 31.43 --dam_lon 115.92 \
  --method all --start_year 1980 --end_year 1990 \
  --output /tmp/pywr_inflow.csv
```
