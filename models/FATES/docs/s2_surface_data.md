# S2: Surface Data Preparation

## Purpose

Prepare a CLM/ELM surface dataset that provides soil properties, PFT fractional
coverage, and land surface characteristics for a FATES single-point or regional
simulation. The surface dataset maps real-world soil texture and vegetation to the
model grid.

## Inputs

| Input | Format | Source | Required |
|-------|--------|--------|----------|
| Site coordinates | lat/lon | Manual | Yes |
| HWSD soil database | NetCDF | FAO Harmonized World Soil Database | Optional |
| Manual soil texture | CSV/string | Field measurements | Optional |
| PFT distribution | Fraction map | Vegetation surveys, remote sensing | Optional |

### Soil Property Requirements

FATES receives soil properties from the host model (CLM/ELM). The surface dataset
must include:

- **Clay fraction** (%) per soil layer
- **Sand fraction** (%) per soil layer
- **Organic matter** (%) per soil layer
- **Soil depth** (m) — determines active rooting zone

CLM uses up to 15 soil layers with exponentially increasing thickness:
```
Layer 1:  0.0175 m
Layer 2:  0.0451 m
Layer 3:  0.0906 m
...
Layer 10: 3.80 m
Layer 15: 45.0 m (bedrock)
```

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Surface dataset specification | JSON/NetCDF | Soil + PFT properties |
| Hydraulic parameters | JSON | Derived from Clapp-Hornberger |

## Procedure

1. **Determine soil properties**:
   - Option A: HWSD lookup by coordinates
   - Option B: Manual specification from field data
   - Option C: Use a standard texture class (loam, clay, sand, etc.)

2. **Generate surface data**:
   ```bash
   # From HWSD
   python tools/convert_surface_data.py \
       --lat 9.15 --lon -79.85 \
       --soil-source hwsd --hwsd-path /path/to/HWSD.nc \
       --output surfdata_bci.json

   # Manual texture
   python tools/convert_surface_data.py \
       --lat 45.0 --lon -90.0 \
       --soil-texture "clay_pct=25,sand_pct=40,silt_pct=35" \
       --soil-depth 2.0 \
       --output surfdata_custom.json

   # Standard texture class
   python tools/convert_surface_data.py \
       --lat 45.0 --lon -90.0 \
       --texture-class clay_loam --soil-depth 1.5 \
       --output surfdata_clayloam.json
   ```

3. **Set PFT distribution**:
   ```bash
   # Tropical forest: 80% broadleaf evergreen + 20% deciduous
   python tools/convert_surface_data.py \
       --lat 9.15 --lon -79.85 \
       --pft-distribution "0:0.8,4:0.2" \
       --output surfdata_tropical.json
   ```

4. **For actual CTSM runs**: Use CTSM's `mksurfdata_esmf` tool to generate
   NetCDF surface data from the specification.

## Verification

- [ ] Soil texture fractions sum to 100% for each layer
- [ ] PFT fractions sum to 1.0
- [ ] Longitude is in CLM convention (0°–360°) — negative longitudes must be converted
- [ ] Soil depth is physically reasonable (0.5–10 m for most sites)
- [ ] Hydraulic properties pass sanity checks:
  - Porosity: 0.2–0.7
  - Field capacity > wilting point
  - Saturated conductivity > 0

## Traps

| Trap ID | Description | Detection |
|---------|-------------|-----------|
| dt_011 | Soil water as % instead of volumetric fraction | Range check |
| dt_002 | Confusing stems/m² with stems/ha in PFT setup | Value magnitude |
| dt_003 | Patch area 10,000 m² not 1 m² when scaling | Documentation |

### Critical: Longitude Convention

CLM/CTSM uses **0° to 360°** longitude convention. A site at 79.85°W must be
entered as 360 - 79.85 = **280.15°E**.

```python
# WRONG — will place site in eastern hemisphere
lon = -79.85

# CORRECT — CLM 0-360 convention
lon = -79.85 + 360  # = 280.15
```

### Critical: Soil Texture Sum

Clay + sand + silt must sum to exactly 100% for each soil layer. Values from
databases may not sum perfectly — normalize before use.

## Example

**Scenario**: Create surface data for a temperate deciduous forest site at
Harvard Forest, Massachusetts (42.54°N, 72.17°W).

```bash
python tools/convert_surface_data.py \
    --lat 42.54 --lon -72.17 \
    --texture-class loam --soil-depth 1.5 \
    --pft-distribution "5:0.7,1:0.2,10:0.1" \
    --output surfdata_harvard.json
```

PFT distribution rationale:
- PFT 5 (broadleaf cold-deciduous): 70% — dominant oaks and maples
- PFT 1 (needleleaf evergreen): 20% — white pine and hemlock
- PFT 10 (cool C3 grass): 10% — understory grasses and herbs
