# S2: Soil Profile Definition

## Purpose

Define the soil column for Daisy from texture, bulk density, and organic matter data. Daisy uses a layered soil column with horizons, each specified by texture fractions and optionally by hydraulic parameters.

## Inputs

| Input | Source | Format | Required |
|-------|--------|--------|----------|
| Clay fraction | HWSD / field data | 0–1 or % | Yes |
| Silt fraction | HWSD / field data | 0–1 or % | Yes |
| Sand fraction(s) | HWSD / field data | 0–1 or % | Yes |
| Humus/organic matter | HWSD / field data | 0–1 or % | Recommended |
| Dry bulk density | HWSD / field data | g/cm³ or kg/m³ | Recommended |
| C/N ratio | Literature / field data | g C/g N | Recommended |
| Horizon depths | Field data | cm (positive or negative) | Yes |
| Hydraulic parameters | Measured or pedotransfer | Various | Optional |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `<site>-soil.dai` | Daisy .dai | Horizon + column definitions |

## Procedure

1. **Collect soil profile data** — For each horizon: depth, texture, bulk density, humus
2. **Choose texture system**:
   - `USDA3`: clay, silt, sand (3 fractions)
   - `FAO3`: clay, silt, sand (same as USDA3 but FAO classification)
   - `ISSS4`: clay, silt, fine_sand, coarse_sand (4 fractions, more precise)
3. **Convert units**:
   - Texture: % → fraction (÷ 100). Daisy uses 0–1 fractions without units
   - Bulk density: kg/m³ → g/cm³ (÷ 1000)
   - Depths: positive → negative (Daisy measures downward from surface as negative)
4. **Normalize texture** — Mineral fractions must sum to ~1.0 (excluding humus)
5. **Choose hydraulic model**:
   - `default`: Daisy estimates from texture (recommended for most cases)
   - `M_vG`: explicit van Genuchten-Mualem parameters (Theta_res, Theta_sat, alpha, n, K_sat)
   - `Cosby_et_al`: pedotransfer function
   - `hypres`: HYPRES pedotransfer function (requires bulk density)
6. **Define column** — Stack horizons with depths, set MaxRootingDepth, groundwater model
7. **Set organic matter initialization** — Initial C input, root C input, depth of incorporation

## Verification

- [ ] Texture fractions sum to ~1.0 per horizon (excluding humus)
- [ ] Depths are negative (below surface)
- [ ] Bulk density is 1.0–2.0 g/cm³ (typical range)
- [ ] Humus is 0.001–0.10 for mineral soils
- [ ] MaxRootingDepth does not exceed deepest horizon
- [ ] No overlapping horizon depths
- [ ] Groundwater model matches site conditions

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Texture in % used as fraction | Clay "10" interpreted as 1000% | Divide all texture values by 100 |
| Positive depths | Daisy interprets as above surface | Negate all depth values |
| Bulk density in kg/m³ | Value ~1500 interpreted as 1500 g/cm³ | Divide by 1000 |
| ISSS4 fractions with USDA3 system | Mismatched columns, wrong parameterization | Match texture system to available data |
| Missing humus | Default 0, underestimates organic N cycling | Provide humus even if estimated |
| K_sat in m/s used as cm/h | Hydraulic conductivity ~3.6e5 too high | Convert: m/s × 360000 = cm/h |
| Alpha in m⁻¹ used as cm⁻¹ | vG retention curve shape wrong | Divide by 100 |
| MaxRootingDepth > soil depth | Roots try to grow below defined soil | Set ≤ deepest horizon |

## Example

```bash
python ki/tools/convert_soil_to_dai.py \
    --input soil_profile.csv \
    --output my-soil.dai \
    --site-name "Taastrup" \
    --max-root-depth 150 \
    --groundwater aquitard \
    --texture-unit percent \
    --bd-unit "g/cm3" \
    --hydraulic hypres
```

Input CSV format:
```csv
name,depth_bottom,clay,silt,sand,humus,dry_bulk_density,C_per_N
Ap,25,10.7,22.2,67.1,2.4,1.45,11.0
Bt,120,22.2,19.5,58.3,1.6,1.66,11.0
C,200,20.7,23.5,55.8,1.0,1.69,11.0
```
