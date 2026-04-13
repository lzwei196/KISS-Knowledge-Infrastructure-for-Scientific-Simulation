# S3: Climate Forcing — Atmospheric Forcing Preparation

## Purpose

Prepare atmospheric forcing files (near-surface air temperature and precipitation) for
PISM's surface models. PISM supports multiple atmosphere/surface model combinations,
from directly prescribing surface mass balance to computing it via positive degree-day
(PDD) models or energy balance schemes.

## Inputs

| Source | Variables | Resolution | Period |
|--------|-----------|-----------|--------|
| ERA5 reanalysis | 2m temperature, total precipitation | 0.25° | 1979–present |
| RACMO2.3 | temperature, SMB, precipitation | 1–11 km | Various |
| MAR | temperature, SMB, runoff | 5–25 km | Various |
| GRIP/Vostok | δ¹⁸O → ΔT time series | Scalar | 0–400 ka |

## Outputs

| File | Variables | PISM Units | Description |
|------|-----------|-----------|-------------|
| Climate forcing | `air_temp` | kelvin | Near-surface air temperature |
| Climate forcing | `precipitation` | kg m^-2 year^-1 | Precipitation rate |
| Paleo-temperature | `delta_T` | kelvin | Temperature offset time series |
| Paleo-precipitation | `frac_P` or `delta_P` | 1 or kg m^-2 year^-1 | Precipitation scaling/offset |

## Procedure

### Step 1: Choose Atmosphere/Surface Model Combination

| Combination | When to Use | Command |
|------------|-------------|---------|
| `given` surface | Prescribe SMB directly | `-surface given` |
| `given` atmosphere + `pdd` surface | Compute SMB from temp+precip | `-atmosphere given -surface pdd` |
| `searise_greenland` + `pdd` | SeaRISE Greenland with PDD | `-atmosphere searise_greenland -surface pdd` |
| `given` + `debm_simple` | Energy balance melt model | `-atmosphere given -surface debm_simple` |
| Paleo-climate | Time-varying climate | `-atmosphere given,delta_T,precip_scaling -surface pdd` |

### Step 2: Prepare Temperature Field

```bash
# Convert ERA5 2m temperature from °C to kelvin
ncap2 -O -s "air_temp=t2m+273.15" era5.nc pism_atm.nc
ncatted -O -a units,air_temp,c,c,"kelvin" pism_atm.nc
ncatted -O -a calendar,time,c,c,"365_day" pism_atm.nc
```

**TRAP**: PISM interprets `air_temp` as near-surface temperature, NOT ice surface
temperature. For `surface given` mode, use `ice_surface_temp` instead.

### Step 3: Prepare Precipitation Field

```bash
# ERA5 total precipitation: m/day → kg m^-2 year^-1
# Factor: 1000 (density) × 365.25 (days/year)
ncap2 -O -s "precipitation=tp*1000.0*365.25" era5.nc pism_atm.nc
ncatted -O -a units,precipitation,c,c,"kg m^-2 year^-1" pism_atm.nc
```

### Step 4: Set Time Axis

```bash
# Ensure correct time units and calendar
ncatted -O -a units,time,m,c,"days since 1980-1-1" pism_atm.nc
ncatted -O -a calendar,time,c,c,"365_day" pism_atm.nc
```

For periodic forcing (e.g., monthly climatology over 12 months):
```bash
pism ... -atmosphere given -atmosphere_given_file pism_atm.nc -atmosphere.given.periodic
```

### Step 5: Paleo-Climate Modifiers

For glacial cycle simulations, add temperature and precipitation offsets:

```bash
# Temperature offset from ice core record
# delta_T(time) in kelvin, scalar time series
pism ... -atmosphere searise_greenland,delta_T \
  -atmosphere_delta_T_file pism_dT.nc

# Precipitation scaling
pism ... -atmosphere searise_greenland,delta_T,precip_scaling \
  -atmosphere_precip_scaling_file pism_dT.nc
```

### Step 6: Elevation Lapse Rate Correction

```bash
pism ... -atmosphere given,elevation_change \
  -temp_lapse_rate 6.0 \                    # kelvin/km
  -precip_lapse_rate 0.0 \                  # (kg m^-2 year^-1)/km
  -atmosphere_lapse_rate_file reference_surface.nc
```

## Verification

```python
from netCDF4 import Dataset
ds = Dataset("pism_atm.nc")
temp = ds.variables["air_temp"][:]
precip = ds.variables["precipitation"][:]
print(f"Temperature: {temp.min():.1f} – {temp.max():.1f} K")
print(f"Precipitation: {precip.min():.1f} – {precip.max():.1f} kg m^-2 year^-1")
# Expected: temp 220–280 K for ice sheets, precip 0–5000 kg m^-2 year^-1
ds.close()
```

## Traps

| Trap | Severity | Description |
|------|----------|-------------|
| Temperature in °C not K | FATAL | Sub-zero kelvin → crash or no ice |
| Precipitation in m w.e. not kg/m²/yr | FATAL | 1000× error in accumulation |
| Wrong calendar | SILENT | Forcing applied at wrong time of year |
| Missing time bounds | DEGRADED | PISM may interpolate incorrectly |
| delta_T double-conversion | SILENT | Already in kelvin, converting again |
| `air_temp` vs `ice_surface_temp` | SILENT | Wrong variable for chosen surface model |

## Example

```bash
# Using the KI tool:
python ki/tools/convert_climate_forcing.py \
  --input era5_monthly_greenland.nc \
  --output pism_climate.nc \
  --temp-var t2m --precip-var tp \
  --temp-units celsius --precip-units "mm/day" \
  --calendar 365_day

# Run with PDD surface model
mpiexec -n 8 pism \
  -i bootstrap.nc -bootstrap \
  -atmosphere given -atmosphere_given_file pism_climate.nc \
  -atmosphere.given.periodic \
  -surface pdd \
  -y 1000 -o output.nc
```
