# Stage 2: Soil Parameters

## Purpose

Derive soil hydraulic properties from soil databases (HWSD, SoilGrids, USDA) and
convert them to GIFMod Soil block parameters with correct units.

## Inputs

| Input                  | Source            | Format    | Required |
|------------------------|-------------------|-----------|----------|
| Soil texture (sand/clay/silt %) | HWSD/SoilGrids | CSV | Yes |
| Bulk density           | HWSD/SoilGrids    | g/cm^3    | Yes      |
| Organic matter content | HWSD/SoilGrids    | percent   | No       |
| Soil depth             | Site data         | cm or m   | Yes      |

## Outputs

| Output               | Format   | Unit System            |
|----------------------|----------|------------------------|
| Ks (hyd. conductivity) | JSON   | m/day                  |
| Porosity             | JSON     | fraction (0-1)         |
| theta_r (residual)   | JSON     | fraction               |
| theta_s (saturated)  | JSON     | fraction               |
| Bulk density         | JSON     | kg/m^3                 |
| Dispersivity         | JSON     | m                      |
| Field capacity       | JSON     | fraction               |
| Wilting point        | JSON     | fraction               |

## Procedure

1. **Extract soil texture**: Obtain sand%, clay%, silt% for each soil layer.

2. **Apply pedotransfer functions**: Use Saxton & Rawls (2006) to estimate:
   - Saturated hydraulic conductivity (Ks) from texture
   - Moisture retention parameters (theta_33, theta_1500)
   - Porosity from bulk density

3. **Convert units** (CRITICAL):
   - Ks: cm/hr from Saxton-Rawls -> m/day (* 0.24)
   - If Ks in cm/s from database: cm/s -> m/day (* 864.0)
   - Bulk density: g/cm^3 -> kg/m^3 (* 1000.0)
   - Porosity: if percent, divide by 100
   - Depth: cm -> m (* 0.01)

4. **Estimate dispersivity**: Use rule-of-thumb alpha = 0.1 * layer_depth (m),
   minimum 0.01 m.

5. **Validate ranges**:
   - Ks: 0.001 - 100 m/day (typical soil range)
   - Porosity: 0.20 - 0.65
   - Bulk density: 800 - 2000 kg/m^3
   - theta_r: 0.01 - 0.20

## Verification

- [ ] All Ks values > 0 and in m/day
- [ ] Porosity in range [0.20, 0.65]
- [ ] Bulk density in range [800, 2000] kg/m^3
- [ ] theta_r < theta_s for all layers
- [ ] theta_s approximately equals porosity

## Traps

| ID     | Trap                              | Error Factor | Consequence                |
|--------|-----------------------------------|--------------|----------------------------|
| dt_001 | Ks in cm/s not m/day              | 864x low     | No infiltration            |
| dt_005 | Bulk density in g/cm^3 not kg/m^3 | 1000x low    | Wrong sorption mass        |
| dt_012 | Porosity as 40 instead of 0.40    | 100x high    | Numerical explosion        |
| dt_006 | Dispersivity in cm not m          | 100x low     | No solute mixing           |

## Example

```bash
python convert_soil_params.py \
  --input hwsd_layer1.csv \
  --output soil_params.json \
  --format hwsd
```

Input CSV:
```csv
id,sand,clay,bulk_density,depth
layer_1,45,22,1.35,100
layer_2,60,15,1.50,50
```

Output JSON (excerpt):
```json
{
  "layers": [
    {
      "layer_id": "layer_1",
      "Ks": 2.156,
      "porosity": 0.4321,
      "bulk_density": 1350.0,
      "depth": 1.0,
      "dispersivity": 0.1
    }
  ]
}
```
