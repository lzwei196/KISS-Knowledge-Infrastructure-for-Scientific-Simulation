# S4: Soil Parameterization Skill

## Purpose

Convert soil physical and hydraulic properties from global or regional soil
databases (HWSD, SSURGO, SoilGrids) into PIHM `.soil` and `.geol` file formats.
Applies pedotransfer functions (PTFs) when hydraulic parameters are not directly
available. Handles the critical unit conversions that cause silent model failures.

## Prerequisites

- Mesh and attribute files (S1, S2) completed — need soil type assignments
- Soil database extract covering the watershed area
- Knowledge of source database units

## Inputs

| Input | Source | Format |
|-------|--------|--------|
| Soil properties | HWSD/SSURGO/SoilGrids | CSV or shapefile |
| Texture data | Sand/silt/clay percentages | % |
| Organic matter | OM content | % |
| Bulk density | BD | g/cm³ or kg/m³ |

### Soil Parameters Required by PIHM

| Parameter | Symbol | Unit | Description |
|-----------|--------|------|-------------|
| Silt content | SILT | % | Silt percentage |
| Clay content | CLAY | % | Clay percentage |
| Organic matter | OM | % | Organic matter percentage |
| Bulk density | BD | g/cm³ | Dry bulk density |
| Infiltration Ksat | KINF | m/s | Saturated infiltration conductivity |
| Vertical Ksat | KSATV | m/s | Vertical saturated hydraulic conductivity |
| Horizontal Ksat | KSATH | m/s | Horizontal saturated hydraulic conductivity |
| Porosity | SMCMAX | m³/m³ | Maximum (saturated) soil moisture |
| Residual moisture | SMCMIN | m³/m³ | Residual (minimum) soil moisture |
| vG alpha | ALPHA | 1/m | van Genuchten alpha parameter |
| vG beta | BETA | - | van Genuchten n parameter |
| Quartz content | QTZ | - | Fraction quartz (for thermal conductivity) |
| Macropore horiz. | MACHF | m²/m² | Horizontal macropore area fraction |
| Macropore vert. | MACVF | m²/m² | Vertical macropore area fraction |
| Macropore depth | DMAC | m | Depth of macropore zone |

### Global Parameters

| Parameter | Symbol | Default | Description |
|-----------|--------|---------|-------------|
| Infiltration depth | DINF | 0.10 m | Depth for infiltration gradient |
| Vertical macro ratio | KMACV_RO | 100.0 | Ksat_macro / Ksat_matrix (vertical) |
| Horizontal macro ratio | KMACH_RO | 1000.0 | Ksat_macro / Ksat_matrix (horizontal) |

## Outputs

| Output | Path | Format |
|--------|------|--------|
| Soil parameters | `input/<project>/<project>.soil` | PIHM text |
| Geology parameters | `input/<project>/<project>.geol` | PIHM text |

## Procedure

### Step 1: Extract Soil Data

Extract soil properties for each soil type in your `.att` file. Ensure the soil
type indices match between `.att` and `.soil` files.

### Step 2: Apply Pedotransfer Functions (if needed)

If hydraulic parameters (Ksat, alpha, beta, porosity) are not directly available,
use PTFs based on texture class:

```bash
python ki/tools/soil_converter.py \
    --input soils.csv \
    --soil-output input/MyProject/MyProject.soil \
    --geol-output input/MyProject/MyProject.geol \
    --use-ptf
```

### Step 3: Convert Units

If hydraulic parameters are provided but in wrong units:

```bash
python ki/tools/soil_converter.py \
    --input soils.csv \
    --soil-output input/MyProject/MyProject.soil \
    --geol-output input/MyProject/MyProject.geol \
    --ksat-unit cm/hr \
    --alpha-unit 1/cm \
    --bd-unit g/cm3 \
    --depth-unit m
```

### Step 4: Validate Parameters

Check converted values against expected ranges by texture class:

| Texture | Ksat (m/s) | Alpha (1/m) | n | Porosity |
|---------|-----------|------------|---|----------|
| Sand | 5e-5 – 1e-3 | 10–20 | 2.2–3.0 | 0.38–0.46 |
| Loam | 1e-6 – 5e-5 | 2–5 | 1.4–1.7 | 0.38–0.46 |
| Clay | 5e-8 – 5e-6 | 0.5–2 | 1.05–1.2 | 0.35–0.45 |
| Silt loam | 5e-7 – 5e-5 | 1–3 | 1.3–1.5 | 0.42–0.50 |

## Verification

1. **Index check**: All soil types in `.att` exist in `.soil`
2. **Range check**: All parameters within physically reasonable bounds
3. **Consistency**: SMCMIN < SMCWLT < SMCREF < SMCMAX
4. **Anisotropy**: KSATH ≥ KSATV (horizontal conductivity usually higher)
5. **Geology**: Bedrock Ksat should be 10–1000× less than soil Ksat

## Traps

| Trap | Triplet | Severity |
|------|---------|----------|
| Ksat in cm/hr not m/s | dt_007 | Silent — instant drainage |
| Alpha in 1/cm not 1/m | dt_008 | Silent — wrong retention |
| Depth in cm not m | dt_009 | Degraded — wrong storage |
| BD in kg/m³ not g/cm³ | dt_010 | Silent — wrong thermal |
| Soil index mismatch .att/.soil | dt_018 | Silent — wrong properties |

## Example

Converting HWSD data for Shale Hills:

```bash
python ki/tools/soil_converter.py \
    --input hwsd_shale_hills.csv \
    --soil-output input/ShaleHills/ShaleHills.soil \
    --geol-output input/ShaleHills/ShaleHills.geol \
    --ksat-unit cm/hr \
    --alpha-unit 1/cm \
    --bd-unit g/cm3
```

The converter will:
1. Read texture (sand/silt/clay %), OM%, bulk density from CSV
2. Convert Ksat from cm/hr → m/s (÷ 360000)
3. Convert alpha from 1/cm → 1/m (× 100)
4. Estimate quartz content from sand fraction
5. Set default macropore parameters
6. Generate geology file with reduced bedrock conductivity (soil Ksat × 0.01)
