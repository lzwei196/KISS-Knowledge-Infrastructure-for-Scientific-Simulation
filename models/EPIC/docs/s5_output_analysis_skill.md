# Stage 5: Output Parsing and Analysis

## Purpose

Parse EPIC output files (.ACY, .DGN, and others) into structured DataFrames,
compute derived variables (above-ground biomass, stress indicators), generate
summary statistics, and create visualization plots.

## Prerequisites

- Stage 4 (Execution) completed
- Output files exist in output/ directory
- Python with pandas, numpy, matplotlib

## Inputs

| Input | Format | Key Variables |
|-------|--------|---------------|
| {site}.ACY | Text (skip 10 rows) | YR, CPNM, YLDG, YLDF, BIOM, YLN, YLP |
| {site}.DGN | Text (skip 10 rows) | Y, M, D, BIOM, RW, LAI, WS, NS, TS |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| {site}_ACY.csv | CSV | Annual yield data |
| {site}_DGN.csv | CSV | Daily simulation data |
| {site}_summary.json | JSON | Summary statistics |
| Yield timeseries plot | PNG | Annual yield visualization |
| Biomass growth curve | PNG | Daily biomass dynamics |

## Procedure

### Parse Annual Yield (ACY)

```python
from geoEpic.io import ACY

acy = ACY('output/site1.ACY')
yield_data = acy.get_var('YLDG')  # Returns DataFrame with YR, CPNM, YLDG
print(yield_data)
```

ACY columns include:
- **YLDG**: Grain yield (t/ha)
- **YLDF**: Forage yield (t/ha)
- **BIOM**: Total biomass (t/ha)
- **YLN/YLP**: Yield nitrogen/phosphorus (kg/ha)
- **LAI**: Peak leaf area index
- **WS/NS/TS**: Stress days (water, nitrogen, temperature)

### Parse Daily General Output (DGN)

```python
from geoEpic.io import DGN

dgn = DGN('output/site1.DGN')
biom = dgn.get_var('BIOM')  # Daily biomass timeseries

# Compute above-ground biomass
dgn_df = dgn.data
dgn_df['AGB'] = dgn_df['BIOM'] - dgn_df['RW']
```

### Using the KI parser tool

```bash
python tools/parse_epic_output.py \
  --output-dir output/ \
  --site-id site1 \
  --export-csv \
  --export-summary
```

### Key Derived Variables

| Variable | Formula | Description |
|----------|---------|-------------|
| AGB | BIOM - RW | Above-ground biomass (t/ha) |
| HI | YLDG / BIOM | Harvest index |
| NUE | YLDG / YLN | Nitrogen use efficiency |
| WUE | YLDG / ET | Water use efficiency |

### Visualization

```python
import matplotlib.pyplot as plt

# Annual yield timeseries
fig, ax = plt.subplots(figsize=(10, 5))
ax.bar(yield_data['YR'], yield_data['YLDG'], color='#2563EB')
ax.set_xlabel('Year')
ax.set_ylabel('Grain Yield (t/ha)')
ax.set_title('EPIC Simulated Crop Yield')
plt.savefig('yield_timeseries.png', dpi=150)

# Daily biomass growth
fig, ax = plt.subplots(figsize=(10, 5))
ax.plot(dgn_df.index, dgn_df['AGB'], color='#2563EB')
ax.set_xlabel('Date')
ax.set_ylabel('Above-Ground Biomass (t/ha)')
plt.savefig('biomass_growth.png', dpi=150)
```

## Verification

1. **Yield reasonableness**:
   - Corn: 5-15 t/ha (typical US Midwest)
   - Soybean: 1.5-4.5 t/ha
   - Winter wheat: 3-10 t/ha
   - Rice: 4-10 t/ha

2. **Biomass dynamics**: Should show S-curve growth during growing season

3. **Stress indicators**: WS, NS, TS should be < 0.3 for well-managed crops

4. **LAI peak**: Corn ~4-6, Soybean ~3-5, Wheat ~4-7

5. **Harvest index**: Corn ~0.45-0.55, Soybean ~0.35-0.45

## Traps

| Trap | Symptom | Root Cause | Fix |
|------|---------|------------|-----|
| All yields = 0 | No crop growth | Wrong PHU, dates, or weather gap | Check OPC and DLY coverage |
| Yield > 30 t/ha | Unrealistically high | Solar radiation in W/m2 not MJ | Fix srad units in DLY |
| Yield very low | Under 2 t/ha for corn | N stress, water stress, or short season | Check NS/WS stress and fertilizer |
| No ACY file | EPIC didn't run or wrong output toggle | PRNT1102.DAT not configured | Enable ACY in output_types |
| Parse error | Malformed output | EPIC version mismatch | Check skip rows (should be 10) |
| AGB negative | RW > BIOM | Possible model error | Clip AGB to max(0, BIOM-RW) |

## Example

```python
from geoEpic.io import ACY, DGN
import json

# Parse and summarize
acy = ACY('output/umstead.ACY')
dgn = DGN('output/umstead.DGN')

summary = {
    'mean_yield': float(acy.data['YLDG'].mean()),
    'peak_biomass': float(dgn.data['BIOM'].max()),
    'peak_lai': float(dgn.data['LAI'].max()),
    'mean_water_stress': float(dgn.data['WS'].mean()),
}

with open('output/summary.json', 'w') as f:
    json.dump(summary, f, indent=2)
```
