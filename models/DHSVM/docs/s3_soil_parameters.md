# S3: Soil Parameter Preparation

## Purpose

Generate the soil type map (binary) and soil parameter table (config section)
for DHSVM. Soil properties control infiltration, subsurface flow, water storage,
and thermal behavior. Parameters can be derived from texture data using
pedotransfer functions or taken from measured values.

## Inputs

| Input | Format | Units | Source |
|-------|--------|-------|--------|
| Soil texture (sand/clay/silt %) | CSV, shapefile | percent | HWSD, STATSGO, SSURGO |
| Soil depth | CSV | meters | HWSD, field measurements |
| Soil classification map | GeoTIFF | integer class ID | HWSD raster |
| Organic matter content | CSV | percent (optional) | HWSD |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `soil.bin` | Flat binary, int32 | Soil type index per grid cell |
| Config [SOILS] section | ASCII text | Parameter table in DHSVM format |
| `soil_params.json` | JSON | Intermediate parameter file |

## Procedure

1. **Obtain soil texture data** from HWSD or regional soil survey. Each soil type
   needs sand, clay, and silt percentages. Verify they sum to ~100%.

2. **Apply pedotransfer functions** to estimate hydraulic properties:
   - Porosity (Saxton & Rawls 2006): fraction, typically 0.35-0.55
   - Saturated hydraulic conductivity (Ksat): m/s, typically 1e-7 to 1e-4
   - Field capacity: fraction at -33 kPa
   - Wilting point: fraction at -1500 kPa
   - Bulk density: kg/m3, typically 1200-1800

3. **Define soil layers** (typically 3 layers). Depths must be:
   - In **meters** (not cm!)
   - **Monotonically increasing** from surface to bottom
   - Example: 0.1, 0.6, 1.5 m

4. **Create soil type map** by reclassifying the source soil data to integer
   type IDs matching the parameter table. Write as flat binary int32.

5. **Run the converter tool:**
   ```bash
   python tools/convert_soil_params.py \
     --hwsd-file HWSD_DATA.csv --output soil_params.json
   ```

6. **Format the [SOILS] section** in the DHSVM config file:
   ```
   [SOILS]
   Soil Map File          = input/soil.bin
   Number of Soil Types   = 3

   Soil Description     1 = Sandy Loam
   Lateral Conductivity 1 = 0.00015
   Exponential Decrease 1 = 3.0
   Depth Threshold      1 = 1.2
   Number of Soil Layers 1 = 3
   Depth of Layer       1 = 0.1  0.6  1.5
   Porosity             1 = 0.453  0.453  0.453
   Field Capacity       1 = 0.207  0.207  0.207
   Wilting Point        1 = 0.095  0.095  0.095
   Bulk Density         1 = 1452  1452  1452
   Vertical Conductivity 1 = 3.5e-05  3.5e-05  3.5e-05
   ```

## Verification

- **Porosity > Field Capacity > Wilting Point** for each layer
- **Layer depths monotonically increasing**
- **Ksat in m/s**: values should be 1e-7 (clay) to 1e-4 (sand)
- **Bulk density**: 800-2000 kg/m3. Values in g/cm3 (1-2) need × 1000
- **Soil map integer range**: 1 to Number of Soil Types

## Traps

| Trap | Symptom | Severity | Fix |
|------|---------|----------|-----|
| Depth in cm instead of m | Soil far too deep, huge storage | Silent | Divide by 100 |
| Ksat in mm/hr instead of m/s | Drainage rate 3.6e6× too fast | Silent | Divide by 3.6e6 |
| Porosity as % instead of fraction | Porosity > 1, crash or overflow | Fatal | Divide by 100 |
| Bulk density in g/cm3 | Values ~1.5 instead of ~1500 | Silent | Multiply by 1000 |
| WP > FC | Negative available water, extreme ET | Degraded | Recheck pedotransfer inputs |
| Non-monotonic layer depths | Incorrect moisture redistribution | Silent | Sort depths ascending |

## Example

```bash
# Quick parameter generation from texture
python tools/convert_soil_params.py \
  --sand 65 --clay 10 --silt 25 --depth 1.5 \
  --output soil_params.json

# Output includes all derived parameters:
# porosity: 0.44, ksat: 3.5e-05 m/s, FC: 0.21, WP: 0.09
```
