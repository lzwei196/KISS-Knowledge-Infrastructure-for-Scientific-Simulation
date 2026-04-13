# S6: Output Extraction and Analysis

## Purpose

Extract model outputs from SuperflexPy simulation results, convert to standardized
formats (CSV, JSON), and compute hydrological performance metrics for model evaluation,
calibration assessment, and inter-model comparison.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| Q_sim | numpy.ndarray or JSON | Simulated streamflow (mm/d) |
| Q_obs | numpy.ndarray or JSON | Observed streamflow (mm/d) |
| Dates | list of strings | Date labels for time series |
| Warmup period | integer | Timesteps to exclude from metrics |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Streamflow CSV | date, Q_sim, Q_obs | Standardized time series |
| Metrics JSON | NSE, KGE, PBIAS, RMSE, r | Performance scores |
| Summary statistics | JSON | Mean, max, min, std |

## Procedure

### Step 1: Extract simulated streamflow

```python
Q_sim = model_output[0]  # numpy array, mm/d
```

### Step 2: Align with observations

Both arrays must have the same length and temporal alignment. If the model was
run for a longer warmup period, trim the first N timesteps before comparison.

### Step 3: Compute performance metrics

```python
# Nash-Sutcliffe Efficiency (NSE)
NSE = 1 - sum((Q_obs - Q_sim)**2) / sum((Q_obs - mean(Q_obs))**2)

# Kling-Gupta Efficiency (KGE)
r = correlation(Q_obs, Q_sim)
alpha = std(Q_sim) / std(Q_obs)
beta = mean(Q_sim) / mean(Q_obs)
KGE = 1 - sqrt((r-1)**2 + (alpha-1)**2 + (beta-1)**2)

# Percent Bias (PBIAS)
PBIAS = 100 * sum(Q_sim - Q_obs) / sum(Q_obs)

# Root Mean Square Error (RMSE)
RMSE = sqrt(mean((Q_obs - Q_sim)**2))
```

### Step 4: Export results

```bash
python ki/tools/parse_output.py \
    --input results.json \
    --output streamflow.csv \
    --warmup 365
```

### Performance benchmarks

| Rating | NSE | KGE | |PBIAS| |
|--------|-----|-----|----|
| Very good | > 0.75 | > 0.75 | < 10% |
| Good | 0.65–0.75 | 0.5–0.75 | 10–15% |
| Satisfactory | 0.50–0.65 | 0.3–0.5 | 15–25% |
| Unsatisfactory | < 0.50 | < 0.3 | > 25% |

### Unit conversion for volumetric flow

To convert Q from mm/d to m³/s:
```python
Q_m3s = Q_mm_d * area_km2 * 1e6 / (86400 * 1000)
# = Q_mm_d * area_km2 / 86.4
```

## Verification

- [ ] NSE is computed on evaluation period only (after warmup)
- [ ] Q_obs and Q_sim arrays have identical length
- [ ] No NaN values contaminate metric calculations
- [ ] PBIAS sign convention: positive = overestimation
- [ ] Water balance check: P - ET - Q ≈ ΔS

## Traps

| Trap ID | Description | Impact |
|---------|-------------|--------|
| dt_001 | Q units wrong when computing metrics | NSE/KGE meaningless |
| dt_013 | Area in m² instead of km² | Volumetric Q off by 1e6 |
| dt_014 | Warmup period too short | Initial transient biases metrics |

## Example

```python
import numpy as np

# After running model
Q_sim = Q[0]  # mm/d
Q_obs = observed_data  # mm/d

# Exclude 1-year warmup
warmup = 365
Q_sim_eval = Q_sim[warmup:]
Q_obs_eval = Q_obs[warmup:]

# NSE
nse = 1 - np.sum((Q_obs_eval - Q_sim_eval)**2) / np.sum((Q_obs_eval - Q_obs_eval.mean())**2)
print(f"NSE = {nse:.3f}")

# KGE
r = np.corrcoef(Q_obs_eval, Q_sim_eval)[0, 1]
alpha = Q_sim_eval.std() / Q_obs_eval.std()
beta = Q_sim_eval.mean() / Q_obs_eval.mean()
kge = 1 - np.sqrt((r-1)**2 + (alpha-1)**2 + (beta-1)**2)
print(f"KGE = {kge:.3f}")
```
