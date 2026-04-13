# S7: Calibration — Parameter Estimation for MODFLOW Models

## Purpose

Adjust model parameters (primarily K, recharge, boundary conductances) to match observed data (head measurements, stream baseflow, spring discharge). Manual and automated calibration approaches.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| Observed heads | CSV (well_id, x, y, layer, head_m) | Water level measurements |
| Observed baseflow | CSV (date, discharge_m3_day) | Stream/spring discharge |
| Model output | .hds, .bud | Simulated results |
| Parameter ranges | JSON | Min/max for each parameter |

## Outputs

| Output | Description |
|--------|-------------|
| Calibrated parameters | K, recharge, conductance values |
| Residual statistics | RMSE, MAE, bias, R² |
| Calibration plots | Observed vs simulated scatter, spatial residuals |
| Parameter sensitivity | Which parameters matter most |

## Metrics

### Head Calibration Metrics

```python
import numpy as np

def compute_metrics(observed, simulated):
    """Compute calibration metrics for head data."""
    residuals = simulated - observed
    n = len(observed)

    rmse = np.sqrt(np.mean(residuals**2))
    mae = np.mean(np.abs(residuals))
    bias = np.mean(residuals)
    r2 = 1 - np.sum(residuals**2) / np.sum((observed - np.mean(observed))**2)

    # Scaled RMSE (normalized by observed range)
    nrmse = rmse / (np.max(observed) - np.min(observed))

    return {
        'RMSE_m': rmse,
        'MAE_m': mae,
        'Bias_m': bias,
        'R2': r2,
        'NRMSE': nrmse,
        'n_obs': n
    }
```

### Calibration Targets

| Metric | Acceptable | Good | Excellent |
|--------|-----------|------|-----------|
| RMSE | < 5 m | < 2 m | < 1 m |
| NRMSE | < 0.15 | < 0.10 | < 0.05 |
| R² | > 0.7 | > 0.9 | > 0.95 |
| Bias | < ±2 m | < ±1 m | < ±0.5 m |
| Water balance | < 5% | < 1% | < 0.5% |

## Manual Calibration Procedure

1. **Run base model** with best-estimate parameters
2. **Compare** simulated vs observed heads
3. **Identify systematic bias**:
   - Heads too high everywhere → reduce recharge or increase K
   - Heads too low everywhere → increase recharge or decrease K
   - Heads wrong near rivers → adjust river conductance
   - Heads wrong in one area → adjust local K
4. **Adjust one parameter at a time** (±50%, ±10×)
5. **Re-run and compare**
6. **Iterate** until metrics are acceptable

### Sensitivity Parameters (ranked by typical impact)

1. **Hydraulic conductivity (K)** — most sensitive, adjust first
2. **Recharge rate** — second most sensitive
3. **River/drain conductance** — affects head near surface water
4. **Storage (Ss, Sy)** — only for transient models
5. **K anisotropy (Kv/Kh)** — affects vertical gradients

## Automated Calibration with PEST

```python
# FloPy can generate PEST input files
# Requires pyemu or PEST separately
import pyemu

# Define parameters
pst = pyemu.Pst.from_io_files(
    tpl_files=['model.npf.tpl'],
    in_files=['model.npf'],
    ins_files=['heads.ins'],
    out_files=['heads.csv']
)

# Set parameter bounds
par = pst.parameter_data
par.loc['hk', 'parlbnd'] = 0.01  # min K
par.loc['hk', 'parubnd'] = 100.0  # max K

pst.write('model.pst')
```

## Verification

- [ ] RMSE < 5 m (or < 10% of head range)
- [ ] R² > 0.8
- [ ] No systematic spatial bias in residuals
- [ ] Water balance < 1%
- [ ] Calibrated parameters are physically reasonable
- [ ] Model reproduces observed gradients (flow direction)

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Overfitting with too many parameters | Good fit but poor prediction | Use regularization, fewer zones |
| Unit mismatch in observations | Large systematic residuals | Ensure obs heads in same datum/units as model |
| Non-unique solutions | Multiple parameter sets fit equally | Use multiple observation types |
| Comparing wrong time/layer | Poor fit despite correct parameters | Match observation time to correct stress period |

## Example

```python
import flopy
import numpy as np

# Load observed heads
obs = np.array([
    # (row, col, observed_head_m)
    (5, 10, 42.3),
    (15, 8, 38.7),
    (25, 12, 35.1),
])

# Read simulated
hds = flopy.utils.HeadFile('model.hds')
head = hds.get_data(kstpkper=(0, 0))

# Extract simulated at observation locations
sim_heads = [head[0, int(r), int(c)] for r, c, _ in obs]
obs_heads = [h for _, _, h in obs]

# Compute metrics
residuals = np.array(sim_heads) - np.array(obs_heads)
rmse = np.sqrt(np.mean(residuals**2))
print(f"RMSE = {rmse:.2f} m")
```
