# Stage 6: Output Analysis

## Purpose

Parse and analyze GeoClaw simulation output files.  Extract solution
variables (water depth, velocity, surface elevation) from the AMR grid
output and gauge time series.  Convert to formats suitable for comparison
with observations, statistical analysis, and visualization.

## Prerequisites

- Stage 5 (execution) completed — `_output/` directory contains fort.q files
- Python with NumPy and matplotlib installed
- Optionally: clawpack visclaw for built-in plotting

## Inputs

| Input | Format | Notes |
|-------|--------|-------|
| `_output/fort.qNNNN` | ASCII or binary | Solution variables per frame |
| `_output/fort.tNNNN` | ASCII | Frame metadata |
| `_output/fort.gauge` | ASCII | Gauge time series |
| `_output/fgmaxNNNN.txt` | ASCII | Maximum value grids (optional) |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Frame summary CSV | CSV | time, n_grids, h_max, speed_max per frame |
| Gauge time series CSV | CSV | time, h, hu, hv, eta per gauge |
| Maximum inundation map | GeoTIFF/CSV | max depth and arrival time |
| Validation metrics | JSON | NSE, RMSE, correlation vs observations |

## Procedure

1. **Parse output with the output parser:**
   ```bash
   python ki/tools/parse_geoclaw_output.py \
     --output-dir _output \
     --outfile results.csv \
     --format csv \
     --json-output parse_report.json
   ```

2. **Extract gauge time series.**  The parser extracts gauge data as
   separate sections in the CSV.  For programmatic access:
   ```python
   import numpy as np

   # Read gauge file directly
   data = np.loadtxt('_output/fort.gauge')
   gauge_1 = data[data[:, 0] == 1]  # Filter gauge ID = 1
   time = gauge_1[:, 2]              # Time in seconds
   eta = gauge_1[:, 5]               # Surface elevation in meters
   ```

3. **Compute derived quantities.**
   ```python
   h = gauge_1[:, 3]    # Water depth (m)
   hu = gauge_1[:, 4]   # x-momentum (m²/s)
   hv = gauge_1[:, 5]   # y-momentum (m²/s)

   # Velocity (avoid division by zero in dry cells)
   dry = h < 1e-6
   u = np.where(dry, 0.0, hu / h)     # x-velocity (m/s)
   v = np.where(dry, 0.0, hv / h)     # y-velocity (m/s)
   speed = np.sqrt(u**2 + v**2)        # Total speed (m/s)
   ```

4. **Compare with observations.**  For tsunami validation, common
   observational data sources include:
   - DART buoy records (surface elevation time series)
   - Tide gauge records
   - Post-tsunami field surveys (runup heights, inundation extent)
   - Satellite altimetry (Jason-1, etc.)

5. **Compute validation metrics:**
   ```python
   # Nash-Sutcliffe Efficiency
   def nse(obs, sim):
       return 1 - np.sum((obs - sim)**2) / np.sum((obs - np.mean(obs))**2)

   # Root Mean Square Error
   def rmse(obs, sim):
       return np.sqrt(np.mean((obs - sim)**2))

   # Percent Bias
   def pbias(obs, sim):
       return 100 * np.sum(sim - obs) / np.sum(obs)

   # Correlation coefficient
   r = np.corrcoef(obs, sim)[0, 1]
   ```

6. **Create visualization:**
   ```python
   import matplotlib.pyplot as plt

   fig, ax = plt.subplots(figsize=(10, 4))
   ax.plot(time_obs / 3600, eta_obs, 'k-', label='Observed', linewidth=1.5)
   ax.plot(time_sim / 3600, eta_sim, '-', color='#2563EB', label='GeoClaw', linewidth=1.0)
   ax.set_xlabel('Time (hours)')
   ax.set_ylabel('Surface elevation (m)')
   ax.legend()
   ax.set_title('Gauge Comparison')

   # Add metrics box
   metrics_text = f'NSE = {nse_val:.3f}\nRMSE = {rmse_val:.3f} m\nr = {r:.3f}'
   ax.text(0.98, 0.95, metrics_text, transform=ax.transAxes,
           fontsize=9, va='top', ha='right',
           bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
   fig.savefig('validation.png', dpi=150, bbox_inches='tight')
   ```

## Verification

- [ ] All expected frames are present in the output
- [ ] No NaN or Inf values in any frame
- [ ] Maximum water depth is physically plausible
- [ ] Maximum speed is reasonable (< 200 m/s for tsunami, < 50 m/s for surge)
- [ ] Gauge time series shows expected wave arrival time
- [ ] If comparing to observations: NSE > 0 (better than mean)

## Traps

| Trap | Triplet | Impact |
|------|---------|--------|
| Confusing hu (momentum) with u (velocity) | — | Velocity appears too large |
| Not accounting for AMR levels in spatial averaging | — | Statistics biased by coarse grids |
| Time in seconds but plotting in hours without conversion | dt_003 | X-axis labels wrong |
| Gauge outside domain | dt_016 | Empty or missing gauge file |
| h_max decreasing by >99% | dt_004 | Excessive Manning friction |
| NaN in output | dt_011 | CFL violation or extreme forcing |

## Example

Full analysis pipeline for bowl-slosh test case:

```bash
# Parse output
python ki/tools/parse_geoclaw_output.py \
  --output-dir $CLAW/geoclaw/examples/tsunami/bowl-slosh/_output \
  --outfile bowl_slosh_results.csv \
  --format csv

# Quick check
head -20 bowl_slosh_results.csv

# Expected output:
# frame,time_s,n_grids,h_max_m,speed_max_ms
# 0,0.000000,5,0.100000,0.000000
# 1,90.000000,5,0.095432,0.312567
# ...
```

The bowl-slosh example has an analytical solution: the water surface oscillates
as a paraboloid in a parabolic bowl.  Maximum depth should remain approximately
constant over time (no energy loss without friction).
