# Stage 2: Parameter File Preparation

## Purpose

Convert basin physical properties (DEM-derived attributes, soil data, land use) into a PRMS parameter file with correct units and structure.

## Inputs

| Data Source | Variables | Native Units |
|-------------|-----------|-------------|
| DEM analysis | elevation, slope, aspect, area | meters, degrees, km2 |
| HWSD/SOILGRIDS | clay%, sand%, depth, Ksat | %, mm, mm/hr |
| Land use map | cover type, imperv fraction | categorical, fraction |
| GIS analysis | latitude, longitude | decimal degrees |

## Outputs

- PRMS parameter file (`prms.params`) with dimensions and parameters
- All values in PRMS internal units (acres, feet, inches, Fahrenheit)

## Procedure

### Step 1: Read HRU attributes

```python
from tools.convert_params_to_prms import read_hru_data
hru_df = read_hru_data("hrus.csv")
```

Required columns: `area_km2`, `elev_m`, `lat`
Optional: `lon`, `slope_deg`, `aspect_deg`, `cov_type`, `imperv_frac`

### Step 2: Apply unit conversions

**CRITICAL conversions:**

| Parameter | Source Unit | PRMS Unit | Formula |
|-----------|-----------|-----------|---------|
| hru_area | km2 | acres | `acres = km2 * 247.105` |
| hru_area | m2 | acres | `acres = m2 / 4046.86` |
| hru_elev | meters | feet | `ft = m * 3.28084` (if elev_units=0) |
| soil_moist_max | mm | inches | `in = mm / 25.4` |
| soil_rechr_max | mm | inches | `in = mm / 25.4` |
| slope | degrees | decimal fraction | `frac = tan(radians(deg))` |

### Step 3: Derive soil parameters

From HWSD texture data:
- **soil_type**: 1=sand (sand>65%), 2=loam (default), 3=clay (clay>35%)
- **soil_moist_max**: depth_mm * AWC / 25.4 (AWC ~ 0.08-0.20 depending on texture)
- **soil_rechr_max**: soil_moist_max * 0.5 (recharge zone is ~50% of total)

### Step 4: Set calibration parameters to defaults

| Parameter | Default | Description |
|-----------|---------|-------------|
| gwflow_coef | 0.015 | GW linear flow coefficient |
| slowcoef_lin | 0.015 | Interflow coefficient |
| fastcoef_lin | 0.09 | Preferential flow coefficient |
| ssr2gw_rate | 0.1 | Subsurface to GW rate |
| smidx_coef | 0.005 | Surface runoff coefficient |
| smidx_exp | 0.3 | Surface runoff exponent |

### Step 5: Write parameter file

```python
from tools.convert_params_to_prms import write_parameter_file
write_parameter_file("prms.params", params, nhru=42, nsegment=15)
```

## Verification

- [ ] hru_area values > 1 acre (if < 1, likely km2 not converted)
- [ ] hru_elev reasonable for region (if < 100 ft, likely meters not converted)
- [ ] soil_moist_max between 1-20 inches (if > 100, likely mm not converted)
- [ ] soil_rechr_max < soil_moist_max for all HRUs
- [ ] hru_lat in correct hemisphere
- [ ] sum(hru_area) approximately equals basin area
- [ ] Parameter file dimensions match data file dimensions

## Traps

### 1. Area in km2 instead of acres

1 km2 = 247.105 acres. If you use km2 directly, water balance volumes are ~247x too small. The model runs but flow is wrong.

### 2. Elevation in meters with elev_units=0 (feet expected)

Temperature lapse rate corrections use elevation differences. If elevations are in meters but PRMS thinks feet, lapse adjustments are 3.28x too small → temperature field is nearly flat.

### 3. Soil depth in mm instead of inches

soil_moist_max in mm instead of inches → 25.4x too large → soil never reaches saturation → no surface runoff → dramatically underestimated peak flows.

### 4. Dimension mismatch

If the parameter file declares `nhru = 42` but only provides 40 values for hru_area, PRMS crashes at startup. Always verify dimensions match.

### 5. Missing snow depletion curve

The `snarea_curve` parameter (11 values for `ndeplval`) is required. Forgetting it causes a runtime error in the snow module.

## Example

```bash
python tools/convert_params_to_prms.py \
    --hru_file /data/sagehen/hrus.csv \
    --soil_file /data/sagehen/soil_hwsd.csv \
    --output_file /prms/input/prms.params \
    --elev_units 0 \
    --nsegment 15 \
    --nobs 1
```

Output:
```
[convert] hru_area: 0.5-12.3 km2 -> 123.6-3039.4 acres
[convert] hru_elev: 1920-2680 m -> 6299-8793 ft
[write] Parameter file: /prms/input/prms.params
[write] 42 HRUs, 35 parameters
All checks passed.
```
