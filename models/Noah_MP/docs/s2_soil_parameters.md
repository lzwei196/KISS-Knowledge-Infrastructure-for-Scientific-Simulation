# Stage 2: Soil Parameters

## Purpose

Derive soil hydraulic and thermal parameters for Noah-MP from global soil databases
(HWSD, SoilGrids) or assign default soil types based on the STATSGO/STAS classification.
Noah-MP uses soil type indices (ISLTYP) to look up parameters from NoahmpTable.TBL.

## Inputs

| Input | Source | Format | Required |
|-------|--------|--------|----------|
| Soil texture (sand/clay %) | HWSD v1.2 or SoilGrids | NetCDF/raster | Yes |
| Domain grid | HRLDAS setup file | NetCDF | Yes |
| Organic matter content | HWSD | NetCDF | Optional |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| ISLTYP field in setup file | NetCDF (integer 2D) | Soil type index per grid cell |
| soil_params.json | JSON | Soil parameters summary |

## Procedure

### 1. Obtain soil texture data

**HWSD v1.2** (Harmonized World Soil Database):
- Resolution: 30 arc-second (~1 km)
- Variables: T_SAND, T_CLAY, T_SILT, T_OC (top soil, 0-30cm)
- Path: `KISSPATH_STATIC/`

**SoilGrids v2.0**:
- Resolution: 250 m
- Variables: sand, clay, silt at 6 depths (0-5, 5-15, 15-30, 30-60, 60-100, 100-200 cm)

### 2. Classify soil texture (USDA triangle)

Convert sand/clay percentages to USDA texture class, then map to Noah-MP type index:

| USDA Class | Noah-MP ISLTYP | SMCMAX | DKSAT (m/s) | BEXP |
|------------|---------------|--------|-------------|------|
| Sand | 1 | 0.395 | 1.76e-4 | 4.05 |
| Loamy Sand | 2 | 0.410 | 1.56e-4 | 4.38 |
| Sandy Loam | 3 | 0.435 | 3.47e-5 | 4.90 |
| Silt Loam | 4 | 0.485 | 7.20e-6 | 5.30 |
| Silt | 5 | 0.485 | 7.20e-6 | 5.30 |
| Loam | 6 | 0.451 | 6.95e-6 | 5.39 |
| Sandy Clay Loam | 7 | 0.420 | 6.30e-6 | 7.12 |
| Silty Clay Loam | 8 | 0.477 | 1.70e-6 | 7.75 |
| Clay Loam | 9 | 0.476 | 2.45e-6 | 8.52 |
| Sandy Clay | 10 | 0.426 | 2.17e-6 | 10.4 |
| Silty Clay | 11 | 0.492 | 1.03e-6 | 10.4 |
| Clay | 12 | 0.482 | 1.28e-6 | 11.4 |
| Organic | 13 | 0.451 | 8.00e-6 | 5.25 |

### 3. Handle special types

- **Water bodies (ISLTYP=14)**: Skip in land surface calculation
- **Bedrock (ISLTYP=15)**: Very low DKSAT, minimal infiltration
- **Urban areas**: Handled by sf_urban_physics option, not soil type

### 4. Set initial soil moisture

Initialize SMOIS per layer (in HRLDAS setup file):
- Wet season start: `SMOIS = 0.75 * SMCMAX` (all layers)
- Dry season start: `SMOIS = 0.50 * SMCMAX` (all layers)
- Spinup recommendation: Run 3-5 years to equilibrate soil moisture

### 5. Using the tool

```bash
python ki/tools/convert_soil_to_noahmp.py \
  --hwsd_path KISSPATH_STATIC/hwsd.nc \
  --lat 33.0 --lon 117.0 \
  --output soil_params.json
```

Or with manual texture:
```bash
python ki/tools/convert_soil_to_noahmp.py \
  --sand 45 --clay 20 \
  --lat 33.0 --lon 117.0 \
  --output soil_params.json
```

## Verification

- [ ] ISLTYP values are in range [1, 19]
- [ ] No ISLTYP=0 (undefined) in land grid cells
- [ ] SMCMAX > SMCREF > SMCWLT > 0 for each soil type
- [ ] DKSAT > 0 (non-zero conductivity)
- [ ] Initial SMOIS is between SMCWLT and SMCMAX

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| dt_010 | Zero runoff everywhere | DKSAT too high (sandy soil classified as all sand) |
| dt_011 | Permanent saturation | ISLTYP mismatch: clay assigned where sand expected |
| dt_006 | Wrong soil layer depths | ZSOIL must be negative; DZS must be positive |
| dt_012 | Extreme ET | SMCMAX set too high, soil never dries out |

## Example

For Bengbu basin (Huai River, China):
- Typical soil: Silt Loam to Clay Loam (ISLTYP 4-9)
- Sand: 15-35%, Clay: 20-35%
- Initial SMOIS: 0.30 m³/m³ (moderately wet)
- NSOIL: 4, depths: 0.1, 0.4, 1.0, 2.0 m
