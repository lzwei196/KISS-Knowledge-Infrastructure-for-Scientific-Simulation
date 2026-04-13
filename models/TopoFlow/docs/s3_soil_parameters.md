# Stage 3: Soil and Infiltration Parameters

## Purpose

Map soil properties from global databases (HWSD, SoilGrids) to the hydraulic
parameters required by TopoFlow's infiltration components.  Correct unit
conversion is critical — infiltration parameters control the partitioning of
rainfall into runoff vs. subsurface flow.

## Inputs

| Data Source    | Variables                        | Resolution | Units (native)          |
|----------------|----------------------------------|------------|-------------------------|
| HWSD v1.2      | Texture class, OC, bulk density  | 1 km       | Class codes, %, g/cm³   |
| SoilGrids 2.0  | Sand, silt, clay %, Ks, BD, OC   | 250 m      | %, mm/hr, g/cm³, g/kg   |
| SSURGO (US)    | Texture, Ks, porosity, AWC       | varies     | in/hr, %, in/in         |
| Literature     | Rawls et al. (1982) PTF tables   | point      | cm/hr, cm, —            |

## Outputs

Parameters needed depend on the infiltration method selected:

### Green-Ampt (`tf_infil_green_ampt`)

| Parameter | Symbol | Unit (TopoFlow) | Description                    |
|-----------|--------|------------------|--------------------------------|
| Ks_val    | Ks     | **m/s**          | Saturated hydraulic conductivity|
| Ki_val    | Ki     | **m/s**          | Initial hydraulic conductivity  |
| qs_val    | θs     | **—** (0–1)      | Saturated water content         |
| qi_val    | θi     | **—** (0–1)      | Initial water content           |
| G_val     | G      | **m**            | Capillary length scale          |

### Smith-Parlange (`tf_infil_smith_parlange`)

Same as Green-Ampt plus:

| Parameter  | Symbol | Unit   | Description                     |
|------------|--------|--------|---------------------------------|
| gamma_val  | γ      | —      | Interpolation parameter (0–1)   |

### Richards 1-D (`tf_infil_richards_1d`)

| Parameter | Symbol | Unit (TopoFlow) | Description                    |
|-----------|--------|------------------|--------------------------------|
| Ks_val    | Ks     | **m/s**          | Saturated hydraulic conductivity|
| Ki_val    | Ki     | **m/s**          | Initial hydraulic conductivity  |
| qs_val    | θs     | **—** (0–1)      | Saturated water content         |
| qi_val    | θi     | **—** (0–1)      | Initial water content           |
| qr_val    | θr     | **—** (0–1)      | Residual water content          |
| pB_val    | ψb     | **m**            | Bubbling pressure head          |
| lam_val   | λ      | —                | Pore-size distribution index    |
| c_val     | c      | —                | Brooks-Corey c parameter        |

## Procedure

### Step 1: Determine soil texture

From HWSD raster or SoilGrids API, extract the USDA texture class at the study
site.  Use `tools/convert_soil_params.py`:

```bash
python ki/tools/convert_soil_params.py \
  --source hwsd \
  --input_file /path/to/hwsd.bil \
  --lat 41.17 --lon -95.62 \
  --method green_ampt \
  --output_dir ./soil_input/ \
  --site_prefix Treynor
```

### Step 2: Apply pedotransfer functions

The tool uses Rawls et al. (1982) pedotransfer functions to convert texture
class to hydraulic parameters.  Reference values:

| Texture         | Ks (m/s)  | θs    | θr    | G (m)   | ψb (m)  | λ     |
|-----------------|-----------|-------|-------|---------|---------|-------|
| Sand            | 5.83e-5   | 0.395 | 0.020 | 0.050   | 0.121   | 0.694 |
| Loamy Sand      | 1.70e-5   | 0.410 | 0.035 | 0.061   | 0.090   | 0.553 |
| Sandy Loam      | 7.19e-6   | 0.435 | 0.041 | 0.110   | 0.218   | 0.378 |
| Silty Loam      | 3.67e-6   | 0.485 | 0.015 | 0.167   | 0.786   | 0.234 |
| Loam            | 3.67e-6   | 0.451 | 0.027 | 0.089   | 0.478   | 0.252 |
| Sandy Clay Loam | 1.19e-6   | 0.420 | 0.068 | 0.219   | 0.299   | 0.319 |
| Silty Clay Loam | 6.39e-7   | 0.477 | 0.040 | 0.273   | 0.356   | 0.177 |
| Clay Loam       | 6.39e-7   | 0.476 | 0.075 | 0.209   | 0.630   | 0.194 |
| Sandy Clay      | 3.33e-7   | 0.426 | 0.109 | 0.239   | 0.153   | 0.223 |
| Silty Clay      | 2.50e-7   | 0.492 | 0.056 | 0.292   | 0.490   | 0.150 |
| Clay            | 1.67e-7   | 0.482 | 0.090 | 0.316   | 0.405   | 0.165 |

### Step 3: Set initial moisture (θi)

Initial moisture depends on antecedent conditions:
- **Dry:** θi ≈ θr + 0.1 × (θs − θr)
- **Normal:** θi ≈ 0.5 × (θr + θs)  — the default
- **Wet:** θi ≈ θs − 0.1 × (θs − θr)

### Step 4: Write parameters to .cfg

For scalar (uniform) parameters, enter values directly in the .cfg file.
For spatially distributed parameters, create RTG grids.

```
# Example infil_green_ampt.cfg snippet
Ks_type_0       | Scalar          | string | Ks input type
Ks_val_0        | 7.19e-06        | float  | sat. hydraulic conductivity [m/s]
qs_type_0       | Scalar          | string | θs input type
qs_val_0        | 0.435           | float  | sat. soil water content [-]
qi_type_0       | Scalar          | string | θi input type
qi_val_0        | 0.238           | float  | init. soil water content [-]
G_type_0        | Scalar          | string | G input type
G_val_0         | 0.110           | float  | capillary length scale [m]
```

## Verification

1. **Ks magnitude:** Should be 1e-7 to 1e-3 m/s.  Outside this range, check units.
2. **θs range:** Should be 0.30–0.55.  Values > 0.60 or < 0.20 are suspicious.
3. **θi < θs:** Initial moisture must be less than saturation.
4. **G magnitude:** Should be 0.01–0.50 m for most soils.  If > 5 m, likely in cm.
5. **Mass balance:** After running, check infiltration volume ≤ precipitation volume.

## Traps

| Trap                              | Symptom                               | Fix                                |
|-----------------------------------|---------------------------------------|------------------------------------|
| Ks in mm/hr instead of m/s        | Excessive infiltration, no runoff     | Divide by 3.6e6                    |
| Ks in cm/hr instead of m/s        | Same as above                         | Divide by 3.6e5                    |
| G in cm instead of m              | 100× too much infiltration            | Divide by 100                      |
| Porosity as % (0–100) not fraction| θs > 1 causes crash or nonsense       | Divide by 100                      |
| θi > θs                           | Negative storage, numerical instab.   | Set θi = 0.5 × (θr + θs)          |
| Wrong layer count (n_layers)      | Array index mismatch, crash           | Count must match parameter arrays  |
| Using Ks from wrong depth         | Surface Ks ≠ subsoil Ks              | Use topsoil (0–30 cm) values       |

## Example

Treynor, Iowa — silty loam (Marshall silt loam series):
- Ks = 3.67e-6 m/s (silty loam from Rawls table)
- θs = 0.485, θr = 0.015, θi = 0.25 (normal antecedent)
- G = 0.167 m
- Method: Green-Ampt (simplest, appropriate for uniform soils)
