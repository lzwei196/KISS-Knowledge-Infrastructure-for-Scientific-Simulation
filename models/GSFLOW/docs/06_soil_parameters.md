# Stage 2: Soil Parameters

## Purpose
Derive GSFLOW/PRMS soil hydraulic parameters from the Harmonized World Soil
Database (HWSD) or SoilGrids data for each HRU in the model domain.

## Inputs
- HWSD raster: `KISSPATH_STATIC/HWSD_China_Geo.img`
  (or SoilGrids: `KISSPATH_HOME/Crop_model_dataset/SoilGrids_Bengbu/`)
- Basin/HRU shapefile
- Number of HRUs

## Outputs
- PRMS parameter file (`soil.params`) containing:
  - `soil_type`: soil type index (1=sand, 2=loam, 3=clay)
  - `soil_moist_max`: maximum available soil moisture (inches)
  - `soil_rechr_max`: maximum recharge zone capacity (inches)
  - `sat_threshold`: saturated threshold (inches)
  - `ssr2gw_rate`: subsurface→groundwater rate (fraction/day)
  - `slowcoef_lin`: linear interflow coefficient
  - `fastcoef_lin`: fast interflow coefficient
  - `soil2gw_max`: maximum soil→GW percolation (inches)

## Procedure

1. **Extract soil texture from HWSD:**
   - Clip HWSD raster to basin boundary
   - Identify dominant texture class per HRU
   - HWSD provides 12 USDA texture classes

2. **Map texture to hydraulic properties:**
   - Use Rawls et al. (1982) or Saxton & Rawls (2006) pedotransfer functions
   - Key properties: porosity, field capacity, wilting point, Ksat

3. **Calculate PRMS parameters:**
   - `soil_moist_max = (FC - WP) × depth` → **convert mm to inches** (÷25.4)
   - `soil_rechr_max = (FC - WP) × recharge_depth` → inches
   - `ssr2gw_rate = f(Ksat)` → typically Ksat/500, capped at 0.8
   - `soil_type`: 1=sand(Ksat>15mm/hr), 2=loam(1.5–15), 3=clay(<1.5)

4. **Write parameter file:**
   - Use PRMS parameter format with `####` delimiters
   - Dimensions: `nhru`, `nssr`
   - Data types: 1 for integers, 2 for floats

## Verification
- `soil_moist_max` range: 0.5–30 inches (12–760 mm)
- `soil_rechr_max` ≤ `soil_moist_max`
- `soil_type` values are 1, 2, or 3 only
- `ssr2gw_rate` range: 0.0001–0.8
- Parameter count = nhru for each parameter

## Traps
- **MM to INCHES:** HWSD soil depths and properties are in metric (mm, mm/hr).
  PRMS parameters must be in INCHES. Forgetting conversion → 25× too much
  soil capacity → all precipitation stored in soil → no streamflow.
- **Depth assumption:** HWSD provides surface soil properties. Assumed depth
  (typically 1000–1500mm) significantly affects `soil_moist_max`.
- **Spatial mismatch:** HWSD resolution (~1km) is much finer than typical
  HRU resolution. Use area-dominant class, not point sampling.
- **NoData pixels:** HWSD may have NoData over water bodies or rock outcrops.
  Default these to loam or sand, not zero.
- **Parameter coupling:** `soil_moist_max` and `soil_rechr_max` must be
  physically consistent: rechr ≤ total capacity.

## Example
```bash
python convert_soil_params.py \
    --hwsd KISSPATH_STATIC/HWSD_China_Geo.img \
    --shapefile KISSPATH_DATA/shp/bengbu_shp/bengbu_clip.shp \
    --output ./input/prms/soil.params \
    --n-hru 1
```
