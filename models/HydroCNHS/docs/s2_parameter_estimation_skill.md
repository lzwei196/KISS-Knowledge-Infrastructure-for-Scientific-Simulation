# S2: Parameter Estimation

## Purpose

Generate initial estimates for GWLF or ABCD rainfall-runoff model parameters
from soil properties, land-use data, and basin characteristics. These estimates
serve as starting points for calibration — they are rarely accurate enough for
direct simulation.

## Inputs

| Input | Format | Unit | Source |
|-------|--------|------|--------|
| Hydrologic soil group | A/B/C/D | categorical | SSURGO, HWSD |
| Land-use type | category | categorical | NLCD, CORINE, GlobCover |
| Subbasin area | numeric | ha | GIS delineation |
| Elevation | numeric | m | DEM |
| Soil depth | numeric | cm | SSURGO, HWSD |

## Outputs

| Output | Format | Unit | Destination |
|--------|--------|------|-------------|
| GWLF parameters (9 per subbasin) | dict/YAML | mixed (see table) | model.yaml |
| ABCD parameters (5 per subbasin) | dict/YAML | mixed (see table) | model.yaml |

### GWLF Parameter Table

| Parameter | Symbol | Unit | Range | How to estimate |
|-----------|--------|------|-------|-----------------|
| Curve Number | CN2 | — | [25, 100] | SCS tables: soil group × land use |
| Interception | IS | — | [0, 0.5] | 0.2 for forest, 0.05 for urban |
| Recession | Res | — | [0.001, 0.5] | Higher for clay soils (group D) |
| Deep Seepage | Sep | — | [0, 0.5] | Usually small (0.01–0.05) |
| Baseflow | Alpha | — | [0, 1] | Higher for sandy soils (group A) |
| Percolation | Beta | — | [0, 1] | Start at 0.5 |
| Soil Water | Ur | **cm** | [1, 15] | AWC × root depth (cm) |
| Snowmelt | Df | **cm/°C** | [0, 1] | 0.3–0.5 typical |
| Land Cover | Kc | — | [0.5, 1.5] | 1.15 forest, 0.7 urban |

## Procedure

1. **Determine hydrologic soil group** — Use SSURGO (US) or HWSD (global).
   Group A = sandy, high infiltration. Group D = clay, low infiltration.

2. **Classify land use** — Map local land-use classes to: forest, grassland,
   cropland, urban_low, urban_high, water, wetland, barren.

3. **Look up CN2** — Use SCS TR-55 tables. CN2 is the single most sensitive
   parameter; getting it roughly right saves calibration effort.

4. **Estimate Ur** — Available water capacity (cm) = AWC (cm/cm) × root depth (cm).
   **CRITICAL**: Ur is in cm, not mm. HWSD often reports AWC in mm — divide by 10.

5. **Set initial values** for remaining parameters from lookup tables or
   literature values. These will be refined by calibration.

6. **Mark parameters for calibration** — Set to -99 in model.yaml. Generate
   bounds using `hydrocnhs.gen_default_bounds()`.

## Verification

```python
# Check all parameters are in valid ranges
params = {"CN2": 72, "IS": 0.1, "Res": 0.1, "Sep": 0.01,
          "Alpha": 0.6, "Beta": 0.5, "Ur": 8.0, "Df": 0.3, "Kc": 1.0}

ranges = {"CN2": (25, 100), "IS": (0, 0.5), "Res": (0.001, 0.5),
          "Sep": (0, 0.5), "Alpha": (0, 1), "Beta": (0, 1),
          "Ur": (1, 15), "Df": (0, 1), "Kc": (0.5, 1.5)}

for k, (lo, hi) in ranges.items():
    assert lo <= params[k] <= hi, f"{k}={params[k]} out of range [{lo}, {hi}]"
    print(f"  {k}: {params[k]} ✓")
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| dt_005: Area in km² not ha | Discharge 100× too low | Multiply by 100 |
| dt_009: Ur in mm not cm | Soil never saturates, no runoff | Divide by 10 |
| dt_010: Df in mm/°C not cm/°C | Excessive snowmelt | Divide by 10 |

## Example

```python
from convert_parameters import estimate_gwlf_params

# Tualatin River Basin, Oregon — mixed forest/agricultural
params = estimate_gwlf_params(
    outlet="WSLO",
    soil_group="B",
    land_use="grassland",
    latitude=45.35,
    elevation_m=200
)
# Result: CN2=69, IS=0.10, Res=0.10, Sep=0.01, Alpha=0.60,
#         Beta=0.50, Ur=15.0, Df=0.46, Kc=0.95
```
