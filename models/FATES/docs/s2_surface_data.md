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
   # From HWSD (shared ki_tools_common.lookup_hwsd: hwsd.bil + HWSD_DATA.csv;
   # --hwsd-path optionally names another hwsd.bil). Example site: Manaus K34
   # (HWSD map unit 12719). Note: the BCI pixel (9.15, -79.85) is HWSD map unit
   # 18773, which has no usable texture, so the tool stops there; give BCI
   # field soil values with --soil-texture instead.
   python tools/convert_surface_data.py \
       --lat -2.609 --lon -60.209 \
       --soil-source hwsd --soil-depth 1.0 \
       --output surfdata_k34.json

   # Manual texture
   python tools/convert_surface_data.py \
       --lat 45.0 --lon -90.0 \
       --soil-texture "clay_pct=25,sand_pct=40,silt_pct=35" \
       --organic-matter-pct 2.5 --bulk-density 1.35 \
       --soil-depth 2.0 \
       --output surfdata_custom.json

   # Standard texture class
   python tools/convert_surface_data.py \
       --lat 45.0 --lon -90.0 \
       --texture-class clay_loam --organic-matter-pct 2.5 --bulk-density 1.35 \
       --soil-depth 1.5 \
       --output surfdata_clayloam.json
   ```

   Soil values per CLM layer (by layer node depth), no invented depth trend:
   - HWSD: node depth <= 0.30 m uses HWSD topsoil (0-30 cm), 0.30-1.00 m uses
     HWSD subsoil (30-100 cm). Organic matter % = HWSD OC % x 1.724; bulk
     density = HWSD T_/S_REF_BULK_DENSITY (g/cm3). A layer below 1.00 m within
     `--soil-depth` has no HWSD value: the tool stops unless
     `--deep-layers-from-subsoil` is given, which copies the 30-100 cm values
     there and records it (`deep_layers_from_subsoil`, `source_by_layer`).
     When `--soil-depth` keeps every active layer in the top 0.30 m (e.g. 0.3),
     the HWSD subsoil is not read or required (`subsoil_used: false`), and only
     topsoil hydraulics are given.
   - Manual / texture class: the given texture, `--organic-matter-pct` and
     `--bulk-density` (both required) apply to every layer down to
     `--soil-depth`. There is no default soil.
   - Layers below `--soil-depth` are bedrock (0).
   - Output also gives `ORGANIC_kg_m3_by_layer`, the CLM surfdata ORGANIC field
     (organic matter density, kg/m3 = OM% / 100 x BD x 1000).
   - Porosity (Clapp-Hornberger hydraulics) uses the given bulk density.
     Field capacity (-33 kPa) and wilting point (-1500 kPa) use
     theta = porosity x (psi / psi_sat)^(-1/b) with both heads in mm of water
     (1 kPa = 101.97 mm), so 33 kPa = 3365 mm and 1500 kPa = 152 957 mm.
   - Inputs are checked first: every number must be finite (no nan/inf);
     `--organic-matter-pct` 0-100 %, `--bulk-density` 0.5-2.0 g/cm3, texture
     keys exactly clay/sand/silt, each 0-100 % and summing to 100 %.
   - Longitude may be given as -180..180 or 0..360. HWSD is sampled at the
     same point in -180..180; the output `grid.longitude` is 0..360 (CLM).
   - HWSD provenance: `soil_provenance` (summary) and
     `soil_properties.provenance` (output file) keep the map unit id and the
     shared lookup's `hwsd_component` record (share, dominant share,
     `texture_from_dominant`, `quality`). When the soil comes from a
     non-dominant component, a warning says so and `status` is
     `success_with_warnings`.

3. **Set PFT distribution**:
   ```bash
   # Tropical forest: 80% broadleaf evergreen + 20% deciduous
   python tools/convert_surface_data.py \
       --lat -2.609 --lon -60.209 --soil-source hwsd --soil-depth 1.0 \
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
    --soil-source hwsd --soil-depth 1.0 \
    --pft-distribution "5:0.7,1:0.2,10:0.1" \
    --output surfdata_harvard.json
```

PFT distribution rationale:
- PFT 5 (broadleaf cold-deciduous): 70% — dominant oaks and maples
- PFT 1 (needleleaf evergreen): 20% — white pine and hemlock
- PFT 10 (cool C3 grass): 10% — understory grasses and herbs
