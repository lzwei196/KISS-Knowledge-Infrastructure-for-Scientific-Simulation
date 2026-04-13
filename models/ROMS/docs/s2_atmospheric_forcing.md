# S2: Atmospheric Forcing Preparation

## Purpose

Convert global reanalysis or weather model output (ERA5, CFSR, GFS, NAM) into
ROMS-compatible NetCDF forcing files. This is the most error-prone step due to
unit conversions — most errors here are SILENT and produce plausible but wrong
results.

## Inputs

| Input | Format | Source | Variables |
|-------|--------|--------|-----------|
| Atmospheric reanalysis | NetCDF/GRIB | ERA5, CFSR | u10, v10, t2m, sp, d2m, tp, ssr, str |
| ROMS grid file | NetCDF | S0 output | lon_rho, lat_rho, mask_rho |

## Outputs

| Output | Format | Variables |
|--------|--------|-----------|
| `roms_frc.nc` | NetCDF | Uwind, Vwind, Tair, Pair, Qair, rain, swrad, lwrad |

Each variable has its own time dimension (e.g., `Uwind_time`, `Tair_time`)
allowing different temporal resolution per variable.

## Procedure

### Step 1: Download source data
For ERA5, use the CDS API:
```python
import cdsapi
c = cdsapi.Client()
c.retrieve('reanalysis-era5-single-levels', {
    'variable': ['10m_u_component_of_wind', '10m_v_component_of_wind',
                 '2m_temperature', 'surface_pressure',
                 '2m_dewpoint_temperature', 'total_precipitation',
                 'surface_net_solar_radiation', 'surface_net_thermal_radiation'],
    'year': '2020', 'month': '01', 'day': list(range(1,32)),
    'time': [f'{h:02d}:00' for h in range(24)],
    'area': [42, -76, 35, -70],  # N, W, S, E
    'format': 'netcdf',
}, 'era5_forcing.nc')
```

### Step 2: Unit conversions

**This is where most ROMS simulations go wrong.** Apply conversions carefully:

| Variable | ERA5 name | ERA5 units | ROMS units | Conversion |
|----------|-----------|------------|------------|------------|
| Uwind | u10 | m/s | m/s | None |
| Vwind | v10 | m/s | m/s | None |
| Tair | t2m | K | °C | Subtract 273.15 |
| Pair | sp | Pa | mb (hPa) | Divide by 100 |
| Qair | d2m (dewpoint K) | K | kg/kg | Psychrometric formula |
| rain | tp | m/accumulation | kg/m²/s | See below |
| swrad | ssr | J/m²/accumulation | W/m² | See below |
| lwrad | str | J/m²/accumulation | W/m² | See below |

**Precipitation (CRITICAL — SILENT ERROR):**
- ERA5 `tp` is in meters of water per accumulation period
- ROMS expects kg/m²/s
- For hourly ERA5: `rain = tp * 1000.0 / 3600.0`
- For mm/day sources: `rain = value / 86400.0`
- Getting this wrong by 1000x floods or dries out the domain

**Humidity (CRITICAL — SILENT ERROR):**
- ERA5 gives dewpoint temperature (d2m in K)
- ROMS with BULK_FLUXES expects specific humidity (kg/kg)
- Conversion: `es = 6.112 * exp(17.67 * Td_C / (Td_C + 243.5))`
- Then: `q = 0.622 * es / (P_mb - 0.378 * es)`
- Typical range: 0.001–0.020 kg/kg
- If values are 1–100, units are probably % RH (wrong)

**Radiation (ERA5 accumulations):**
- ERA5 radiation is accumulated J/m² since last forecast step
- Divide by accumulation period (seconds) to get W/m²
- Shortwave must be positive (downward into ocean)
- Clip negative shortwave to 0 (nighttime artifacts)

### Step 3: Interpolate to ROMS grid
Bilinearly interpolate each variable from the source grid to the ROMS RHO-grid.
Apply land masking from the ROMS grid.

### Step 4: Write NetCDF
Each variable gets its own time dimension:
```
dimensions:
  Uwind_time = UNLIMITED
  Tair_time = UNLIMITED
  ...
  eta_rho = 80
  xi_rho = 120

variables:
  Uwind_time(Uwind_time)  units: "seconds since 2020-01-01"
  Uwind(Uwind_time, eta_rho, xi_rho)  units: "m/s"
  ...
```

### Step 5: Validate

```bash
python tools/convert_forcing.py \
  --mode forcing \
  --source era5_hourly.nc \
  --grid roms_grid.nc \
  --output roms_frc.nc \
  --time-ref "2020-01-01"
```

## Verification

Check value ranges match physical expectations:

```python
from netCDF4 import Dataset
ds = Dataset('roms_frc.nc')

checks = {
    'Tair': (-40, 50, 'Celsius'),
    'Pair': (900, 1100, 'mb'),
    'Qair': (0, 0.03, 'kg/kg'),
    'rain': (0, 0.05, 'kg/m2/s'),
    'swrad': (0, 1400, 'W/m2'),
    'lwrad': (-300, 100, 'W/m2'),
    'Uwind': (-50, 50, 'm/s'),
    'Vwind': (-50, 50, 'm/s'),
}

for var, (vmin, vmax, units) in checks.items():
    if var in ds.variables:
        data = ds.variables[var][:]
        actual_min = float(data.min())
        actual_max = float(data.max())
        ok = vmin <= actual_min and actual_max <= vmax
        status = "OK" if ok else "FAIL"
        print(f"{var}: [{actual_min:.4f}, {actual_max:.4f}] {units} — {status}")
ds.close()
```

## Traps

| Trap | Description | How to detect |
|------|-------------|---------------|
| Rain 1000x too high | mm/day not converted to kg/m²/s | Max rain > 0.1 |
| Temperature in Kelvin | Forgot to subtract 273.15 | Mean Tair > 200 |
| Pressure in Pa | Forgot to divide by 100 | Mean Pair > 50000 |
| Humidity in % | Not converted to kg/kg | Mean Qair > 1 |
| Radiation sign wrong | Shortwave negative | Mean swrad < 0 |
| Accumulated radiation | J/m² not divided by dt | swrad > 2000 |
| Time reference mismatch | Different epoch than roms.in TIME_REF | Forcing applied at wrong time |

## Example

```bash
# Convert ERA5 data to ROMS forcing
python tools/convert_forcing.py \
  --mode forcing \
  --source era5_2020_jan.nc \
  --grid roms_grid.nc \
  --output roms_frc_2020jan.nc \
  --time-ref "2020-01-01" \
  --precip-units "m/day" \
  --humidity-type "dewpoint"
```
