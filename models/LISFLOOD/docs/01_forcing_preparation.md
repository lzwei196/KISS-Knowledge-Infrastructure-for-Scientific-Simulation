# Stage 1: Meteorological Forcing Preparation

## Purpose

Convert global meteorological datasets (ERA5, CMFD, MSWX) to LISFLOOD-compatible NetCDF forcing stacks. LISFLOOD requires four forcing variables at each grid cell and timestep:

| Variable | Description | Unit | Prefix in settings |
|----------|-------------|------|--------------------|
| pr | Precipitation (rain + snow) | mm/day | `PrecipitationMaps` |
| ta | Average air temperature | °C (or K) | `TavgMaps` |
| et0 | Reference evapotranspiration (potential) | mm/day | `ET0Maps` |
| e0 | Open water evaporation (potential) | mm/day | `E0Maps` |

## Inputs

| Input | Source | Format | Notes |
|-------|--------|--------|-------|
| Precipitation | ERA5 `tp`, CMFD `prec` | NetCDF | Requires unit conversion |
| Temperature | ERA5 `t2m`, CMFD `temp` | NetCDF | K or °C, must match flag |
| ET0 | ERA5 PET or Hargreaves estimate | NetCDF or computed | Must be POTENTIAL ET |
| E0 | ~ 1.05 × ET0 for open water | Computed | Penman approximation |
| Domain mask | MaskMap from LISFLOOD setup | NetCDF/PCRaster | Defines spatial extent |

## Outputs

| Output | Format | Naming Convention |
|--------|--------|-------------------|
| pr.nc | NetCDF (time × lat × lon) | Or: `pr00001.nc`, `pr00002.nc`, ... |
| ta.nc | NetCDF (time × lat × lon) | Or as PCRaster map stack |
| et0.nc | NetCDF (time × lat × lon) | Variable names must match `lfbinding` |
| e0.nc | NetCDF (time × lat × lon) | Same coordinate system as MaskMap |

## Procedure

1. **Identify source data format** — ERA5 (m/timestep, K), CMFD (mm/3hr, K), or MSWX (mm/3hr, °C)
2. **Convert precipitation to mm/day**:
   - ERA5: `pr_mm_day = tp_m * 1000` (m → mm, already daily if daily ERA5)
   - CMFD: `pr_mm_day = sum_8_3hr_steps` (aggregate 3-hourly to daily)
   - Clip negative values: `pr = max(0, pr)`
3. **Convert temperature**:
   - If source is K and `TemperatureInKelvin=0`: subtract 273.15
   - If source is K and `TemperatureInKelvin=1`: no conversion needed
   - If source is °C and `TemperatureInKelvin=0`: no conversion needed
4. **Prepare ET0**:
   - If available from forcing (ERA5 PET): convert units to mm/day
   - If not available: estimate using Hargreaves method from Tmin, Tmax, latitude
   - **Must be potential ET**, not actual — LISFLOOD reduces internally
5. **Prepare E0**: multiply ET0 by ~1.05 (Penman open water factor)
6. **Write NetCDF stacks** with correct coordinate system and time axis
7. **Validate ranges**: pr < 500 mm/day, -60 < ta < 60 °C, 0 < et0 < 20 mm/day

## Verification

- [ ] Precipitation max < 500 mm/day (check: not in m/day by mistake)
- [ ] Temperature range physically realistic (not still in Kelvin)
- [ ] ET0 all positive (potential evaporation cannot be negative)
- [ ] Time axis matches `CalendarDayStart` and `StepStart`/`StepEnd` in settings
- [ ] Spatial extent covers the entire MaskMap domain
- [ ] No NaN values within the model domain

## Traps

| Trap | Severity | Description |
|------|----------|-------------|
| dt_001 | **silent** | Precipitation in wrong units — m/day vs mm/day. ERA5 gives meters; multiply by 1000. |
| dt_002 | **silent** | Temperature K/°C flag mismatch. If `TemperatureInKelvin=0` but input is K, snow model breaks. |
| dt_003 | **silent** | ET0 is actual instead of potential — underestimates evaporation by 30-50%. |
| dt_004 | **silent** | Forcing timestep doesn't match `DtSec`. Daily forcing with 6-hourly model timestep requires interpolation. |

## Example

```bash
# Convert CMFD forcing for a Chinese basin
python tools/convert_forcing.py \
    --source_dir KISSPATH_DATA/cmfd/daily/ \
    --source_type cmfd \
    --output_dir /path/to/lisflood/forcings/ \
    --start_date 2000-01-01 \
    --end_date 2010-12-31 \
    --mask_file /path/to/mask.nc \
    --temp_unit celsius

# Verify output
python -c "
import xarray as xr
ds = xr.open_dataset('forcings/pr.nc')
print('Precip range:', ds['pr'].min().values, '-', ds['pr'].max().values, 'mm/day')
print('Time range:', ds.time[0].values, '-', ds.time[-1].values)
"
```
