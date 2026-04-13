# Stage 2: Soil Data Preparation

## Purpose

Acquire soil profile data and convert to EPIC's .SOL (soil profile) and .SIT
(site information) formats. EPIC requires detailed soil layer properties
including texture, bulk density, water holding capacity, pH, organic carbon,
and hydraulic conductivity.

## Prerequisites

- Stage 0 (Configuration) completed
- For US locations: SSURGO available via SDA REST API
- For global locations: HWSD raster or SoilGrids/ISRIC
- Site coordinates (latitude, longitude, elevation)

## Inputs

| Source | Coverage | Variables | Access |
|--------|----------|-----------|--------|
| SSURGO/SDA | USA | Full horizon data | REST API (NRCS) |
| HWSD | Global | Top/subsoil (2 layers) | Raster file |
| SoilGrids/ISRIC | Global | 6 depth layers | REST API or tiles |
| Custom CSV | Any | User-defined layers | Local file |

## Outputs

| Output | Format | Location |
|--------|--------|----------|
| {site}.SOL | Fixed-width (8.3f) | soil/ |
| {site}.SIT | Fixed-width | sites/ |

## Procedure

### Using SSURGO (US sites)

```python
from geoEpic.soil import fetch_soil_data
from geoEpic.io import SOL, SIT

# Fetch by coordinates
soil_data = fetch_soil_data(lat=41.5, lon=-93.5)

# Or by MUKEY
from geoEpic.soil.sda import get_soil_from_sda
soil_df = get_soil_from_sda(mukey=354136)

# Create SOL and save
sol = SOL.from_dataframe(soil_df)
sol.save('soil/site1.SOL')
```

### Using HWSD (Global)

```python
# Using the KI converter tool
python tools/convert_soil_to_sol.py \
  --source hwsd \
  --input hwsd_record.json \
  --output-dir soil/ \
  --site-id SITE001 \
  --lat 35.0 --lon 116.5 --elev 50.0
```

### Using SoilGrids (Global)

```python
python tools/convert_soil_to_sol.py \
  --source soilgrids \
  --input soilgrids_export.csv \
  --output-dir soil/ \
  --site-id SITE001 \
  --lat 35.0 --lon 116.5 --elev 50.0
```

### Unit Conversions

| Property | SSURGO Unit | EPIC Unit | Conversion |
|----------|-------------|-----------|------------|
| Bulk density (dbthirdbar_r) | g/cm3 | g/cm3 | None |
| Water content 15bar | fraction | fraction | None |
| Water content 1/3bar | fraction | fraction | None |
| Sand/silt/clay | % | % | None |
| pH | pH | pH | None |
| Organic matter | % OM | % OC | **OM / 1.724** |
| CEC | meq/100g | meq/100g | None |
| Ksat | um/s | mm/hr | **ksat * 3.6** |
| Coarse fragments | % by weight | % | None |

**SoilGrids-specific conversions:**

| Property | SoilGrids Unit | EPIC Unit | Conversion |
|----------|---------------|-----------|------------|
| bdod | cg/cm3 | g/cm3 | **/ 100** |
| sand, silt, clay | g/kg | % | **/ 10** |
| phh2o | pH*10 | pH | **/ 10** |
| soc | dg/kg | % OC | **/ 100** |
| cec | mmol(c)/kg | meq/100g | **/ 10** |
| cfvo | cm3/dm3 | % | **/ 10** |

## Verification

1. **Layer depth**: Must be monotonically increasing (e.g., 18, 28, 52, ... cm)
2. **Bulk density**: 0.8-1.8 g/cm3 (typical agricultural soil)
3. **Water holding**: Wilting < Field Capacity < Porosity
4. **Texture**: Sand + Silt + Clay ~ 100%
5. **pH**: 4.0-8.5 (typical range)
6. **Organic carbon**: 0.1-6% (topsoil), declining with depth
7. **Ksat**: 0.1-500 mm/hr
8. **Hydrological group**: A(sandy) → D(clay); determines runoff curve number

## Traps

| Trap | Symptom | Root Cause | Fix |
|------|---------|------------|-----|
| OM not converted to OC | OC 1.7x too high | Used OM directly as OC | Divide by 1.724 |
| Ksat in um/s not mm/hr | Extremely slow drainage | SSURGO ksat needs *3.6 | Multiply by 3.6 |
| BD in kg/m3 not g/cm3 | BD = 1400 instead of 1.4 | Wrong units | Divide by 1000 |
| SoilGrids not divided | All properties 10-100x wrong | Raw SG values not scaled | Apply scale factors |
| Layer depths in inches | Layers too shallow | US data in inches | Multiply by 2.54 |
| Missing deep layers | Shallow root zone | Only topsoil data | Extrapolate subsoil to 2.3m |
| Hydrological group wrong | Bad runoff estimation | A/D coded as 1 not 4 | Use dominant group |
| Albedo too high/low | Wrong energy balance | Default not appropriate | Use 0.10-0.20 for ag soils |

## Example

```python
from geoEpic.io import SOL

# Load and inspect
sol = SOL.load('soil/umstead.SOL')
print(f"Layers: {sol.num_layers}")
print(f"Depths: {sol.data['Layer_depth'].values}")
print(f"BD range: {sol.data['Bulk_Density'].min():.2f} - {sol.data['Bulk_Density'].max():.2f}")
print(f"Sand range: {sol.data['Sand_content'].min():.1f} - {sol.data['Sand_content'].max():.1f}%")
```
