# Stage 2: Forcing Data Preparation

## Purpose

Convert global or regional forcing datasets into EF5-compatible gridded precipitation and PET files with correct unit conversions. This is the most error-prone stage due to silent unit conversion mistakes.

## Inputs

| Input | Format | Units | Source |
|-------|--------|-------|--------|
| Precipitation | NetCDF, GeoTIFF, HDF5 | Varies by product | CMFD, MSWX, GPM IMERG, TRMM, MRMS, Q2 |
| PET | NetCDF, GeoTIFF | Varies | GLEAM, MOD16, computed from T (Hamon/Hargreaves) |
| Temperature | NetCDF, GeoTIFF | degC or K | CMFD, ERA5, MSWX (required for Snow-17) |
| Domain extent | From DEM grid | — | Stage 1 output |

## Outputs

| Output | Format | Units (EF5 internal) |
|--------|--------|---------------------|
| Precipitation grids | ASC, BIF, or TIF | mm/hr (rate) |
| PET grids | ASC, BIF, or TIF | mm/hr (rate) or degC |
| Temperature grids | ASC, BIF, or TIF | degC (for Snow-17) |

## Procedure

### 1. Determine source units and frequency

| Product | Native Unit | Frequency | Conversion to mm/hr |
|---------|-------------|-----------|----------------------|
| CMFD | mm/hr | 3-hourly | 1.0 (already correct) |
| GPM IMERG | mm/hr | 30-min | 1.0 |
| TRMM 3B42RT | mm/hr | 3-hourly | 1.0 |
| TRMM 3B42V7 | mm/3hr | 3-hourly | ÷ 3 |
| MRMS Q2 | mm/hr | 5-min | 1.0 |
| ERA5 | m/hr | hourly | × 1000 |
| MSWX | mm/day | daily | ÷ 24 |

### 2. Resample to DEM grid

```python
# Using GDAL to resample precip to DEM grid
from osgeo import gdal
gdal.Warp("precip_resampled.tif", "precip_source.tif",
          xRes=dem_cellsize, yRes=dem_cellsize,
          outputBounds=[xmin, ymin, xmax, ymax],
          resampleAlg="bilinear")
```

### 3. Apply unit conversion

```python
from tools.convert_forcing_to_ef5 import convert_precip_units
data_mmhr = convert_precip_units(data_raw, source_unit="mm/3h")
```

### 4. Write to EF5 format

Use consistent file naming with datetime placeholders:
```
precip_YYYYMMDDHH.tif     → FREQ=1h,  NAME=precip_YYYYMMDDHH.tif
precip_YYYYMMDDHHUU.bif   → FREQ=5u,  NAME=precip_YYYYMMDDHHUU.bif
PET_MM.tif                → FREQ=m,   NAME=PET_MM.tif
```

### 5. Configure in control.txt

```ini
[PrecipForcing RAIN]
TYPE=TIF            # ASC, BIF, TIF, TRMMRT, TRMMV7, MRMS
UNIT=mm/h           # Must match what's in the file
FREQ=1h             # Ingestion frequency
LOC=/data/precip    # Directory containing files
NAME=precip_YYYYMMDDHH.tif  # File naming pattern

[PETForcing PET]
TYPE=TIF
UNIT=mm/m           # mm per month (monthly PET)
FREQ=m              # Monthly frequency
LOC=/data/pet
NAME=PET_MM.tif     # MM replaced by month number
```

## Verification

### Quick sanity checks

```python
import numpy as np

# Precipitation (should be mm/hr rate)
precip = read_grid("precip_2009060112.tif")
valid = precip[~np.isnan(precip)]
print(f"Precip: min={valid.min():.2f}, max={valid.max():.2f}, mean={valid.mean():.2f} mm/hr")
# Expected: max < 100 mm/hr for hourly, mean < 5 mm/hr for most climates
assert valid.max() < 500, "Precip too high — likely wrong units"
assert valid.min() >= 0, "Negative precipitation!"

# PET (mm/hr or mm/month depending on UNIT setting)
pet = read_grid("PET_06.tif")
valid_pet = pet[~np.isnan(pet)]
print(f"PET: min={valid_pet.min():.2f}, max={valid_pet.max():.2f} mm/hr")
# If UNIT=mm/h: max should be < 1 mm/hr
# If UNIT=mm/m: max should be < 300 mm/month
```

### File count check

```python
from datetime import datetime, timedelta
start = datetime(2009, 1, 1)
end = datetime(2009, 12, 31)
freq_hours = 1
expected = int((end - start).total_seconds() / 3600 / freq_hours)
actual = len(list(Path("/data/precip").glob("*.tif")))
print(f"Expected: {expected}, Actual: {actual}")
assert actual >= expected * 0.95, "Missing forcing files!"
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| UNIT=mm/h but data is mm/3h | Precip 3x too high, massive floods | Set UNIT=mm/3h or pre-convert to mm/h |
| UNIT=mm/m meant as mm/minute | Precip way too low (÷720 instead of ÷60) | In EF5, m=month, u=minute. Use mm/u or pre-convert |
| PET in mm/day with UNIT=mm/h | PET 24x too high, extreme ET | Set UNIT=mm/d or convert to mm/h before writing |
| PET as temperature with UNIT=mm/h | Model crashes or produces garbage | Use UNIT=C for temperature-based PET |
| ERA5 precip in m/hr | 1000x too low if treated as mm/hr | Multiply by 1000 before writing |
| FREQ doesn't match file availability | Missing timesteps → zero precip | Check FREQ matches actual file interval |
| File naming mismatch | EF5 can't find files, reads as zero | Verify YYYY/MM/DD/HH/UU/SS placeholders match filenames |
| Grid extent doesn't cover basin | NaN precip for edge cells | Ensure precip grid covers entire DEM extent |
| BIF byte order wrong | Garbage values read | BIF is little-endian float32 on all platforms |

## Example

```bash
# Convert CMFD 3-hourly precip (mm/hr) to EF5 format
python tools/convert_forcing_to_ef5.py \
    --precip-dir /data/cmfd/prec/ \
    --pet-dir /data/gleam/pet/ \
    --output-dir /data/ef5_forcing/ \
    --bbox 116.5 32.0 118.5 34.0 \
    --start 20090101 \
    --end 20091231 \
    --precip-unit mm/h \
    --pet-unit mm/d \
    --format tif \
    --freq 3
```
