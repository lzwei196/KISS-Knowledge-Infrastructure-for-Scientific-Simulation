# Stage 3: Vegetation / Land Cover

## Purpose
Classify land cover from satellite data (AVHRR, MODIS) into GSFLOW/PRMS
vegetation types and derive vegetation-related parameters for each HRU.

## Inputs
- Land cover raster: `AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif`
- Basin/HRU shapefile
- Vegetation type mapping table

## Outputs
- PRMS parameter file (`veg.params`) containing:
  - `cov_type`: cover type (0=bare, 1=grasses, 2=shrubs, 3=trees, 4=coniferous)
  - `covden_sum`: summer cover density (0–1)
  - `covden_win`: winter cover density (0–1)
  - `snow_intcp`: snow interception capacity (inches)
  - `srain_intcp`: summer rain interception capacity (inches)
  - `wrain_intcp`: winter rain interception capacity (inches)
  - `rad_trncf`: radiation transmission coefficient (0–1)
  - `jh_coef_hru`: Jensen-Haise coefficient by HRU

## Procedure

1. **Extract land cover:**
   - Clip AVHRR or MODIS raster to basin
   - Identify dominant land cover class per HRU

2. **Map to PRMS cover types:**

   | AVHRR Class | Description | PRMS cov_type |
   |-------------|-------------|---------------|
   | 1 | Evergreen Needleleaf | 4 |
   | 2 | Evergreen Broadleaf | 3 |
   | 3 | Deciduous Needleleaf | 4 |
   | 4 | Deciduous Broadleaf | 3 |
   | 5 | Mixed Forest | 3 |
   | 6 | Woodland | 3 |
   | 7 | Wooded Grassland | 2 |
   | 8 | Closed Shrubland | 2 |
   | 9 | Open Shrubland | 2 |
   | 10 | Grassland | 1 |
   | 11 | Cropland | 1 |
   | 12 | Bare Ground | 0 |
   | 13 | Urban | 0 |
   | 14 | Water | 0 |

3. **Assign vegetation parameters** based on cover type:
   - Trees (3,4): covden_sum=0.7, covden_win=0.3, snow_intcp=0.1 in
   - Shrubs (2): covden_sum=0.4, covden_win=0.2, snow_intcp=0.06 in
   - Grasses (1): covden_sum=0.5, covden_win=0.1, snow_intcp=0.02 in
   - Bare (0): covden_sum=0.0, covden_win=0.0, snow_intcp=0.0

4. **Set impervious fraction:**
   - Urban areas: `hru_percent_imperv = 0.3–0.8`
   - Other: `hru_percent_imperv = 0.0–0.05`

## Verification
- `cov_type` values are 0–4
- `covden_sum` ≥ `covden_win` (summer always ≥ winter density)
- Interception capacities > 0 for vegetated HRUs
- No NoData or -9999 values in parameter arrays

## Traps
- **Interception units:** PRMS interception is in INCHES, not mm.
  Typical values: 0.01–0.15 inches. If values are > 1.0, likely still in mm.
- **Cover density range:** Must be 0.0–1.0. Values > 1.0 cause ET errors.
- **Urban HRUs:** Need both `hru_percent_imperv` AND `imperv_stor_max` set.
  High impervious fraction without proper storage → extreme peak flows.
- **rad_trncf:** For bare ground should be 1.0 (full transmission).
  For dense forest: 0.3–0.5. Affects snowmelt calculations.

## Example
```python
import rasterio
import geopandas as gpd
from rasterio.mask import mask

basin = gpd.read_file("basin.shp")
with rasterio.open("AVHRR_1km_LANDCOVER.tif") as src:
    clipped, transform = mask(src, basin.geometry, crop=True)
    dominant_class = np.argmax(np.bincount(clipped[clipped > 0]))
```
