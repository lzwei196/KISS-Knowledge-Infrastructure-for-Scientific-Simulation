# Stage 2: Atmospheric Forcing Preparation

## Purpose

Convert atmospheric reanalysis or observational data into the format required
by CLM5's data atmosphere component (DATM/CDEPS). This is the most
error-prone stage due to unit conversion requirements — incorrect forcing
units produce silent errors that propagate through all model outputs.

## Prerequisites

- Stage 0 complete (case configured)
- Raw atmospheric forcing data available (ERA5, GSWP3, CRUJRA, or station data)
- Python environment with `xarray`, `numpy`, `netCDF4`
- Knowledge of forcing data temporal resolution and calendar

## Inputs

| Input | Source | Format | Variables |
|---|---|---|---|
| ERA5 hourly | Copernicus CDS | NetCDF | t2m, d2m, tp, ssrd, strd, sp, u10, v10 |
| GSWP3 | NCAR RDA | NetCDF | Tair, Qair, Wind, Precip, SWdown, LWdown, PSurf |
| CRUJRA | UEA CRU | NetCDF | tmp, spfh, ugrd, vgrd, pre, dswrf, dlwrf, pres |
| Station CSV | Local | CSV | datetime, temperature, humidity, wind_speed, precip, SW, LW, pressure |

## Required CLM5 DATM Variables

| DATM Variable | Description | Units | Physical Range |
|---|---|---|---|
| TBOT | Bottom atmosphere temperature | K | 200–330 |
| QBOT | Bottom atmosphere specific humidity | kg/kg | 0–0.04 |
| WIND | Wind speed at reference height | m/s | 0–50 |
| PRECTmms | Total precipitation rate | mm/s (= kg/m2/s) | 0–0.1 |
| FSDS | Downward shortwave radiation | W/m2 | 0–1400 |
| FLDS | Downward longwave radiation | W/m2 | 50–600 |
| PSRF | Surface pressure | Pa | 50000–110000 |

## Procedure

### Step 1: Identify source format and units

Before any conversion, verify:
- What calendar does the forcing use? (gregorian, noleap, 360_day)
- What temporal resolution? (hourly, 3-hourly, 6-hourly, daily)
- Are radiation fluxes instantaneous or accumulated?
- Is precipitation a rate (mm/s) or accumulated (mm/timestep)?

### Step 2: Run the forcing converter

```bash
python ki/tools/convert_forcing_to_clm.py \
    --source era5 \
    --input /path/to/era5_data.nc \
    --output /path/to/datm_forcing/ \
    --lat 40.0 --lon 116.0 \
    --start-year 2000 --end-year 2010
```

### Step 3: Validate converted forcing

Check the output JSON for warnings:
```json
{
  "status": "success",
  "warnings": [],
  "variables_converted": ["TBOT", "QBOT", "WIND", "PRECTmms", "FSDS", "FLDS", "PSRF"]
}
```

### Step 4: Configure DATM streams

In the CLM5 case, point DATM to the converted files:
```bash
# In user_nl_datm_streams (for CDEPS) or user_nl_datm
./xmlchange DATM_MODE=CLMCRUNCEPv7
```

Or create custom stream files for non-standard forcing.

## Outputs

| Output | Format | Description |
|---|---|---|
| clmforc.TBOT.nc | NetCDF | Temperature forcing (K) |
| clmforc.QBOT.nc | NetCDF | Humidity forcing (kg/kg) |
| clmforc.WIND.nc | NetCDF | Wind speed forcing (m/s) |
| clmforc.PRECTmms.nc | NetCDF | Precipitation forcing (mm/s) |
| clmforc.FSDS.nc | NetCDF | Shortwave forcing (W/m2) |
| clmforc.FLDS.nc | NetCDF | Longwave forcing (W/m2) |
| clmforc.PSRF.nc | NetCDF | Pressure forcing (Pa) |

## Verification

1. **Temperature**: Mean should be 250–310 K for most locations; values < 200 K
   indicate Celsius was not converted
2. **Humidity**: All values 0–0.04 kg/kg; values > 1 indicate RH was used
3. **Precipitation**: Max rate should be < 0.1 mm/s; rates > 1 indicate wrong
   time conversion (mm/day used as mm/s)
4. **Shortwave**: All values >= 0; diurnal cycle visible; max < 1400 W/m2
5. **Longwave**: All values in 50–600 W/m2 range; no zeros at night
6. **Pressure**: Should be ~101325 Pa at sea level; values < 1000 indicate kPa

## Common Traps

### dt_001: Precipitation unit mismatch (CRITICAL, SILENT)

ERA5 provides precipitation in **meters per timestep** (accumulated).
Converting to mm/s requires: `precip_mm_s = precip_m * 1000 / timestep_s`

If you use mm/day directly as mm/s, precipitation is 86400x too high.
The model may crash (NaN soil moisture) or produce unrealistic runoff.

### dt_002: Temperature in Celsius (SILENT)

If temperature is 20°C and used as 20 K, longwave emission (σT⁴) drops
to near zero, all energy balance breaks down. CLM5 will still run but
produce frozen soils everywhere.

### dt_003: Downward vs net longwave (SILENT)

Using net longwave (which can be negative) as downward longwave causes
energy deficit and unrealistic surface cooling. Always verify that LW
values are positive and in the 50–600 W/m2 range.

### dt_004: Specific humidity vs relative humidity (SILENT)

If RH=80% is entered as QBOT=80.0 kg/kg, the model crashes immediately.
If RH=0.80 is entered as QBOT=0.80, the model runs with severe
overestimation of latent heat flux and precipitation recycling.

### dt_013: Temporal resolution mismatch (DEGRADED)

If forcing is 6-hourly but DATM expects 3-hourly, CLM5 may interpolate
incorrectly (especially for precipitation, which should not be linearly
interpolated). Set `tintalgo` appropriately in stream files.

## Example

Convert CMFD data for Bengbu basin (China):

```bash
python ki/tools/convert_forcing_to_clm.py \
    --source csv \
    --input /mnt/disk1/Hydrocraft_server/data/bengbu_forcing.csv \
    --output /path/to/datm/ \
    --lat 32.95 --lon 117.35
```
