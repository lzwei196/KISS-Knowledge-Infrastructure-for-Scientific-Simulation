# Stage 3: CREST Parameter Preparation

## Purpose

Derive and prepare CREST model parameter grids from global soil and land cover datasets. Parameters can be specified as uniform scalar values (applied to the entire basin) or as distributed grids (spatially varying). When both are specified, the scalar acts as a multiplier on the grid values.

## Inputs

| Input | Format | Unit | Source |
|-------|--------|------|--------|
| HWSD raster | GeoTIFF/ERDAS .img | mapping unit code | FAO Harmonized World Soil Database |
| HWSD_DATA.csv | CSV | various | HWSD lookup table (soil properties) |
| DEM | GeoTIFF/ASC | meters | From Stage 1 |
| Land use | GeoTIFF | class code | GlobCover, MODIS land cover (for IM) |

## Outputs

| Output | Format | Unit | Description |
|--------|--------|------|-------------|
| wm.tif | Float32 GeoTIFF | mm | Maximum soil water capacity |
| b.tif | Float32 GeoTIFF | - | Variable infiltration curve exponent |
| im.tif | Float32 GeoTIFF | % (0-100) | Impervious area ratio |
| fc.tif (ksat) | Float32 GeoTIFF | mm/hr | Saturated hydraulic conductivity |

## CREST Parameters Reference

### Water balance parameters

| Param | Config Key | Unit | Typical Range | Description |
|-------|-----------|------|---------------|-------------|
| WM | wm | mm | 50-500 | Maximum soil water capacity. Controls total soil storage. Derived from Available Water Capacity × soil depth. |
| B | b | - | 0.1-2.0 | Variable infiltration curve exponent. Higher B = more runoff for same soil moisture. Correlated with clay content. |
| IM | im | % | 0-15 | Impervious area ratio. Fraction of grid cell generating direct runoff regardless of soil moisture. Urban areas = high IM. |
| KE | ke | - | 0.1-1.5 | PET-to-AET multiplier. Scales potential ET to actual ET. Usually calibrated, not from soil data. |
| FC | fc | mm/hr | 0.1-50 | Saturated hydraulic conductivity (Ksat). Controls infiltration splitting between overland and interflow. |
| IWU | iwu | % | 0-100 | Initial soil water as percentage of WM. Spin-up sensitive. Set to 50% as default. |

### How scalar + grid parameters interact

In the config file:
```ini
wm=1.5                    # Scalar multiplier
wm_grid=/path/to/wm.tif   # Distributed grid values
```
Internal computation: `WM_effective = scalar × grid_value`

This means:
- If `wm=1.0` and grid has WM=200mm, effective WM=200mm
- If `wm=1.5` and grid has WM=200mm, effective WM=300mm
- The scalar acts as a calibration multiplier

**Important for IM**: If no grid is provided, the scalar value is divided by 100 internally (so `im=5` means 5%, stored as 0.05). If a grid IS provided, the scalar is used as a direct multiplier.

## Procedure

### Step 1: Derive WM from HWSD

```
WM = AWC (mm/m) × soil_depth (m)
```

Where AWC (Available Water Content) comes from HWSD field capacity minus wilting point. Typical values:
- Sand: 50-100 mm/m
- Loam: 150-250 mm/m
- Clay: 100-200 mm/m

### Step 2: Derive FC (Ksat) from texture class

Map USDA soil texture classes to Ksat (Rawls et al., 1982):

| Texture | Ksat (mm/hr) |
|---------|-------------|
| Clay | 0.6 |
| Silty clay | 0.9 |
| Clay loam | 2.3 |
| Loam | 13.2 |
| Sandy loam | 25.9 |
| Sand | 120.4 |

### Step 3: Derive B from clay content

Empirical relationship: `B = 0.0145 × clay% + 0.14`

### Step 4: Derive IM from land use

- Forest: 0-2%
- Agriculture: 1-5%
- Urban: 20-80%
- Water: 100%

### Step 5: Generate grids

```bash
python convert_params_to_ef5.py \
    --hwsd-raster /data/soil/HWSD_China_Geo.img \
    --hwsd-csv /data/soil/HWSD_DATA.csv \
    --dem /data/bengbu/DEM.tif \
    --output-dir /data/bengbu/params/
```

Or generate uniform defaults:
```bash
python convert_params_to_ef5.py \
    --dem /data/bengbu/DEM.tif \
    --output-dir /data/bengbu/params/ \
    --default-wm 200 --default-fc 10 --default-im 2 --default-b 0.5
```

## Verification

1. **Value range check**: Verify parameters are within physically meaningful ranges
2. **Spatial patterns**: WM and FC should correlate with soil texture patterns
3. **Grid alignment**: Parameter grids should cover the DEM extent
4. **Nodata masking**: Nodata should be consistent with DEM

```python
from osgeo import gdal
for param in ["wm", "fc", "im", "b"]:
    ds = gdal.Open(f"params/{param}.tif")
    data = ds.GetRasterBand(1).ReadAsArray()
    valid = data[data != -9999]
    print(f"{param}: min={valid.min():.2f}, max={valid.max():.2f}, mean={valid.mean():.2f}")
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| WM in meters not mm | Near-zero soil storage, all runoff | Multiply by 1000 |
| IM as fraction (0-1) not percent (0-100) | Almost no impervious runoff | Multiply by 100 when no grid; check IM handling |
| FC in mm/day not mm/hr | 24× wrong interflow splitting | Divide by 24 |
| FC in m/s not mm/hr | Ksat millions too large | Multiply by 3.6e6 |
| Scalar multiplier misunderstanding | Parameters doubled or halved | Remember: scalar × grid = effective; set scalar=1.0 for grid-only |
| Zero values in param grid | EF5 replaces zeros with 0.01 | Clean data before: set nodata for missing, not zero |
| B = 0 | Division by zero in VIC curve | Minimum B should be ~0.05 |
| IWU > 100% | SM exceeds WM at initialization | Clamp IWU to [0, 100] |

## Example

```ini
[CrestParamSet bengbu]
wm_grid=/data/bengbu/params/wm.tif
im_grid=/data/bengbu/params/im.tif
fc_grid=/data/bengbu/params/fc.tif
b_grid=/data/bengbu/params/b.tif
GAUGE=outlet
wm=1.0       # Scalar multiplier (1.0 = use grid values directly)
b=1.0
im=1.0
ke=0.8       # Calibrated PET multiplier
fc=1.0
iwu=50.0     # 50% initial soil moisture
```
