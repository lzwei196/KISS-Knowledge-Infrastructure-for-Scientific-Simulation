# Stage 2: Soil Parameter Assignment

## Purpose

Assign geotechnical and hydraulic soil properties to TRIGRS property zones. Each zone represents a distinct soil/geological unit with uniform properties. Properties control both the infiltration model (hydraulic conductivity, diffusivity, water retention) and the slope stability model (cohesion, friction angle, unit weight).

## Inputs

| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| HWSD database | Raster / CSV | FAO/IIASA | Harmonized World Soil Database |
| SoilGrids | GeoTIFF | ISRIC | Global soil property predictions |
| Geological map | Shapefile | Local survey | Bedrock/surficial geology |
| Field data | CSV/table | Site investigation | Lab-measured properties |
| zones.asc | ESRI ASCII grid | Stage 1 | Integer zone assignment grid |

## Outputs

| Output | Format | Unit | Description |
|--------|--------|------|-------------|
| zones.asc | ESRI ASCII grid | integer | Property zone grid |
| Zone blocks | Text (for tr_in.txt) | mixed | Per-zone parameter lines |

### Zone parameter units (CRITICAL)

| Parameter | Symbol | TRIGRS unit | Common alternative | Conversion |
|-----------|--------|------------|-------------------|------------|
| Cohesion | c | **Pa** | kPa | multiply by 1000 |
| Friction angle | phi | **degrees** | (usually correct) | -- |
| Unit weight soil | uws | **N/m^3** | kN/m^3 | multiply by 1000 |
| Diffusivity | D0 | **m^2/s** | cm^2/s | multiply by 1e-4 |
| K-sat | Ks | **m/s** | cm/hr | multiply by 2.778e-6 |
| Theta-sat | ths | fraction | (usually correct) | -- |
| Theta-res | thr | fraction | (usually correct) | -- |
| Alpha | alpha | **1/m** | 1/cm | multiply by 100 |

## Procedure

1. **Classify study area into zones**
   - Group by soil type, geology, land cover, or depth
   - Create integer zone grid matching DEM dimensions
   - Typical projects use 1-5 zones

2. **Assign properties per zone**
   - Use pedotransfer functions for regional studies (HWSD -> geotechnical)
   - Use lab test data for site-specific studies
   - Literature values as initial estimates for calibration

3. **Convert all units to TRIGRS requirements**
   - This is the #1 source of errors (see unit table above)
   - Use `convert_soil_to_trigrs.py` for automated conversion

4. **Select saturated vs unsaturated model**
   - Saturated model: set Alpha to **negative** value (e.g., -0.5)
   - Unsaturated model: set Alpha to **positive** value AND provide valid Theta-sat, Theta-res
   - Mixed: different zones can use different models

5. **Validate property ranges**
   - All properties must be physically reasonable
   - See bounds table below

### Physical bounds

| Parameter | Minimum | Maximum | Notes |
|-----------|---------|---------|-------|
| Cohesion (Pa) | 0 | 100,000 | 0 for clean sand, >50kPa for stiff clay |
| Phi (degrees) | 15 | 45 | 15 for soft clay, 40+ for gravel |
| uws (N/m^3) | 14,000 | 25,000 | 18,000-22,000 typical |
| D0 (m^2/s) | 1e-8 | 1.0 | D0 = Ks * zmax / (Ks/alpha) approximately |
| Ks (m/s) | 1e-10 | 1e-2 | 1e-8 clay, 1e-4 sand |
| Theta-sat | 0.2 | 0.7 | Porosity |
| Theta-res | 0.01 | 0.3 | Must be < Theta-sat |
| Alpha (1/m) | 0.1 | 100 | Negative = use saturated model |

## Verification

```bash
# Run the soil converter tool
python convert_soil_to_trigrs.py \
    --soil_data soil_properties.csv \
    --dem dem.asc \
    --output_zones zones.asc \
    --output_params soil_params.txt \
    --cohesion_unit kpa \
    --uws_unit kn/m3

# Verify zone grid
python3 -c "
import numpy as np
z = np.loadtxt('zones.asc', skiprows=6)
print(f'Zone values: {sorted(set(z[z!=-9999].astype(int).flat))}')
"
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Cohesion in kPa instead of Pa | FS unrealistically high (~1000x) | Multiply by 1000 |
| uws in kN/m^3 instead of N/m^3 | FS scaled incorrectly | Multiply by 1000 |
| Ks in cm/hr instead of m/s | Infiltration timing completely wrong | Multiply by 2.778e-6 |
| Alpha negative (unintended) | Saturated model used when unsaturated intended | Use positive Alpha |
| D0 too large | Pressure wave arrives instantly | Check D0 = Ks * thickness / specific storage |
| Theta-sat < Theta-res | TRIGRS may crash or give NaN | Ensure Theta-sat > Theta-res |

## Example

```
# tr_in.txt zone block for colluvium (Zone 1)
zone, 1
cohesion,phi,  uws,   diffus,   K-sat, Theta-sat,Theta-res,Alpha
3.5e+03, 35., 2.2e+04,  6.0e-06, 1.0e-07,   0.45,    0.05,    -0.5

# Explanation of values:
# cohesion = 3500 Pa (3.5 kPa) -- typical for weathered colluvium
# phi = 35 degrees -- typical for granular colluvium
# uws = 22000 N/m^3 (22 kN/m^3) -- dense colluvium
# diffus = 6e-6 m^2/s -- moderate
# K-sat = 1e-7 m/s -- low permeability
# Theta-sat = 0.45 -- typical porosity
# Theta-res = 0.05 -- low residual
# Alpha = -0.5 -- NEGATIVE means saturated model is used
```
