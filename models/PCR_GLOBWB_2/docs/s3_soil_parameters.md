# Stage 3: Soil and Parameter Setup

## Purpose

Prepare soil hydraulic properties, topographic parameters, and groundwater properties for PCR-GLOBWB 2. Convert raw soil databases (HWSD, SoilGrids) to the model's expected NetCDF parameter format.

## Inputs

| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| Soil texture | NetCDF/Shapefile | HWSD v1.2 / SoilGrids | Sand/clay/silt percentages |
| Topography | NetCDF | GTOPO30 / MERIT DEM | Elevation, slope |
| Aquifer properties | NetCDF | de Graaf et al. | Thickness, conductivity |

## Outputs

| Output | Format | Variables | Unit |
|--------|--------|-----------|------|
| soilPropertiesNC | NetCDF | saturatedConductivity, porosity, matricSuction | m/day, m3/m3, m |
| topographyNC | NetCDF | tanslope, slopeLength, orographyBeta | -, m, - |
| groundwaterPropertiesNC | NetCDF | specificYield, kSatAquifer, recessionCoeff | m3/m3, m/day, day-1 |

## Procedure

### Soil Properties

1. **Obtain HWSD or SoilGrids data** for the study area
2. **Apply pedotransfer functions** (Cosby et al., 1984):
   - Ksat: `log10(Ksat) = -0.60 + 0.0126*sand - 0.0064*clay` (inches/hr → m/day)
   - Porosity: `porosity = 0.489 - 0.00126*sand`
   - Matric suction: `log10(psi) = 1.54 - 0.0095*sand + 0.0063*silt` (cm → m)
3. **Validate ranges** (dt_004, dt_007):
   - Ksat: 0.001 to 50 m/day
   - Porosity: 0.1 to 0.8 (fraction, NOT percentage)
   - All values must be in **meters**, not millimeters

### Soil Layer Configuration

PCR-GLOBWB supports 2 or 3 soil layers:

**2-layer mode** (`numberOfUpperSoilLayers = 2`):
- Upper soil (storUpp): variable depth based on root zone
- Lower soil (storLow): extends to bedrock

**3-layer mode** (`numberOfUpperSoilLayers = 3`):
- Layer 1: 0-5 cm (storUpp000005)
- Layer 2: 5-30 cm (storUpp005030)
- Layer 3: 30-150 cm (storLow030150)

### Topography Parameters

- `tanslope`: tangent of slope angle (dimensionless, typically 0-1)
- `slopeLength`: hillslope length for interflow calculation (m)
- `orographyBeta`: orographic precipitation correction factor

### Groundwater Properties

- `specificYield`: must be fraction 0-1, NOT percentage (dt_007)
- `kSatAquifer`: must be m/day, NOT cm/hr (dt_008)
- `recessionCoeff`: baseflow recession coefficient (day-1)

## Verification

- [ ] Ksat values in range 0.001-50 m/day
- [ ] Porosity values in range 0.1-0.8 (fraction)
- [ ] Specific yield < 1.0 (fraction, not percentage)
- [ ] kSatAquifer < 500 m/day (check units)
- [ ] No negative values in any parameter
- [ ] Spatial coverage matches clone map

## Traps

| Trap ID | Symptom | Root Cause | Fix |
|---------|---------|-----------|-----|
| dt_004 | Soil saturates instantly | Soil capacity in mm instead of m | Divide by 1000 |
| dt_007 | Unrealistic groundwater | Specific yield in % instead of fraction | Divide by 100 |
| dt_008 | Fast/slow baseflow | kSat in cm/hr instead of m/day | Multiply by 0.24 |

## Example

```python
from tools.convert_soil_params import convert_hwsd_to_pcrglobwb

# Convert HWSD topsoil data
convert_hwsd_to_pcrglobwb(
    input_nc="hwsd_v1.2_global.nc",
    output_nc="soilProperties_upper.nc",
    layer="upper"
)

# Convert HWSD subsoil data
convert_hwsd_to_pcrglobwb(
    input_nc="hwsd_v1.2_global.nc",
    output_nc="soilProperties_lower.nc",
    layer="lower"
)
```

### PCR-GLOBWB Default Parameter Files (from 4TU OPeNDAP)

```
global_05min/landSurface/soil/soilProperties5ArcMin.nc
global_05min/landSurface/topography/topography_parameters_5_arcmin_october_2015.nc
global_05min/groundwater/properties/groundwaterProperties5ArcMin.nc
```

These pre-processed files can be used directly without conversion by setting `inputDir` to the OPeNDAP server URL.
