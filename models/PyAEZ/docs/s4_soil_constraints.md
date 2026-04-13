# S4: Soil Constraints (Module IV) Skill Document

## Purpose

Evaluate soil suitability for crop growth using seven soil quality indicators (SQ1–SQ7)
derived from the Harmonized World Soil Database (HWSD). Each indicator assesses a
different aspect of soil quality, and the combined result produces fc4, the soil
constraint reduction factor applied to the climate-adjusted yield.

## Inputs

| Variable | Type | Format | Unit | Source |
|----------|------|--------|------|--------|
| `clim_yield_rain` | NumPy | (H,W) | kg/ha | Module III |
| `clim_yield_irr` | NumPy | (H,W) | kg/ha | Module III |
| `soil_map` | NumPy | (H,W) | int SMU codes | GeoTIFF |
| Soil params (rain) | Excel | .xlsx | — | convert_soil.py |
| Soil params (irr) | Excel | .xlsx | — | convert_soil.py |
| Topsoil characteristics | Excel | .xlsx | various | HWSD |
| Subsoil characteristics | Excel | .xlsx | various | HWSD |

### Seven Soil Qualities (SQ1–SQ7)

| SQ | Name | Key Variables | Unit |
|----|------|--------------|------|
| SQ1 | Nutrient Availability | Texture, OC (%), pH, TEB (cmol/kg) | — |
| SQ2 | Nutrient Retention | BS (%), CEC soil/clay (cmol/kg) | — |
| SQ3 | Rooting Conditions | Ref depth (cm), rockiness (%), soil phase | — |
| SQ4 | Oxygen/Drainage | Drainage class, soil phase | — |
| SQ5 | Salinity/Sodicity | ESP (%), EC (dS/m) | — |
| SQ6 | Calcareousness | CaCO3 (%), gypsum (%) | — |
| SQ7 | Workability | Gravel (%), texture, steep phase | — |

## Outputs

| Variable | Shape | Unit | Description |
|----------|-------|------|-------------|
| `soil_yield_rain` | (H,W) | kg/ha | Soil-constrained rainfed yield |
| `soil_yield_irr` | (H,W) | kg/ha | Soil-constrained irrigated yield |
| `fc4_rain` | (H,W) | 0–1 | Soil constraint factor (rainfed) |
| `fc4_irr` | (H,W) | 0–1 | Soil constraint factor (irrigated) |
| SQ ratings | per SMU | 0–100 | Individual SQ scores |

## Procedure

### Step 1: Initialize
```python
from pyaez import SoilConstraints
sc = SoilConstraints.SoilConstraints()
```

### Step 2: Import reduction factor tables
```python
sc.importSoilReductionSheet(
    rain_sheet_path='maiz_soil_params_rain.xlsx',
    irr_sheet_path='maiz_soil_params_irr.xlsx')
```

### Step 3: Calculate soil qualities
```python
sc.calculateSoilQualities(
    irr_or_rain='R',  # 'R' for rainfed, 'I' for irrigated
    topsoil_path='maiz_soil_characteristics_topsoil.xlsx',
    subsoil_path='maiz_soil_characteristics_subsoil.xlsx')
```

### Step 4: Calculate soil ratings
```python
sc.calculateSoilRatings(input_level='H')  # 'L', 'I', or 'H' detail level
```

### Step 5: Apply to yield map
```python
soil_yield = sc.applySoilConstraints(soil_map, clim_yield_rain)
fc4 = sc.getSoilSuitabilityMap()
```

## Verification

1. **fc4 range**: 0–1; fertile soils near 1.0, degraded soils near 0
2. **SMU matching**: All soil_map codes must exist in Excel sheets; missing codes → fc4=0
3. **SQ scores**: Individual SQ1–SQ7 should be 0–100; check for all-zero
4. **Yield reduction**: soil_yield ≤ input yield everywhere
5. **Rainfed vs irrigated**: Different fc4 tables can give different patterns

## Traps

| Trap | Symptom | Root Cause |
|------|---------|------------|
| fc4 = 0 everywhere | Soil map SMU codes not matching Excel | Check SMU integer codes match |
| fc4 = 1 everywhere | All reduction factors set to 100 | Review Excel reduction values |
| Missing SMU error | Some soil_map values not in Excel | Add missing SMU rows to Excel |
| Wrong condition code | Using 'R' tables for irrigated run | Check irr_or_rain parameter |
| HWSD v1 vs v2 mismatch | Different property names between versions | Verify column names |

## Example

```python
from pyaez import SoilConstraints
from osgeo import gdal

soil_map = gdal.Open('data_input/LAO_Soil.tif').ReadAsArray()

sc = SoilConstraints.SoilConstraints()
sc.importSoilReductionSheet('maiz_soil_params_rain.xlsx', 'maiz_soil_params_irr.xlsx')
sc.calculateSoilQualities('R', 'maiz_soil_characteristics_topsoil.xlsx',
                           'maiz_soil_characteristics_subsoil.xlsx')
sc.calculateSoilRatings('H')

soil_yield = sc.applySoilConstraints(soil_map, clim_yield_rain)
fc4 = sc.getSoilSuitabilityMap()
print(f"fc4 range: {fc4[mask>0].min():.2f} – {fc4[mask>0].max():.2f}")
```
