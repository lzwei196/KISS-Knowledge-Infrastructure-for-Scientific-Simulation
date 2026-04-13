# S6: Validation

## Purpose

Evaluate ROMS simulation quality by comparing model output against observations,
reanalysis products, and published benchmarks. Compute domain-appropriate metrics
and produce diagnostic figures to identify model strengths and weaknesses.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| ROMS output | NetCDF | History/average files |
| Observations | CSV/NetCDF | Tide gauges, CTD, ARGO, moorings |
| Satellite data | NetCDF | SST (OSTIA, OISST), SSH (AVISO) |
| Reanalysis | NetCDF | HYCOM, GLORYS for comparison |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Metrics table | JSON/CSV | RMSE, bias, correlation, skill per variable |
| Validation figures | PNG | Time series, Taylor diagrams, profiles |
| Summary report | Text | Overall assessment |

## Procedure

### Step 1: Sea Surface Temperature (SST) validation

Compare against satellite SST (OSTIA, OISST, MODIS):

```python
import numpy as np
from netCDF4 import Dataset

# Load model SST (surface level, time-averaged)
mod = Dataset('roms_avg.nc')
sst_mod = mod.variables['temp'][:, -1, :, :]

# Load satellite SST (interpolated to model grid)
obs = Dataset('oisst_on_roms_grid.nc')
sst_obs = obs.variables['sst'][:]

# Compute spatial mean bias
bias = np.nanmean(sst_mod - sst_obs, axis=(1,2))
rmse = np.sqrt(np.nanmean((sst_mod - sst_obs)**2, axis=(1,2)))
```

**Expected performance:**
- Mean bias < 0.5°C
- RMSE < 1.0°C
- Spatial correlation > 0.9

### Step 2: Sea Surface Height (SSH) / Tides

Compare against tide gauge data:

```python
# Extract model SSH at tide gauge locations
# Compute tidal harmonics using t_tide or utide
from utide import solve

# Model
coef_mod = solve(time_mod, ssh_mod, lat=39.5)
# Observations
coef_obs = solve(time_obs, ssh_obs, lat=39.5)

# Compare M2 amplitude and phase
m2_amp_mod = coef_mod['A'][coef_mod['name'] == 'M2'][0]
m2_amp_obs = coef_obs['A'][coef_obs['name'] == 'M2'][0]
```

**Expected performance:**
- M2 amplitude error < 5 cm
- M2 phase error < 10°
- Subtidal SSH RMSE < 10 cm

### Step 3: Temperature/Salinity profiles

Compare against CTD/ARGO profiles:

```python
# For each profile location and time:
# 1. Find nearest model grid point
# 2. Extract model profile at closest output time
# 3. Interpolate both to common depth levels
# 4. Compute RMSE and bias at each depth

depths_common = np.arange(0, 500, 10)  # 0-500m, 10m intervals
```

**Expected performance:**
- Temperature RMSE < 1°C in upper 200 m
- Salinity RMSE < 0.2 PSU
- Thermocline depth within 20 m

### Step 4: Currents

Compare against ADCP/mooring data:

**Expected performance:**
- Surface current RMSE < 0.15 m/s
- Current direction RMSE < 30°
- Tidal current M2 error < 5 cm/s

### Step 5: Compute summary metrics

```python
def compute_metrics(obs, sim):
    """Compute all standard ocean model metrics."""
    valid = ~np.isnan(obs) & ~np.isnan(sim)
    obs, sim = obs[valid], sim[valid]

    n = len(obs)
    bias = np.mean(sim - obs)
    mae = np.mean(np.abs(sim - obs))
    rmse = np.sqrt(np.mean((sim - obs)**2))
    r = np.corrcoef(obs, sim)[0, 1]
    r2 = r**2

    # Willmott skill
    d_num = np.sum((sim - obs)**2)
    d_den = np.sum((np.abs(sim - np.mean(obs)) + np.abs(obs - np.mean(obs)))**2)
    skill = 1 - d_num / d_den if d_den > 0 else 0

    # Murphy skill score (similar to NSE)
    ss_res = np.sum((obs - sim)**2)
    ss_tot = np.sum((obs - np.mean(obs))**2)
    nse = 1 - ss_res / ss_tot if ss_tot > 0 else 0

    return {
        'n': n,
        'bias': float(bias),
        'mae': float(mae),
        'rmse': float(rmse),
        'r': float(r),
        'r2': float(r2),
        'skill': float(skill),
        'nse': float(nse)
    }
```

### Step 6: Create validation figure

```python
import matplotlib.pyplot as plt

fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# Panel 1: SST time series
axes[0,0].plot(time_obs, sst_obs, 'k-', label='Observed', linewidth=1)
axes[0,0].plot(time_mod, sst_mod, color='#2563EB', label='ROMS', linewidth=1)
axes[0,0].set_ylabel('SST (°C)')
axes[0,0].legend()

# Panel 2: SSH time series
axes[0,1].plot(time_obs, ssh_obs, 'k-', label='Tide Gauge')
axes[0,1].plot(time_mod, ssh_mod, color='#2563EB', label='ROMS')
axes[0,1].set_ylabel('SSH (m)')

# Panel 3: T/S profiles
axes[1,0].plot(temp_obs, -depth_obs, 'k-', label='CTD')
axes[1,0].plot(temp_mod, -depth_mod, color='#2563EB', label='ROMS')
axes[1,0].set_xlabel('Temperature (°C)')
axes[1,0].set_ylabel('Depth (m)')

# Panel 4: Metrics box
metrics_text = f"SST:  RMSE={sst_rmse:.2f}°C, r={sst_r:.3f}\n"
metrics_text += f"SSH:  RMSE={ssh_rmse:.3f} m, r={ssh_r:.3f}\n"
metrics_text += f"Temp: RMSE={temp_rmse:.2f}°C"
axes[1,1].text(0.5, 0.5, metrics_text, transform=axes[1,1].transAxes,
               fontsize=14, verticalalignment='center', horizontalalignment='center',
               bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
axes[1,1].axis('off')

plt.tight_layout()
plt.savefig('validation_summary.png', dpi=150)
```

## Verification

A good validation should:
1. Cover all major model variables (SST, SSH, T/S profiles, currents)
2. Use independent observations (not the same data used for forcing/BC)
3. Span the full simulation period
4. Report quantitative metrics (not just visual comparison)
5. Identify seasonal/regional variations in model skill

## Traps

| Trap | Description | Consequence |
|------|-------------|-------------|
| Comparing different time periods | Model time ≠ obs time | Meaningless metrics |
| Not accounting for staggering | u/v at wrong locations | Spatial offset in comparison |
| Comparing instantaneous vs. averaged | History vs. average file | Smoothed features in averages |
| Ignoring land mask | Including land points | Corrupted statistics |
| Cherry-picking metrics | Only showing correlation | Hiding bias or variance errors |

## Example

```bash
# Extract model SST time series at buoy location
python tools/parse_roms_output.py \
  --input roms_his.nc --variable temp --mode timeseries \
  --lon -73.0 --lat 40.5 --level -1 --output model_sst.csv

# Compare with observations and compute metrics
python -c "
import pandas as pd, numpy as np
mod = pd.read_csv('model_sst.csv')
obs = pd.read_csv('buoy_sst.csv')
rmse = np.sqrt(np.mean((mod['temp'] - obs['sst'])**2))
r = np.corrcoef(mod['temp'], obs['sst'])[0,1]
print(f'SST RMSE: {rmse:.2f} °C, r: {r:.3f}')
"
```
