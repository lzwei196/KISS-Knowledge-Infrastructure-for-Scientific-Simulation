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

## 1D Column SWC Extraction (FLUXNET Validation)

For NXYZ 1 1 N columns, Liquid_Saturation has shape **(1, 1, N)** — NOT (N,).
Cell ordering: index 0 = bottom (z_min), index N-1 = top (z_max, sensor location).

```python
import h5py, numpy as np

def extract_daily_swc_1d(h5_file, phi):
    """Extract top-cell SWC time series from a 1D NXYZ 1 1 N column."""
    daily_swc = {}
    with h5py.File(h5_file, "r") as f:
        for key in sorted(f.keys()):
            if not key.startswith("Time:"):
                continue
            try:
                day = float(key.replace("Time:", "").replace("d", "").strip())
            except ValueError:
                continue
            grp = f[key]
            if "Liquid_Saturation" not in grp:
                continue
            # CRITICAL: flatten() handles shape (1,1,N) AND (N,) safely
            sat = np.array(grp["Liquid_Saturation"], dtype=float).flatten()
            top_sat = float(sat[-1])   # top cell = highest z = last index
            daily_swc[int(round(day))] = top_sat * phi   # m³/m³
    return daily_swc
```

**Import order**: Always import `netCDF4` BEFORE `h5py` if both are used
in the same script (see dt_025). HDF5 global state conflict causes silent hangs.

```python
import netCDF4   # MUST come first
import h5py
import numpy as np
```

**PFLOTRAN HDF5 time key format** for daily output:
`"Time:  1.00000E+00 d"` — note the double-space, leading spaces, and `d` unit.
Parse with: `float(key.replace("Time:","").replace("d","").strip())`

## FLUXNET SWC Validation Metrics and Targets

For 1D vadose-zone column validation against FLUXNET SWC_F_MDS_1:

| Metric | Formula | Target (acceptable) | Good |
|--------|---------|---------------------|------|
| R | Pearson correlation | > 0.50 | > 0.70 |
| NSE | Nash-Sutcliffe efficiency | > 0.0 | > 0.40 |
| PBIAS | % bias | \|PBIAS\| < 25% | < 10% |
| RMSE | vol. water content | < 0.08 m³/m³ | < 0.05 m³/m³ |

**NSE decomposition** (when R is good but NSE is negative):
```
NSE = 2αR − α² − β²
where α = σ_sim/σ_obs  (variability ratio)
      β = (μ_sim - μ_obs)/σ_obs  (normalized bias)
```
Negative NSE despite R>0.7 almost always means |β| > 0.5 (large systematic bias).
Fix: check PBIAS and address the bias source before reporting NSE.

**Validated FLUXNET sites and results** (from HydroCraft PFLOTRAN KI runs):

| Site | Ecosystem | Period | Config | R | NSE | PBIAS |
|------|-----------|--------|--------|---|-----|-------|
| CN-Din | Subtropical forest, Guangdong, 23.2°N | 2003–2005 | RZ=2.0m, φ=0.43 | 0.761 | -0.174 | +22.2% |
| CN-HaM | Alpine meadow, Qinghai, 37.6°N ✓ | 2002–2004 | RZ=1.0m, φ=0.60 | 0.773 | **+0.471** | **+0.1%** |
| CN-Qia | Plantation forest, Jiangxi, 26.7°N | 2003–2005 | RZ=1.0m, φ=0.43 | 0.575 | -2.06 | +54.2% |

CN-Qia is flagged as structurally biased (subtropical monsoon regime — see dt_026).
CN-HaM with φ=0.60 override (organic alpine meadow) is the recommended reference case.

## Traps

| Symptom | Cause | Fix |
|---|---|---|
| Head offset by ~10.33 m | Forgot to subtract P_atm | h = (P - 101325) / rho_g + z |
| All heads same value | Steady-state with uniform BC | Check if transient was intended |
| Observation file empty | No OBSERVATION block in input | Add OBSERVATION_FILE and REGION |
| Water balance > 5% | Numerical error | Refine grid, reduce dt |
| NaN in late timesteps | Solver diverged silently | Check convergence in .out file |
| TypeError on sat[-1] | Shape (1,1,N) not (N,) | Use .flatten() before indexing |
| SWC constant across time | Wrong HDF5 key parsed | Check key starts with "Time:" and strip "d" |
| h5py hangs | Import after netCDF4 | Import netCDF4 first, then h5py |
| PBIAS=-30% at alpine site | HWSD phi underestimate | Compute phi_est from obs p95/0.95; use φ≈0.60 |
| PBIAS=+50% at monsoon site | No surface runoff in 1D column | Flag site as unsuitable; see dt_026 |

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
