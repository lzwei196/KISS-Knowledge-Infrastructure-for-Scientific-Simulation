# Stage 6: Output Analysis

## Purpose

Parse, validate, and analyze WSIMOD output files (flows.csv, tanks.csv, surfaces.csv).
Extract specific variables, compute water balance metrics, and generate visualizations
for model validation and reporting.

## Inputs

| Input               | Format   | Source              | Notes                          |
|---------------------|----------|---------------------|--------------------------------|
| flows.csv           | CSV      | Model output        | Arc flows + pollutant data     |
| tanks.csv           | CSV      | Model output        | Storage node states            |
| surfaces.csv        | CSV      | Model output        | Land surface states            |
| Observed data       | CSV      | Gauge stations      | For validation comparison      |

## Outputs

| Output              | Format   | Destination         | Notes                          |
|---------------------|----------|---------------------|--------------------------------|
| Parsed DataFrames   | pandas   | Analysis scripts    | Pivoted by arc/node/time       |
| Summary statistics  | JSON     | Reports             | Mean, std, min, max per var    |
| Validation metrics  | JSON     | Reports             | NSE, RMSE, PBIAS, R²          |
| Figures             | PNG      | Reports             | Timeseries, scatter plots      |

## Procedure

1. **Load output files**:
   ```python
   import pandas as pd
   flows = pd.read_csv("outputs/flows.csv", index_col=0)
   tanks = pd.read_csv("outputs/tanks.csv", index_col=0)
   surfaces = pd.read_csv("outputs/surfaces.csv", index_col=0)
   ```

2. **Pivot flow data by arc**:
   ```python
   flow_pivot = flows.pivot(index="time", columns="arc", values="flow")
   phosphate_pivot = flows.pivot(index="time", columns="arc", values="phosphate")
   ```

3. **Compute water balance**:
   ```python
   # Total inflow vs outflow
   total_inflow = flow_pivot[["runoff", "baseflow", "urban_drainage"]].sum(axis=1)
   total_outflow = flow_pivot["catchment_outflow"]
   balance = (total_inflow - total_outflow).abs()
   print(f"Max imbalance: {balance.max():.2e}")
   ```

4. **Validate against observations** (if available):
   ```python
   import numpy as np

   def nse(obs, sim):
       return 1 - np.sum((obs - sim)**2) / np.sum((obs - np.mean(obs))**2)

   def rmse(obs, sim):
       return np.sqrt(np.mean((obs - sim)**2))

   def pbias(obs, sim):
       return 100 * np.sum(sim - obs) / np.sum(obs)

   obs = pd.read_csv("observed_flow.csv", index_col=0, parse_dates=True)
   sim = flow_pivot["catchment_outflow"]
   # Align dates
   common = obs.index.intersection(sim.index)
   print(f"NSE: {nse(obs.loc[common], sim.loc[common]):.3f}")
   print(f"RMSE: {rmse(obs.loc[common], sim.loc[common]):.4f}")
   print(f"PBIAS: {pbias(obs.loc[common], sim.loc[common]):.1f}%")
   ```

5. **Generate figures**:
   ```python
   import matplotlib.pyplot as plt

   fig, axes = plt.subplots(3, 1, figsize=(12, 10))

   # Flow timeseries
   flow_pivot.plot(ax=axes[0], title="Arc Flows (m³/d)")

   # Phosphate timeseries
   phosphate_pivot.plot(ax=axes[1], title="Phosphate Transport (kg/d)")

   # Tank storage
   tanks.pivot(index="time", columns="node", values="volume").plot(
       ax=axes[2], title="Tank Storage"
   )

   plt.tight_layout()
   plt.savefig("results_overview.png", dpi=150)
   ```

## Verification

- [ ] All expected arcs appear in flows.csv
- [ ] No NaN or Inf values in numeric columns
- [ ] Flow values are non-negative
- [ ] Temperature in realistic range (-5 to 40°C)
- [ ] Phosphate/nutrient values are non-negative
- [ ] Water balance closes (imbalance < 1e-6)

## Traps

| Trap   | Symptom                                    | Fix                                      |
|--------|--------------------------------------------|------------------------------------------|
| dt_003 | Pollutant concentrations double on mixing  | Non-additive treated as additive         |
| dt_017 | Tiny mass balance violations accumulate    | Float precision — check tolerance        |
| dt_002 | Flow magnitude 1000× off from observed     | ML vs m³ unit mismatch in output         |
| dt_010 | Missing pollutant column in output         | Pollutant not in POLLUTANTS list         |

## Example

```python
import pandas as pd
from matplotlib import pyplot as plt

# Load
flows = pd.read_csv("outputs/flows.csv", index_col=0)

# Pivot and plot
flow_pivot = flows.pivot(index="time", columns="arc", values="flow")
precip_data = pd.read_csv("timeseries_data.csv")
precip = precip_data.loc[precip_data.variable == "precipitation"].set_index("date")

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
precip["value"].plot(ax=ax1, color="steelblue", title="Precipitation (mm/d)")
flow_pivot[["catchment_outflow", "baseflow"]].plot(ax=ax2, title="Flows")
plt.tight_layout()
plt.savefig("hydrograph.png", dpi=150)
```
