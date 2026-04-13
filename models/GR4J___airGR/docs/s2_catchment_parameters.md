# Stage 2: Catchment Parameter Extraction

## Purpose

Extract physical catchment properties needed by GR4J and its support functions. GR4J itself is a lumped model with only 4 free parameters (calibrated, not from physical data), but the workflow requires catchment area (for discharge unit conversion) and optionally hypsometry (for CemaNeige snow module).

## Inputs

| Input | Source | Format | Unit |
|-------|--------|--------|------|
| Catchment boundary | Shapefile or coordinates | SHP/GeoJSON | degrees |
| DEM | SRTM, MERIT | GeoTIFF/NetCDF | m |
| HWSD soil data (optional) | HWSD v1.2 | Raster | various |
| Catchment area | Manual or computed | Scalar | km2 |
| Centroid coordinates | Manual or computed | Scalar | degrees |

## Outputs

| Output | Format | Content |
|--------|--------|---------|
| Catchment params JSON | JSON | area_km2, latitude, longitude, hypsometry, conversion_factors |

## Procedure

### Step 1: Determine catchment area
- From shapefile: compute area using equal-area projection
- From coordinates: rough estimate from bounding box
- **TRAP (UT-006)**: Area must be in km2, NOT m2. Off by 1e6 causes Qmm conversion error.
- Typical check: area should be 1-1,000,000 km2

### Step 2: Determine catchment centroid
- Compute from shapefile boundary
- Or use gauge station coordinates as approximation
- Latitude is needed for PE_Oudin computation

### Step 3: Extract hypsometric curve (optional, for CemaNeige)
- Clip DEM to catchment boundary
- Compute 101-point percentile curve (0%, 1%, ..., 100%)
- HypsoData must have exactly 101 values for airGR
- Values must be ascending (min elevation to max elevation)
- ZInputs (median elevation) = HypsoData[51]

### Step 4: Compute discharge conversion factors
- Q_m3s_to_mmday = 86.4 / area_km2
- Q_ls_to_mmday = 0.0864 / area_km2
- Store these for use in Stage 1 and Stage 5

### Step 5: Extract soil properties (informational)
- HWSD provides soil texture, organic carbon, AWC
- GR4J does NOT use soil parameters directly
- But X1 (production store) correlates with available water capacity
- And X3 (routing store) correlates with aquifer storage

## Verification

1. **Area range**: Reasonable for the target catchment (check against literature)
2. **Latitude**: Should match the known location of the catchment
3. **Hypsometry**: Must be monotonically ascending, 101 values, no NaN
4. **Conversion factors**: Q_m3s_to_mmday * area = 86.4 (sanity check)

## Traps

| ID | Trap | Silent? | Detection |
|----|------|---------|-----------|
| UT-006 | Area in m2 instead of km2 | Yes | Conversion factor off by 1e6 |
| HYP-001 | Hypsometry descending | Error | airGR DataAltiExtrapolation fails |
| HYP-002 | Hypsometry not 101 values | Error | airGR raises stop() |

## Example

```python
from tools.convert_catchment_params import build_catchment_params

result = build_catchment_params(
    area_km2=121330,
    latitude=32.95,
    longitude=117.38,
    elevation_mean=50.0,
    catchment_name="Bengbu (Huai River)",
    output_json="catchment_params.json",
)
# result["conversion_factors"]["Q_m3s_to_mmday"] ≈ 0.000712
```

## Key Relationships

| Physical Property | Related GR4J Parameter | Relationship |
|-------------------|----------------------|--------------|
| Soil AWC (mm) | X1 (production store) | Positive correlation — deeper soils ≈ higher X1 |
| Aquifer storage | X3 (routing store) | Positive correlation — larger aquifer ≈ higher X3 |
| Basin lag time | X4 (UH time constant) | Positive correlation — larger basins ≈ higher X4 |
| Geology (karst) | X2 (exchange coeff.) | Karst = negative X2 (water loss to groundwater) |
