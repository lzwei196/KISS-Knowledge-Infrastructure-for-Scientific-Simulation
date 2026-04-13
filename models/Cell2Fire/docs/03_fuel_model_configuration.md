# Stage 3: Fuel Model Configuration

## Purpose

Generate the fuel lookup table that maps integer fuel codes in the fuel raster to fire behavior parameters. Each fire model (S&B, FBP, Kitral) uses a different lookup format with model-specific coefficients.

## Inputs

| Input | Description |
|-------|-------------|
| Fire model choice | S (Scott&Burgan), C (Canadian FBP), K (Kitral), P (Portugal) |
| Fuel raster | To determine which fuel codes are present |
| Custom fuel parameters | Optional overrides for specific fuel types |

## Outputs

| File | Model | Description |
|------|-------|-------------|
| `spain_lookup_table.csv` | S, K, P | Scott&Burgan / Kitral / Portugal fuel lookup |
| `fbp_lookup_table.csv` | C | Canadian FBP fuel type lookup |

### Lookup table format

```csv
grid_value,export_value,descriptive_name,fuel_type, r, g, b, h, s, l
101,101,Short sparse grass GR1,GR1,209,255,115,57,255,185
```

| Column | Description |
|--------|-------------|
| grid_value | Integer code matching the fuel raster pixel values |
| export_value | Output/export code (usually same as grid_value) |
| descriptive_name | Human-readable fuel type description |
| fuel_type | Short fuel type code (e.g., GR1, C-2) |
| r, g, b | RGB color for visualization |
| h, s, l | HSL color for visualization |

## Procedure

### Step 1: Identify fuel codes in your raster

```python
import numpy as np
from convert_fuel_params import read_asc

header, data = read_asc("fuels.asc")
unique_codes = np.unique(data[data != -9999])
print(f"Fuel codes present: {unique_codes}")
```

### Step 2: Generate default lookup table

```bash
python convert_fuel_params.py --model S --output-dir ./instance
```

This creates `spain_lookup_table.csv` with all 40+ standard Scott & Burgan fuel types.

### Step 3: Verify all fuel codes are mapped

Every non-NODATA, non-zero fuel code in the raster must have a corresponding `grid_value` in the lookup table. Unmapped codes may cause the simulator to crash or treat the cell as non-burnable.

### Step 4: Customize fuel parameters (optional)

To modify fire behavior for specific fuel types:
1. Create a custom CSV with the same columns
2. Pass to the tool: `--custom-fuels my_fuels.csv`
3. Custom entries override defaults for matching `grid_value`

## Verification

1. **All codes mapped**: Every unique fuel code in the raster has a lookup entry.
2. **No duplicate grid_values**: Each code appears exactly once.
3. **Reasonable fuel_type codes**: Standard naming (GR1-GR9, GS1-GS4, SH1-SH9, etc.).
4. **Non-burnable codes**: Codes 0, 91-99 should be present if those values exist in the raster.
5. **File placed correctly**: Lookup table must be in the same directory as the fuel raster.

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Missing fuel codes | Cells treated as non-burnable, fire stops at boundaries | Add entries for all raster codes |
| Wrong lookup file name | Cell2Fire uses built-in defaults, unexpected behavior | S&B: `spain_lookup_table.csv`, FBP: `fbp_lookup_table.csv` |
| Fuel code 0 present in raster | Creates firebreaks where there should be fuel | Reclassify 0 to appropriate fuel type |
| Mixed fuel model codes | Using FBP codes (1-20) with S&B model | Ensure codes match the chosen --sim option |
| NODATA (-9999) in fuel raster | Cells treated as non-burnable (correct behavior) | Verify this is intentional |

## Example

Scott & Burgan fuel model for Vilopriu 2013 (Catalonia, Spain):
- Dominant fuels: GR3 (103), GR5 (105), SH6 (146), SH8 (148), TU5 (165), TL8 (188)
- Non-burnable: NB3 (93) for agriculture, NB9 (99) for water
- Fuel code 0 for urban/developed areas

```bash
# Generate default lookup
python convert_fuel_params.py --model S --output-dir ./Vilopriu_2013-asc

# Verify
python -c "
import pandas as pd
import numpy as np
from convert_fuel_params import read_asc

lookup = pd.read_csv('./Vilopriu_2013-asc/spain_lookup_table.csv')
_, fuels = read_asc('./Vilopriu_2013-asc/fuels.asc')
codes = set(np.unique(fuels[fuels != -9999]).astype(int))
mapped = set(lookup['grid_value'].astype(int))
unmapped = codes - mapped
if unmapped:
    print(f'WARNING: Unmapped codes: {unmapped}')
else:
    print('All fuel codes are mapped')
"
```
