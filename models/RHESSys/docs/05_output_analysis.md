# Stage 5: Output Parsing and Analysis

## Purpose

Parse RHESSys output files into analysis-ready formats, apply unit conversions
for comparison with observations, and compute validation metrics.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| Model output | Space-delimited or CSV | Raw RHESSys output files |
| Observed streamflow | CSV | Gauge data (typically m^3/s) |
| Basin area | scalar (m^2) | For streamflow unit conversion |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Parsed CSV | `.csv` | Clean, column-named time series |
| Validation metrics | JSON/text | NSE, KGE, PBIAS, R^2 |
| Time series plots | PNG | Observed vs simulated |

## Procedure

### Step 1: Identify Output Format

RHESSys has two output modes:

**Legacy (space-delimited):** Columns are positional, no header. Column order
depends on the output level (basin/patch/stratum) and whether growth mode was
enabled.

**CSV (output filter):** Standard CSV with headers. Produced when `-of filter.yml`
is used.

### Step 2: Parse to Clean CSV

For legacy output:
```bash
python ki/tools/parse_output.py \
  --input out/test_basin.daily \
  --output out/basin_daily.csv \
  --level basin
```

For CSV output:
```bash
python ki/tools/parse_output.py \
  --input out/test_basin_daily.csv \
  --output out/basin_clean.csv \
  --level basin --csv-input
```

### Step 3: Unit Conversion for Streamflow

**CRITICAL:** RHESSys streamflow output is in **m/day per unit basin area**
(i.e., depth/time). To compare with observed discharge (m^3/s):

```
Q_m3s = streamflow_m_day × basin_area_m2 / 86400
```

Where:
- `streamflow_m_day` = model output value
- `basin_area_m2` = total basin area in m^2
- `86400` = seconds per day

**TRAP dt_002:** Forgetting this conversion and comparing m/day/m^2 directly
against m^3/s gives dimensionally wrong results that can appear plausible for
small basins but are always wrong.

```bash
python ki/tools/parse_output.py \
  --input out/test_basin.daily \
  --output out/basin_daily.csv \
  --level basin \
  --basin-area 1000000
```

### Step 4: Key Output Variables

**Basin daily columns (legacy):**

| Column | Position | Variable | Unit |
|--------|----------|----------|------|
| 1-3 | 1-3 | day, month, year | — |
| 4 | 4 | basinID | — |
| 24 | 24 | streamflow | m/day/m^2 |
| 9-10 | 9-10 | trans_sat, trans_unsat | m/day |
| 13 | 13 | evap | m/day |
| 15 | 15 | sat_deficit | m |
| 17 | 17 | unsat_storage | m |
| 21 | 21 | snow_stored | m |
| 26 | 26 | LAI | m^2/m^2 |
| 33-34 | 33-34 | streamflow_NO3, streamflow_DON | kg N/m^2/day |

### Step 5: Validation Metrics

Standard hydrology metrics:

**Nash-Sutcliffe Efficiency (NSE):**
```
NSE = 1 - sum((Qobs - Qsim)^2) / sum((Qobs - mean(Qobs))^2)
```
- NSE = 1: perfect; > 0.5: good; < 0: worse than mean

**Kling-Gupta Efficiency (KGE):**
```
KGE = 1 - sqrt((r-1)^2 + (alpha-1)^2 + (beta-1)^2)
```
- r = correlation, alpha = variability ratio, beta = bias ratio

**Percent Bias (PBIAS):**
```
PBIAS = 100 * sum(Qsim - Qobs) / sum(Qobs)
```
- 0%: no bias; positive: over-prediction

### Step 6: Water Balance Check

```python
# Check: P - ET - Q - dS ≈ 0
rain = sum(data['rain'])
et = sum(data['evap']) + sum(data['trans_sat']) + sum(data['trans_unsat'])
q = sum(data['streamflow'])
ds = data['sat_deficit'].iloc[-1] - data['sat_deficit'].iloc[0]
residual = rain - et - q + ds  # Should be near 0
```

### Step 7: Multi-variable Validation

Beyond streamflow, validate:
- **Snow:** SWE against SNOTEL (m water equivalent)
- **ET:** against MODIS ET (mm/day × 1000 → m/day)
- **LAI:** against MODIS LAI (m^2/m^2, direct comparison)
- **Soil moisture:** against in-situ or SMAP (volumetric)

## Verification

```bash
# Check parsed CSV has expected columns
head -1 out/basin_daily.csv

# Check date range
python3 -c "
import csv
with open('out/basin_daily.csv') as f:
    rows = list(csv.DictReader(f))
print(f'Rows: {len(rows)}')
print(f'First: {rows[0].get(\"date\", \"N/A\")}')
print(f'Last: {rows[-1].get(\"date\", \"N/A\")}')
"

# Quick streamflow stats
python3 -c "
import csv
with open('out/basin_daily.csv') as f:
    rows = list(csv.DictReader(f))
sf = [float(r['streamflow']) for r in rows if r.get('streamflow')]
print(f'Streamflow: min={min(sf):.6f} max={max(sf):.6f} mean={sum(sf)/len(sf):.6f} m/day/m^2')
"
```

## Traps

| Trap | Symptom | Fix | Triplet |
|------|---------|-----|---------|
| Comparing m/day/m^2 vs m^3/s | Metrics make no sense | Convert with basin area | dt_002 |
| All zeros in output | TEC events before start | Fix TEC dates | dt_014 |
| Streamflow 1000x too high | Precip in mm not m | Fix input precip units | dt_001 |
| Negative streamflow | Numerical instability | Check soil params, reduce timestep | dt_018 |

## Example

```python
import pandas as pd
import numpy as np

# Load model output
sim = pd.read_csv("out/basin_daily.csv", parse_dates=["date"])

# Convert streamflow to m^3/s
basin_area = 1e6  # m^2
sim["Q_m3s"] = sim["streamflow"].astype(float) * basin_area / 86400

# Load observations
obs = pd.read_csv("obs_streamflow.csv", parse_dates=["date"])

# Merge and compute NSE
merged = pd.merge(obs, sim[["date", "Q_m3s"]], on="date")
nse = 1 - np.sum((merged["Q_obs"] - merged["Q_m3s"])**2) / \
          np.sum((merged["Q_obs"] - merged["Q_obs"].mean())**2)
print(f"NSE = {nse:.3f}")
```
