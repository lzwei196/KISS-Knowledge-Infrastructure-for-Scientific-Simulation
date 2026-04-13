# S6: Validation and Calibration

## Purpose

Compare Daisy simulation results against observed field data or literature values, compute performance metrics, and identify calibration needs.

## Inputs

| Input | Source | Format | Required |
|-------|--------|--------|----------|
| Simulated output | S5 output | CSV / DataFrame | Yes |
| Observed data | Field measurements | CSV (date, variable, value) | For quantitative validation |
| Literature values | Published studies | Typical ranges | For plausibility checks |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Metrics summary | JSON / text | NSE, RMSE, PBIAS, r² for each variable |
| Validation figures | PNG | Time series comparisons, scatter plots |
| Calibration recommendations | Text | Parameters to adjust |

## Procedure

### Plausibility Validation (no observed data needed)

1. **Check yield against literature** for the crop type and region:
   - Spring Barley (Denmark): 4–7 Mg DM/ha grain
   - Winter Wheat (Denmark): 6–10 Mg DM/ha grain
   - Maize silage: 10–18 Mg DM/ha total
   - Grass (4 cuts): 8–14 Mg DM/ha total

2. **Check water balance**:
   - Annual ET: 300–600 mm for temperate continental
   - Drainage: 50–400 mm depending on climate and soil
   - Precipitation vs ET+Drain+Runoff ≈ ΔStorage

3. **Check N balance**:
   - Harvest N: 80–200 kg N/ha for cereals
   - Leaching: < 50 kg N/ha/year (well-managed), can be > 100 for sandy soils
   - Denitrification: 5–30 kg N/ha/year

### Quantitative Validation (with observed data)

4. **Align time series** — Match dates between simulated and observed
5. **Compute metrics**:

   **Nash-Sutcliffe Efficiency (NSE)**:
   ```
   NSE = 1 - Σ(sim - obs)² / Σ(obs - obs_mean)²
   ```
   - > 0.5: satisfactory; > 0.65: good; > 0.75: very good

   **Root Mean Square Error (RMSE)**:
   ```
   RMSE = √(Σ(sim - obs)² / n)
   ```

   **Percent Bias (PBIAS)**:
   ```
   PBIAS = 100 × Σ(sim - obs) / Σ(obs)
   ```
   - |PBIAS| < 10%: very good; < 25%: satisfactory

   **Correlation coefficient (r)**:
   ```
   r = Σ((sim - sim_mean)(obs - obs_mean)) / √(Σ(sim - sim_mean)² × Σ(obs - obs_mean)²)
   ```

6. **Create validation figures**:
   - Time series: observed (black) vs simulated (blue #2563EB)
   - Scatter plot: 1:1 line
   - Residual plot: bias over time

### Calibration Guidance

7. **If yield too low** → Check:
   - Radiation input (unit conversion)
   - N fertilization amount
   - Water stress (irrigation needed?)
   - Crop variety parameters

8. **If yield too high** → Check:
   - Disease/pest effects not modeled
   - Soil N availability too high
   - Initial organic matter too high

9. **If drainage too high/low** → Check:
   - Soil hydraulic parameters (K_sat, alpha, n)
   - Groundwater model settings
   - Precipitation input units

10. **If N leaching too high** → Check:
    - Fertilizer timing (too early → winter leaching)
    - Catch crop / cover crop management
    - Soil C/N ratio

## Verification

- [ ] Simulated values fall within plausible physical ranges
- [ ] Harvest timing matches expected phenology (DS reaches 2.0)
- [ ] Water balance closes to within 5% of precipitation
- [ ] If observed data available: NSE > 0 (better than mean)
- [ ] No systematic bias in residuals

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Comparing different variables | Grain yield vs total biomass | Ensure apples-to-apples comparison |
| Unit mismatch in comparison | PBIAS > 1000% | Check both sim and obs are in same units |
| Ignoring spinup period | Poor early performance | Discard first 1–3 years from metrics |
| Using wet weight vs dry weight | 2–5× yield overestimate | Daisy reports DM; convert obs if needed |
| Wrong time alignment | Shifted correlation | Match exact dates, not just indices |

## Example

```python
import numpy as np
import pandas as pd

# Load simulated and observed
sim = pd.read_csv("csv/harvest.csv")
obs_yield = 5.2  # Mg DM/ha (observed spring barley grain)

sim_yield = sim["sorg_DM"].iloc[0]  # First harvest event
bias = sim_yield - obs_yield
pbias = 100 * bias / obs_yield

print(f"Simulated: {sim_yield:.2f} Mg DM/ha")
print(f"Observed:  {obs_yield:.2f} Mg DM/ha")
print(f"Bias:      {bias:+.2f} Mg DM/ha ({pbias:+.1f}%)")
```
