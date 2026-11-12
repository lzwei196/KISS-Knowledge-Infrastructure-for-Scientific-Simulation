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
| Stream.Flow | DHSVM ASCII | Per-segment water volumes, m3 per model step (not m3/s) |
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
     --segment <SAVE name of the gauge segment> \
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

- **Parsed record count** matches expected timesteps (Stream.Flow: steps - 1 rows
  per saved segment, because the first model step has only a `Totals` row)
- **No NaN values** in parsed output
- **Streamflow units**: Stream.Flow and Streamflow.Only hold water VOLUMES in m3 per
  model time step, not m3/s (channel.c: `outflow * deltat`). For m3/s divide by the
  step length in seconds (Time Step hours x 3600). Only with no channel network
  (unit hydrograph mode) is Stream.Flow one m3/s value per step.
- **Date alignment**: Ensure observed and simulated dates overlap
- **Mass balance closure** < 1% of total inflow

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Date format mismatch | Zero matched records in validation | Convert obs to DHSVM date format |
| Wrong segment for validation | Metrics computed at wrong location | Use outlet segment (check "name" field) |
| Aggregated vs pixel | Wrong spatial scale for comparison | Use pixel output for point comparisons |
| Unit mismatch in obs | PBIAS hundreds of percent | Verify both are in m3/s (or both mm) |
| Stream.Flow read as m3/s | Simulated flow too high by a factor equal to the step length in seconds (10800 for a 3 h step) | Stream.Flow is m3 per model step: divide by (Time Step hours x 3600) first |
| Wrong Stream.Flow column | Simulated flow is upstream inflow or a network total | Use OUTFLOW (5th field) of the gauge segment rows; skip `Totals` rows |
| Spinup included in metrics | Poor metrics due to initialization | Skip first year(s) from metrics |

## Example

```python
# Quick validation analysis
import numpy as np

STEP_HOURS = 3        # placeholder: use the TIME section "Time Step" of your config
SEGMENT = "OUTLET"    # placeholder: the SAVE "name" of the gauge segment

# Stream.Flow segment rows: date id inflow lateral_inflow OUTFLOW storage_change "name"
# Values are m3 per model step. "Totals" rows use another column order: skip them.
vol = []
with open("output/Stream.Flow") as f:
    for line in f:
        parts = line.split()
        if len(parts) >= 5 and f'"{SEGMENT}"' in line:
            vol.append(float(parts[4]))

vol = np.array(vol)                  # m3 per model step
q = vol / (STEP_HOURS * 3600)        # m3/s, mean over each step
print(f"Mean Q: {q.mean():.4f} m3/s")
print(f"Peak Q: {q.max():.4f} m3/s")
print(f"Total volume: {vol.sum() / 1e6:.2f} million m3")
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
