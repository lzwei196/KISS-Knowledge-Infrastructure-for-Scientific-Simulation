# S8: Output Analysis and Validation

## Purpose

Parse DHSVM output files, extract key variables, compute hydrological performance
metrics, and create validation plots. This stage converts DHSVM's native output
formats into standard CSV/JSON for further analysis and compares simulated
streamflow to observations.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| Aggregated.Values | DHSVM ASCII | Basin-averaged time series |
| Stream.Flow | DHSVM ASCII | Per-segment streamflow |
| Mass.Balance | DHSVM ASCII | Running water balance |
| Mass.Final.Balance | Text (stderr) | End-of-simulation balance |
| Observed streamflow | CSV | Gauge data for validation |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| results.csv | CSV | Parsed time series in standard format |
| validation.json | JSON | Metrics: NSE, KGE, PBIAS, RMSE, R |
| hydrograph.png | PNG | Observed vs simulated streamflow plot |

## Procedure

1. **Parse Aggregated.Values** to extract basin-average precipitation, ET,
   soil moisture, SWE, and other state variables:
   ```bash
   python tools/parse_output.py \
     --aggregated output/Aggregated.Values \
     --output results.csv
   ```

2. **Parse Stream.Flow** to extract discharge time series per segment:
   ```bash
   python tools/parse_output.py \
     --streamflow output/Stream.Flow \
     --output streamflow.json
   ```

3. **Check mass balance** for closure errors:
   ```bash
   python tools/parse_output.py \
     --mass-balance output/Mass.Final.Balance \
     --output balance.json
   ```

4. **Compute validation metrics** against observed data:
   ```bash
   python tools/parse_output.py \
     --streamflow output/Stream.Flow \
     --observed gauge_data.csv \
     --metrics nse,kge,pbias,rmse,r \
     --output validation.json
   ```

5. **Interpret metrics:**

   | Metric | Good | Satisfactory | Unsatisfactory |
   |--------|------|-------------|----------------|
   | NSE | > 0.65 | 0.36 – 0.65 | < 0.36 |
   | KGE | > 0.50 | 0.0 – 0.50 | < 0.0 |
   | PBIAS (%) | |±10%| | |±25%| | > |±25%| |
   | R | > 0.80 | 0.60 – 0.80 | < 0.60 |

## Verification

- **Parsed record count** matches expected timesteps
- **No NaN values** in parsed output
- **Streamflow units**: DHSVM outputs m3/s for channel flow
- **Date alignment**: Ensure observed and simulated dates overlap
- **Mass balance closure** < 1% of total inflow

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Date format mismatch | Zero matched records in validation | Convert obs to DHSVM date format |
| Wrong segment for validation | Metrics computed at wrong location | Use outlet segment (check "name" field) |
| Aggregated vs pixel | Wrong spatial scale for comparison | Use pixel output for point comparisons |
| Unit mismatch in obs | PBIAS hundreds of percent | Verify both are in m3/s (or both mm) |
| Spinup included in metrics | Poor metrics due to initialization | Skip first year(s) from metrics |

## Example

```python
# Quick validation analysis
import numpy as np

# Parse simulated streamflow
with open("output/Stream.Flow") as f:
    lines = f.readlines()

# Extract outlet flow (last segment typically)
sim_flow = []
for line in lines:
    parts = line.split()
    if len(parts) > 2 and '"OUTLET"' in line:
        sim_flow.append(float(parts[2]))

sim = np.array(sim_flow)
print(f"Mean Q: {sim.mean():.4f} m3/s")
print(f"Peak Q: {sim.max():.4f} m3/s")
print(f"Total volume: {sim.sum() * 3600 * 3 / 1e6:.2f} million m3")
```

## Key Variables in Aggregated.Values

| Column | Units | Description |
|--------|-------|-------------|
| Precip | m/timestep | Total precipitation |
| Snow | m/timestep | Snowfall portion |
| Swq | m | Snow water equivalent |
| Melt | m/timestep | Snowmelt |
| TotalET | m/timestep | Total evapotranspiration |
| SoilMoist1..N | fraction | Soil moisture per layer |
| TableDepth | m | Water table depth |
| SatFlow | m3/timestep | Saturated subsurface flow |
