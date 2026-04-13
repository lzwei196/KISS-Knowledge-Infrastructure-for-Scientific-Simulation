# S1 — Domain Setup (Soil and Cultivar)

## Purpose

Prepare the soil profile and crop cultivar parameters for the simulation.
This stage converts raw soil data from global databases (HWSD, SoilGrids) or
local sources into APSIM's JSON soil format with correct units and constraints.

## Inputs

| Input                | Format     | Units          | Source              |
|----------------------|-----------|----------------|---------------------|
| Soil texture         | CSV/NetCDF| % (sand/clay)  | HWSD, SoilGrids     |
| Bulk density         | numeric   | g/cc or kg/m³  | HWSD, SoilGrids     |
| Organic carbon       | numeric   | % or g/kg      | HWSD, SoilGrids     |
| pH                   | numeric   | pH units       | HWSD, SoilGrids     |
| Layer depths         | array     | cm or mm       | HWSD, SoilGrids     |
| Crop name            | string    | —              | S0 configuration    |

## Outputs

| Output               | Format     | Description                          |
|----------------------|-----------|--------------------------------------|
| `soil.json`          | JSON      | APSIM soil fragment ready for .apsimx|
| Validation report    | text      | Layer-by-layer parameter summary     |

## Procedure

1. **Extract soil data** for the target location from HWSD or SoilGrids:
   ```bash
   # Example: extract from HWSD CSV
   python convert_soil.py --input hwsd_dalby.csv --output soil.json \
       --lat -27.18 --lon 151.26 --source hwsd --crop Wheat
   ```

2. **Unit conversions** (handled by `convert_soil.py`):
   - Bulk density: kg/m³ ÷ 1000 = g/cc
   - Water content: % (v/v) ÷ 100 = mm/mm
   - Layer thickness: cm × 10 = mm
   - Organic carbon: g/kg ÷ 10 = %

3. **Pedotransfer functions** estimate water retention limits from texture:
   - LL15 (wilting point), DUL (field capacity), SAT (saturation)
   - Uses Saxton & Rawls (2006) equations
   - **MUST satisfy**: AirDry ≤ LL15 ≤ DUL ≤ SAT for every layer

4. **Crop-specific parameters**:
   - Crop LL (lower limit): slightly above LL15 (crop can't extract all water)
   - KL (root water uptake rate): decreases with depth (0.08 at surface → 0.01 deep)
   - XF (root exploration factor): 1.0 for accessible layers, decreasing for deep/restrictive

5. **Water balance parameters**: estimated from topsoil texture:
   - CN2Bare (curve number): 73 (sandy) to 88 (clay)
   - SWCON (drainage): higher for sand, lower for clay
   - Cona/U: evaporation parameters vary by season

## Verification

- [ ] AirDry ≤ LL15 ≤ DUL ≤ SAT for every layer (CRITICAL)
- [ ] Bulk density between 0.5 and 2.2 g/cc
- [ ] Total soil depth ≥ 600 mm (typical crop rooting zone)
- [ ] Layer count matches across all arrays (Physical, Chemical, Organic, WaterBalance)
- [ ] SoilCrop name matches `{Crop}Soil` convention

## Traps

- **Water limits out of order** (dt_003): AirDry > LL15 or LL15 > DUL will crash
  the water balance model. The tool auto-corrects but warns.
- **Bulk density in kg/m³** (dt_009): SoilGrids BD is typically 1000-1800 kg/m³.
  If not divided by 1000, BD appears as 1400 g/cc which is physically impossible.
- **Layer thickness in cm instead of mm** (dt_008): 30 cm layer becomes 30 mm
  (3 cm) if not multiplied by 10, giving a 15 cm soil profile instead of 150 cm.
- **Mismatched layer counts**: If Thickness has 7 layers but BD has 6, APSIM
  crashes with an array index error.

## Example

Input (HWSD extract for Dalby):
```csv
depth_top_cm,depth_bot_cm,sand_pct,clay_pct,bulk_density_kg_m3,organic_carbon_g_kg,ph_water
0,15,35,42,1300,18,6.2
15,30,33,44,1350,12,6.5
30,60,30,48,1400,8,6.8
60,100,28,50,1450,4,7.0
100,150,25,52,1500,2,7.2
150,200,25,52,1520,1,7.3
```

Output: APSIM soil JSON with 6 layers, all constraints satisfied.
