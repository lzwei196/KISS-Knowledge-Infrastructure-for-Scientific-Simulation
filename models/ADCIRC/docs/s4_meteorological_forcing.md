# S4: Meteorological Forcing (fort.22)

## Purpose

Prepare wind and atmospheric pressure forcing for ADCIRC storm surge and wind-driven circulation simulations. The meteorological forcing is the primary driver of storm surge and must be properly formatted with correct units. ADCIRC supports 30+ meteorological formats via the NWS parameter.

## Inputs

| Input | Source | Format | Description |
|-------|--------|--------|-------------|
| Wind velocity | GFS, ERA5, HRRR, HWRF | GRIB2/netCDF | 10m wind u,v components |
| Atmospheric pressure | GFS, ERA5 | GRIB2/netCDF | Sea-level pressure |
| Hurricane track | NHC best-track, ATCF | CSV/text | For parametric wind models |

## Outputs

| Output | File | Format | Description |
|--------|------|--------|-------------|
| Control file | `fort.22` | ASCII | NWS-specific control/header |
| Pressure field | `fort.221` | OWI ASCII | Gridded pressure (mb) |
| Wind field | `fort.222` | OWI ASCII | Gridded wind u,v (m/s) |

## Procedure

### NWS Format Selection

| NWS | Format | Input | Best For |
|-----|--------|-------|----------|
| 0 | None | — | Tidal-only runs |
| 8 | Holland parametric | Hurricane track params | Quick hurricane estimates |
| 12 | OWI gridded | fort.221 + fort.222 | Real-time forecasting |
| 13 | OWI netCDF | fort.221.nc + fort.222.nc | Large hindcast studies |
| 14 | GRIB2 direct | GRIB2 files | Direct NWP model coupling |

### OWI Format Details (NWS=12)

The OWI format is the most commonly used for operational forecasting.

**fort.22 (control file)**:
```
1             ! Number of basin-scale sets
0             ! Number of region-scale sets
fort.221      ! Pressure filename
fort.222      ! Wind filename
```

**fort.221 (pressure) header per timestep**:
```
iLat=  29iLong=  41DX=0.2500DY=0.2500SWLat= 24.0000SWLon= -98.0000DT=200508250000
```

**Critical fields**:
- `iLat`, `iLong`: Grid dimensions (number of points)
- `DX`, `DY`: Grid spacing in degrees
- `SWLat`, `SWLon`: Southwest corner coordinates
- `DT`: Datetime string (YYYYMMDDHHmm)

**Data values**: 8 values per line, space-separated, fixed width 10.4f format.

### Unit Conversions

| Variable | Source Unit | ADCIRC (OWI) Unit | Conversion |
|----------|-----------|-------------------|------------|
| Pressure | Pa | mb (hPa) | ÷ 100 |
| Pressure | inHg | mb | × 33.8639 |
| Wind speed | knots | m/s | × 0.5144 |
| Wind speed | km/h | m/s | ÷ 3.6 |
| Wind speed | mph | m/s | × 0.44704 |

**WARNING**: ADCIRC internally converts pressure from mb to meters of water column:
`P_mH2O = (P_standard - P_actual) × 100 / (rho_water × g)`
Getting the input units wrong (e.g., Pa instead of mb) produces extreme or zero surge (dt_003).

### Wind Drag

ADCIRC uses the Garratt (1977) drag law by default:
```
Cd = 0.001 × (0.75 + 0.067 × W10)
```
Capped at Cd = 0.003 for W10 > 33.6 m/s (dt_004).

For major hurricanes (Category 3+), consider alternative drag laws:
- Powell et al. (2003): Drag reduction at high winds
- Donelan et al. (2004): Cap at lower value

## Verification

```bash
# Check OWI header format
head -2 fort.221

# Verify pressure range (should be 900-1050 mb)
python3 -c "
import numpy as np
vals = []
with open('fort.221') as f:
    for line in f:
        if line.startswith('iLat') or line.startswith('Basin'): continue
        try: vals.extend([float(x) for x in line.split()])
        except: pass
a = np.array(vals)
print(f'Pressure: min={a.min():.1f}, max={a.max():.1f} mb')
if a.min() < 100: print('WARNING: Pressure likely in Pa, not mb!')
if a.max() > 50000: print('WARNING: Pressure definitely in Pa!')
"

# Verify wind speed range (should be 0-80 m/s)
python3 -c "
import numpy as np
vals = []
with open('fort.222') as f:
    for line in f:
        if line.startswith('iLat') or line.startswith('Basin'): continue
        try: vals.extend([float(x) for x in line.split()])
        except: pass
a = np.array(vals)
print(f'Wind: min={a.min():.1f}, max={a.max():.1f} m/s')
if a.max() > 100: print('WARNING: Wind may be in knots or km/h!')
"
```

## Traps

| Trap | ID | Symptom |
|------|----|---------|
| Pressure in Pa not mb | dt_003 | Extreme surge or zero surge |
| Wind in knots not m/s | dt_010 | Surge ~50% of expected (knots) or 3.6x (km/h) |
| OWI header off-by-one | dt_007 | Wind applied at wrong locations |
| Grid mismatch with mesh domain | — | Zero forcing over mesh area |
| WTIMINC mismatch with data interval | — | Temporal interpolation errors |

## Example

```bash
# Convert ERA5 to OWI format
python ki/tools/convert_forcing_to_adcirc.py \
    --input_dir /data/era5/katrina/ \
    --format era5_nc \
    --domain_sw 24.0,-98.0 --domain_ne 31.0,-88.0 \
    --resolution 0.25 \
    --start_date 2005-08-25 --end_date 2005-09-01 \
    --output_dir ./

# Verify output
ls -la fort.22 fort.221 fort.222
head -3 fort.221
```
