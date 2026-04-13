# S7: Output Analysis

## Purpose

Extract simulation results from HydroCNHS, export to CSV for archival,
compute evaluation metrics against observed data, and generate validation
plots. This is the final quality-assurance step before the model is
considered operational.

## Inputs

| Input | Format | Unit | Source |
|-------|--------|------|--------|
| Q_routed | dict of arrays | cms | S5 model.dc.Q_routed |
| Observed streamflow | CSV or DataFrame | cms | USGS/gauge data |
| Simulation dates | string | YYYY/M/D | model.yaml |
| Warmup period | integer | years | User-defined (typically 1–2) |

## Outputs

| Output | Format | Unit | Destination |
|--------|--------|------|-------------|
| Simulated CSV | CSV file | cms | Archive |
| Metrics JSON | JSON file | unitless | Reports |
| Validation plot | PNG file | — | Reports |

## Procedure

### 1. Extract time series

```python
import pandas as pd
import numpy as np
from datetime import datetime

# Build date index
start = datetime.strptime("1981/1/1", "%Y/%m/%d")
n_days = len(model.dc.Q_routed["WSLO"])
dates = pd.date_range(start=start, periods=n_days, freq="D")

# Create DataFrame
df = pd.DataFrame(index=dates)
for outlet in model.dc.Q_routed:
    df[f"Q_{outlet}_cms"] = model.dc.Q_routed[outlet]

# Export
df.to_csv("simulated_streamflow.csv")
```

### 2. Apply warmup period

The first 1–2 years of simulation are typically discarded because the model
needs time for soil moisture, groundwater, and snow storage to equilibrate
from initial conditions.

```python
warmup_years = 2
warmup_days = warmup_years * 365
df_eval = df.iloc[warmup_days:]
```

### 3. Compute evaluation metrics

Use HydroCNHS built-in indicators:

```python
indicator = hydrocnhs.Indicator()

obs = observed_df["Q_WSLO_cms"].values
sim = df_eval["Q_WSLO_cms"].values

metrics = {
    "NSE":   indicator.get_nse(obs, sim),
    "KGE":   indicator.get_kge(obs, sim),
    "iKGE":  indicator.get_ikge(obs, sim),
    "r":     indicator.get_r(obs, sim),
    "r2":    indicator.get_r2(obs, sim),
    "RMSE":  indicator.get_rmse(obs, sim),
    "RSR":   indicator.get_rsr(obs, sim),
    "iNSE":  indicator.get_inse(obs, sim),
    "Cp":    indicator.get_cp(obs, sim),
}
```

Or get all at once:

```python
df_metrics = hydrocnhs.Indicator.cal_indicator_df(obs, sim)
```

### 4. Interpret metrics

| Metric | Range | Good | Acceptable | Poor |
|--------|-------|------|------------|------|
| NSE | (-∞, 1] | > 0.65 | 0.36–0.65 | < 0.36 |
| KGE | (-∞, 1] | > 0.70 | 0.40–0.70 | < 0.40 |
| r | [-1, 1] | > 0.85 | 0.70–0.85 | < 0.70 |
| PBIAS | (-∞, ∞) | |val| < 10% | 10–25% | > 25% |
| RSR | [0, ∞) | < 0.50 | 0.50–0.70 | > 0.70 |

### 5. Generate validation plot

```python
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(14, 4))
ax.plot(dates_eval, obs, color="black", lw=0.8, label="Observed")
ax.plot(dates_eval, sim, color="#2563EB", lw=0.8, label="Simulated")

text = f"NSE={metrics['NSE']:.3f}\nKGE={metrics['KGE']:.3f}\nr={metrics['r']:.3f}"
ax.text(0.98, 0.95, text, transform=ax.transAxes, fontsize=9,
        va="top", ha="right",
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))

ax.set_ylabel("Discharge (cms)")
ax.legend(loc="upper left")
ax.set_title("HydroCNHS Validation — WSLO")
plt.tight_layout()
plt.savefig("validation.png", dpi=150)
```

### 6. Monthly aggregation

For many applications, monthly performance is more meaningful:

```python
df_monthly = df_eval.resample("MS").mean()
obs_monthly = observed_df.resample("MS").mean()

# Compute monthly metrics
nse_monthly = indicator.get_nse(obs_monthly.values, df_monthly.values)
```

## Verification

- NSE > 0 means the model is better than the mean of observed data
- If NSE < 0 but r > 0.7, the model has timing correct but magnitude wrong
  → check unit conversions (precipitation, area)
- If PBIAS > 25%, systematic bias exists → check if PET is being
  over/underestimated
- Compare peak flows specifically: if peaks are damped, routing parameters
  (GShape, GScale) may need adjustment

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| dt_017: No warmup | NSE artificially low | Skip 1–2 years |
| dt_018: Misaligned dates | Metrics meaningless | Align sim/obs date indices |
| dt_001: Wrong prec units | NSE << 0, sim/obs 10× off | Check cm/day |

## Example

Using the parse_output.py tool:

```bash
python parse_output.py \
    --results-pickle results.pickle \
    --observed-csv observed_WSLO.csv \
    --start-date "1981/1/1" \
    --warmup-years 2 \
    --output-csv simulated.csv \
    --metrics-json metrics.json \
    --plot validation.png
```
