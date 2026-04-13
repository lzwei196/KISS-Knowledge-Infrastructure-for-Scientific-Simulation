# S7: Output Analysis

## Purpose

Parse PFLOTRAN output files (HDF5, TecPlot observation, mass balance),
extract time series and spatial fields, compute hydraulic metrics, and
generate analysis-ready CSV/figures for model evaluation and calibration.

## Inputs

| Input | Format | Source |
|---|---|---|
| HDF5 output | `.h5` | s6_execution |
| Observation files | `-obs-*.tec` | s6_execution |
| Mass balance file | `-mas.dat` | s6_execution |
| Observed data | CSV | Field measurements |

## Outputs

| Output | Format | Description |
|---|---|---|
| Time series CSV | `.csv` | Observation point data with head conversion |
| Spatial field CSVs | `.csv` | Per-variable, per-timestep |
| Summary JSON | `.json` | Statistics, ranges, validation checks |
| Validation figures | `.png` | Obs vs sim comparison plots |

## Procedure

### Step 1: Parse HDF5 Output

PFLOTRAN HDF5 structure:
```
/Coordinates/X [ncells]
/Coordinates/Y [ncells]
/Coordinates/Z [ncells]
/Time:1.0000e+00 y/Liquid_Pressure [ncells]
/Time:1.0000e+00 y/Liquid_Saturation [ncells]
```

```python
import h5py
f = h5py.File("simulation.h5", "r")
# List time groups
times = [k for k in f.keys() if k.startswith("Time:")]
# Read pressure at final time
pressure = f[times[-1]]["Liquid_Pressure"][:]
```

### Step 2: Convert Pressure to Hydraulic Head

**CRITICAL**: PFLOTRAN stores absolute liquid pressure (Pa), not head (m).

```python
# h = (P - P_atm) / (rho * g) + z
P_atm = 101325.0
rho_g = 998.2 * 9.80665  # = 9786.4 Pa/m

head_m = (pressure_pa - P_atm) / rho_g + elevation_m
```

Common mistake: forgetting to subtract atmospheric pressure, which offsets
all heads by ~10.33 m.

### Step 3: Parse TecPlot Observation Files

Format:
```
TITLE = ""
VARIABLES = "Time [y]","Liq. Pressure [Pa]","Liq. Saturation [-]"
ZONE T="Observation: well_1"
1.000000e-03  2.058000e+05  9.876543e-01
```

Extract columns, convert time, and add derived columns (head).

### Step 4: Compute Water Balance

From mass balance file:
- Total inflow (recharge + lateral BC)
- Total outflow (wells + seepage + lateral)
- Storage change
- Balance error = |inflow - outflow - storage_change| / |inflow|

**Must be < 1%** for a trustworthy simulation.

### Step 5: Compare to Observations

For groundwater head validation:

```python
import numpy as np

def nse(obs, sim):
    """Nash-Sutcliffe Efficiency"""
    return 1 - np.sum((obs - sim)**2) / np.sum((obs - np.mean(obs))**2)

def kge(obs, sim):
    """Kling-Gupta Efficiency"""
    r = np.corrcoef(obs, sim)[0, 1]
    alpha = np.std(sim) / np.std(obs)
    beta = np.mean(sim) / np.mean(obs)
    return 1 - np.sqrt((r - 1)**2 + (alpha - 1)**2 + (beta - 1)**2)

def pbias(obs, sim):
    """Percent Bias (%)"""
    return 100 * np.sum(sim - obs) / np.sum(obs)

def rmse(obs, sim):
    """Root Mean Square Error"""
    return np.sqrt(np.mean((obs - sim)**2))
```

### Step 6: Generate Figures

Standard validation plot:
- Time series: observed (black dots) vs simulated (blue line)
- Metrics box in top-right corner
- 1:1 scatter plot
- Residual histogram

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

# Time series
ax1.plot(obs_time, obs_head, 'ko', markersize=3, label='Observed')
ax1.plot(sim_time, sim_head, '-', color='#2563EB', label='Simulated')
ax1.set_xlabel('Time (years)')
ax1.set_ylabel('Hydraulic Head (m)')
ax1.legend()

# Metrics box
metrics_text = f"NSE = {nse_val:.3f}\nKGE = {kge_val:.3f}\nRMSE = {rmse_val:.2f} m"
ax1.text(0.98, 0.98, metrics_text, transform=ax1.transAxes,
         va='top', ha='right', fontsize=9,
         bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

# 1:1 plot
ax2.scatter(obs_head, sim_head, c='#2563EB', alpha=0.5, s=10)
ax2.plot([min_h, max_h], [min_h, max_h], 'k--', label='1:1 line')
ax2.set_xlabel('Observed Head (m)')
ax2.set_ylabel('Simulated Head (m)')

plt.savefig('validation.png', dpi=150, bbox_inches='tight')
```

## Verification

1. Pressure values > 0 Pa (no vacuum)
2. Saturation in [0, 1]
3. Head values physically reasonable for the site
4. Water balance error < 1%
5. No NaN in output arrays
6. Observation records match expected time range

## Traps

| Symptom | Cause | Fix |
|---|---|---|
| Head offset by ~10.33 m | Forgot to subtract P_atm | h = (P - 101325) / rho_g + z |
| All heads same value | Steady-state with uniform BC | Check if transient was intended |
| Observation file empty | No OBSERVATION block in input | Add OBSERVATION_FILE and REGION |
| Water balance > 5% | Numerical error | Refine grid, reduce dt |
| NaN in late timesteps | Solver diverged silently | Check convergence in .out file |

## Example

```bash
python parse_pflotran_output.py \
    --hdf5-file bengbu_richards.h5 \
    --obs-file bengbu_richards-obs-0.tec \
    --output-dir results/

# Results in:
# results/observations.csv
# results/summary.json
# results/Liquid_Pressure/t_*.csv
```
