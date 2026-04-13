# S6 — Validation

## Purpose

Compare APSIM simulation results against observed data or published literature
values to assess model performance. Compute standard crop model performance
metrics and produce diagnostic plots.

## Inputs

| Input                | Format     | Source              |
|----------------------|-----------|---------------------|
| Simulation results   | CSV       | S5 output           |
| Observed data        | CSV       | Field trials, literature |
| Comparison variable  | string    | e.g., grain yield, biomass |

## Outputs

| Output               | Format     | Description                          |
|----------------------|-----------|--------------------------------------|
| Metrics report       | JSON/text | R², RMSE, nRMSE, PBIAS, d, EF      |
| Validation plot      | PNG       | Observed vs. simulated scatter/time  |

## Procedure

1. **Prepare observed data**: Align observed measurements with simulation
   outputs. Common comparison variables:
   - **Grain yield** (t/ha): Most common validation target
   - **Total biomass** (t/ha): Above-ground dry matter
   - **Phenology dates**: Days to flowering, days to maturity
   - **LAI** (m²/m²): Peak leaf area timing and magnitude
   - **Soil water** (mm): Profile water content over time

2. **Unit alignment**: Ensure both datasets use the same units:
   - APSIM biomass: g/m² (convert to t/ha by ÷ 100)
   - Phenology: APSIM uses continuous stage codes (e.g., 6.5 for mid-grain fill)

3. **Compute metrics**:
   ```python
   import numpy as np

   def rmse(obs, sim):
       return np.sqrt(np.mean((sim - obs) ** 2))

   def nrmse(obs, sim):
       return rmse(obs, sim) / np.mean(obs) * 100

   def pbias(obs, sim):
       return 100 * np.sum(sim - obs) / np.sum(obs)

   def nse(obs, sim):  # Nash-Sutcliffe Efficiency
       return 1 - np.sum((obs - sim)**2) / np.sum((obs - np.mean(obs))**2)

   def willmott_d(obs, sim):
       return 1 - np.sum((obs - sim)**2) / np.sum(
           (np.abs(sim - np.mean(obs)) + np.abs(obs - np.mean(obs)))**2)

   def r_squared(obs, sim):
       return np.corrcoef(obs, sim)[0, 1] ** 2
   ```

4. **Performance benchmarks** for crop models:

   | Metric  | Excellent | Good     | Acceptable | Poor     |
   |---------|-----------|----------|------------|----------|
   | R²      | > 0.90    | > 0.80   | > 0.65     | < 0.65   |
   | nRMSE   | < 10%     | < 15%    | < 25%      | > 25%    |
   | PBIAS   | < 5%      | < 10%    | < 20%      | > 20%    |
   | EF/NSE  | > 0.75    | > 0.50   | > 0.0      | < 0.0    |
   | d       | > 0.90    | > 0.85   | > 0.75     | < 0.75   |

5. **Create validation plots**:
   - 1:1 scatter plot (obs vs sim) with regression line
   - Time series plot (both on same axis)
   - Residual plot (sim - obs vs obs)

## Verification

- [ ] At least 5 data points for meaningful statistics
- [ ] Units match between observed and simulated
- [ ] Temporal alignment correct (same dates/years)
- [ ] Metrics are within acceptable range for the intended use
- [ ] Plots show no systematic bias

## Traps

- **Unit mismatch in comparison** (dt_006): Comparing APSIM g/m² to
  literature t/ha without conversion. 350 g/m² = 3.5 t/ha, not 350 t/ha.

- **Comparing wrong phenological window**: APSIM reports daily values.
  Literature reports end-of-season yield. Extract the maximum grain weight
  or the value at maturity, not the time series.

- **Spatial scale mismatch**: APSIM simulates a single point/field.
  Regional yield statistics average many fields with different soils,
  management, and varieties.

- **Year selection bias**: Cherry-picking good years gives misleading metrics.
  Include drought years, wet years, and average years.

- **Over-calibration**: If model parameters were tuned to match the
  validation data, the metrics are meaningless. Use independent datasets.

## Example

```python
import numpy as np
import matplotlib.pyplot as plt

# Observed yields (t/ha) from field trials
obs = np.array([2.8, 3.5, 4.2, 3.1, 3.8, 2.5, 4.0, 3.6])
# Simulated yields (converted from g/m²: ÷100)
sim = np.array([2.9, 3.3, 4.5, 3.0, 3.7, 2.7, 4.2, 3.4])

r2 = np.corrcoef(obs, sim)[0,1]**2
nrmse_val = np.sqrt(np.mean((sim-obs)**2)) / np.mean(obs) * 100
pbias_val = 100 * np.sum(sim-obs) / np.sum(obs)

print(f"R² = {r2:.3f}, nRMSE = {nrmse_val:.1f}%, PBIAS = {pbias_val:.1f}%")
# R² = 0.952, nRMSE = 5.8%, PBIAS = 1.3%
```
