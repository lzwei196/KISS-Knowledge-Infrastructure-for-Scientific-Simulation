# Stage 2: Forcing Data Conversion

## Purpose

Convert global or regional meteorological forcing datasets (precipitation and potential evapotranspiration) into the gridded time series format required by EF5. This stage handles unit conversions, temporal disaggregation, spatial clipping, and file naming conventions.

## Inputs

| Input | Format | Unit | Source |
|-------|--------|------|--------|
| Precipitation | NetCDF, GeoTIFF | mm/hr, mm/3h, mm/day | CMFD, MSWX, CHIRPS, GPM, Q2 radar |
| PET | NetCDF, GeoTIFF, CSV | mm/hr, mm/day, mm/month, °C | CMFD, Penman-Monteith, Hargreaves |
| Basin extent | Bounding box | degrees | From Stage 1 DEM |

## Outputs

| Output | Format | Unit | Description |
|--------|--------|------|-------------|
| Precip grids | ASC/BIF/TIF (one per timestep) | mm/hr (recommended) | Timestamped precipitation grids |
| PET grids | ASC/BIF/TIF (one per timestep) | mm/hr or °C | Timestamped PET grids |

## Procedure

### Step 1: Identify source data characteristics

Determine:
- Variable name in NetCDF (e.g., `prec`, `precipitation`, `tp`)
- Native unit (check attributes carefully!)
- Temporal resolution (hourly, 3-hourly, daily, monthly)
- Spatial resolution and projection

### Step 2: Configure unit conversion

EF5 internally converts all precipitation to mm/hr using the `UNIT` config:

| Source | Config UNIT | Internal treatment |
|--------|------------|-------------------|
| mm/hr | `mm/h` | Direct |
| mm/3hr (CMFD) | `mm/3h` | Divide by 3 |
| mm/day | `mm/d` | Divide by 24 |
| kg/m²/s (ERA5) | Convert to mm/hr first | × 3600 |

**CRITICAL**: The UNIT in config must match the actual unit of the files, not the desired unit. EF5 does the conversion internally.

### Step 3: Configure temporal frequency

Set `FREQ` to match the temporal spacing of your forcing files:

```
FREQ=5u       # Every 5 minutes
FREQ=1h       # Hourly
FREQ=3h       # 3-hourly
FREQ=d        # Daily
FREQ=m        # Monthly
```

### Step 4: Set filename template

EF5 replaces date tokens in the NAME field:
- `YYYY` → year (4-digit)
- `MM` → month (2-digit, zero-padded)
- `DD` → day
- `HH` → hour
- `UU` → minute
- `SS` → second

Example: `NAME=precip_YYYYMMDDHHUU.asc` → `precip_201001010300.asc`

### Step 5: Convert and write grids

Use the provided tool:
```bash
python convert_forcing_to_ef5.py \
    /data/cmfd/precipitation.nc prec \
    --source-unit mm/3h \
    --target-unit mm/h \
    --output-dir /ef5/precip/ \
    --name-template "precip_YYYYMMDDHHUU.asc" \
    --format asc \
    --bbox 116.0 32.0 118.5 34.5
```

### Step 6: PET handling

EF5 supports two PET modes:
1. **Direct PET** (UNIT=mm/h, mm/d, etc.): pre-computed PET grids
2. **Temperature-based** (UNIT=C): EF5 converts temperature to PET internally

For temperature-based PET:
```ini
[PETForcing PET]
TYPE=TIF
UNIT=C          # Temperature in Celsius!
FREQ=d
LOC=/data/temp/
NAME=temp_YYYYMMDD.tif
```

## Verification

1. **Unit check**: Open a sample grid, verify values are reasonable
   - Precipitation: 0-150 mm/hr typical (0-300 for extreme events)
   - PET: 0-10 mm/hr typical
   - Temperature: -40 to 50 °C
2. **Temporal coverage**: Count files vs expected timesteps
3. **Spatial coverage**: Check grid covers entire basin DEM
4. **Nodata**: Verify nodata areas don't overlap with basin cells

```python
import numpy as np
data = np.loadtxt("precip_sample.asc", skiprows=6)
print(f"Range: [{data[data > -9999].min():.2f}, {data[data > -9999].max():.2f}]")
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| UNIT mismatch | 24× too much/little rainfall | Verify UNIT matches actual file content |
| FREQ mismatch | Skipped or duplicated timesteps | Match FREQ to actual file temporal spacing |
| Kelvin not Celsius | Enormous PET values | Subtract 273.15 before writing grids |
| kg/m²/s not mm/hr | 3600× scaling error | Multiply by 3600 (1 kg/m²/s = 3600 mm/hr) |
| Wrong NAME template | "File not found" at runtime | Check date token positions match actual filenames |
| Grid resolution mismatch | Poor forcing interpolation | EF5 handles interpolation, but extreme mismatch degrades results |
| Negative precipitation | Water balance breaks | Clip to zero: `data[data < 0] = 0` |
| UTC vs local time | Temporal shift in hydrograph | Ensure all forcing uses consistent timezone |

## Example

```ini
[PrecipForcing CMFD]
TYPE=ASC
UNIT=mm/3h
FREQ=3h
LOC=/data/bengbu/precip/
NAME=cmfd_prec_YYYYMMDDHHUU.asc

[PETForcing CMFD_PET]
TYPE=ASC
UNIT=mm/d
FREQ=d
LOC=/data/bengbu/pet/
NAME=cmfd_pet_YYYYMMDD.asc
```
