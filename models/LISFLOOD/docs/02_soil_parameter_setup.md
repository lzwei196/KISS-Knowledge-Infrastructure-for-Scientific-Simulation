# Stage 2: Soil and Land Use Parameter Setup

## Purpose

Generate LISFLOOD soil hydraulic parameter maps from soil databases (HWSD, SoilGrids, or HYPRES pedotransfer functions). LISFLOOD requires Van Genuchten parameters for three soil layers and two land use types (other/forest).

## Inputs

| Input | Source | Format | Notes |
|-------|--------|--------|-------|
| Soil texture | HWSD, SoilGrids | CSV, GeoTIFF | Sand%, clay%, silt%, OM%, bulk density |
| MaskMap | LISFLOOD domain | NetCDF/PCRaster | Spatial extent and resolution |
| Land use maps | CLC, GlobCover | NetCDF/PCRaster | OtherFraction, ForestFraction, IrrigationFraction |

## Outputs

For each soil layer (1=superficial, 2=upper, 3=lower) and land use (standard, Forest):

| Parameter | Variable Name | Unit | Description |
|-----------|--------------|------|-------------|
| Saturated hydraulic conductivity | `MapKSat1`, `MapKSat1Forest`, `MapKSat2`, ... | mm/day | **NOT cm/day or m/s** |
| Pore-size distribution | `MapLambda1`, `MapLambda1Forest`, ... | — | Van Genuchten Lambda = N - 1 |
| Van Genuchten alpha | `MapGenuAlpha1`, `MapGenuAlpha1Forest`, ... | 1/cm | **NOT 1/m** |
| Saturated water content | `MapThetaSat1`, `MapThetaSat1Forest`, ... | m³/m³ | Porosity |
| Residual water content | `MapThetaRes1`, `MapThetaRes1Forest`, ... | m³/m³ | Typically 0.01 |
| Soil layer depth | `SoilDepth1`, `SoilDepth2`, `SoilDepth3` | mm | **NOT m or cm** |

## Procedure

1. **Determine soil texture** per grid cell from database (HWSD or SoilGrids)
2. **Apply HYPRES pedotransfer functions** (Wösten et al. 1999) to convert texture to Van Genuchten parameters:
   - Input: sand%, clay%, silt%, organic matter%, bulk density, topsoil flag
   - Output: ThetaSat, ThetaRes, Alpha [1/cm], N, Lambda, KSat [mm/day]
3. **Distinguish topsoil vs subsoil**: layers 1 and 2 use topsoil PTF; layer 3 uses subsoil PTF
4. **Apply forest correction**: forest soils typically have higher KSat (better structure) and different organic matter content
5. **Set soil depths** in **millimeters**:
   - SoilDepth1 (superficial): typically 50-300 mm
   - SoilDepth2 (upper): typically 300-1500 mm
   - SoilDepth3 (lower): typically 300-1500 mm
6. **Write parameter maps** as NetCDF or PCRaster, matching MaskMap extent
7. **Validate**: compute field capacity and wilting point to verify physical realism

## Verification

- [ ] All KSat values > 0 and < 10000 mm/day
- [ ] Lambda values between 0.01 and 2.0
- [ ] GenuAlpha values between 0.001 and 0.5 (in 1/cm — if >1, probably in 1/m)
- [ ] ThetaSat between 0.3 and 0.65 m³/m³
- [ ] SoilDepth values in mm (50-1500 mm typical, NOT 0.05-1.5)
- [ ] Field capacity > wilting point for all cells
- [ ] No NaN within domain mask
- [ ] Forest parameter maps cover ForestFraction > 0 areas

## Traps

| Trap | Severity | Description |
|------|----------|-------------|
| dt_005 | **silent** | GenuAlpha in 1/m instead of 1/cm — off by 100×, produces wrong field capacity |
| dt_007 | **silent** | SoilDepth in m instead of mm — 1000× error in soil water storage capacity |
| dt_008 | **silent** | KSat in wrong units (cm/day or m/s instead of mm/day) — affects infiltration |
| — | **silent** | Using Brooks-Corey parameters instead of Van Genuchten — different formulation |

## Example

```bash
# Generate uniform loam parameters for a test domain
python tools/convert_soil_params.py \
    --source_type texture_class \
    --texture_class loam \
    --mask_file /path/to/mask.nc \
    --output_dir /path/to/lisflood/maps/ \
    --soil_depths "200,800,1200"

# Verify field capacity
python -c "
import numpy as np
# Van Genuchten: theta(h) = theta_r + (theta_s - theta_r) / (1 + (alpha*h)^n)^m
alpha = 0.036  # 1/cm (loam)
n = 1.56
m = 1 - 1/n
theta_s, theta_r = 0.43, 0.01
h_fc = 100  # cm (pF 2.0)
fc = theta_r + (theta_s - theta_r) / (1 + (alpha*h_fc)**n)**m
print(f'Field capacity: {fc:.3f} m3/m3')
"
```
