# Stage 5: Output Analysis and Post-processing

## Purpose

Parse COSIPY output netCDF files, extract time series and spatial fields, compute summary statistics, and create visualizations of energy balance, mass balance, and snowpack evolution.

## Inputs

| Input | Source | Format |
|-------|--------|--------|
| Result netCDF | Stage 4 output | netCDF4 |
| Restart netCDF (optional) | Stage 4 output | netCDF4 |
| Observed data (optional) | Stakes / AWS / remote sensing | CSV |

## Outputs

| Output | Type | Description |
|--------|------|-------------|
| Summary statistics | Console / JSON | MB, energy balance, snowpack state |
| Time series CSV | CSV | Selected variables over time |
| Spatial plots | PNG | Field maps of MB, snow height, albedo |
| Profile plots | PNG | Vertical structure (T, density, LWC) |
| Validation metrics | Console / CSV | RMSE, bias, correlation vs. observations |

## Procedure

### 1. Parse output with KI tool

```bash
# Summary mode
python ki/tools/parse_output.py \
    -i data/output/Zhadang_ERA5_20090101-20090110.nc \
    --mode summary

# Extract time series to CSV
python ki/tools/parse_output.py \
    -i data/output/Zhadang_ERA5_20090101-20090110.nc \
    --mode timeseries \
    --output results.csv

# Domain average time series
python ki/tools/parse_output.py \
    -i data/output/Zhadang_ERA5_20090101-20090110.nc \
    --mode timeseries \
    --domain-mean \
    --output domain_mean.csv
```

### 2. Built-in plotting

```bash
# Spatial field plots
cosipy-plot-field

# Vertical profile plots (requires full_field=true output)
cosipy-plot-profile

# VTK 3D visualization
cosipy-plot-vtk
```

### 3. Key output variables to check

#### Mass balance (m w.e. per timestep)
| Variable | Typical range | Indicates |
|----------|--------------|-----------|
| MB | -0.01 to +0.01 | Total mass balance |
| surfMB | -0.01 to +0.01 | Surface mass balance (melt-accumulation) |
| intMB | -0.001 to +0.001 | Internal mass balance (refreeze-subsurf melt) |
| SNOWFALL | 0 to 0.005 | Solid precipitation (m w.e.) |
| surfM | 0 to 0.01 | Surface melt |
| Q | 0 to 0.01 | Runoff |

#### Energy balance (W/m2)
| Variable | Typical range | Indicates |
|----------|--------------|-----------|
| G (input) | 0-1000 | Incoming shortwave |
| LWin | 150-350 | Incoming longwave |
| LWout | -250 to -350 | Outgoing longwave (negative) |
| H | -100 to +100 | Sensible heat (positive = toward surface) |
| LE | -100 to +50 | Latent heat (negative = sublimation/evap) |
| B | -50 to +50 | Ground heat flux |
| ME | 0 to 500 | Melt energy (positive when melting) |

#### Snowpack state
| Variable | Typical range | Indicates |
|----------|--------------|-----------|
| SNOWHEIGHT | 0 to 5 m | Snow depth |
| TOTALHEIGHT | 10 to 50 m | Total column (snow + ice) |
| TS | 240 to 273 K | Surface temperature |
| ALBEDO | 0.3 to 0.85 | Surface albedo |
| LAYERS | 10 to 200 | Number of vertical layers |

### 4. Validation against observations

```python
import pandas as pd
import numpy as np

# Load simulated and observed
sim = pd.read_csv('results.csv', index_col=0, parse_dates=True)
obs = pd.read_csv('stake_data.csv', index_col=0, parse_dates=True)

# Compute metrics
common = sim.index.intersection(obs.index)
sim_vals = sim.loc[common, 'MB'].cumsum()
obs_vals = obs.loc[common, 'cumMB']

rmse = np.sqrt(np.mean((sim_vals - obs_vals)**2))
bias = np.mean(sim_vals - obs_vals)
r = np.corrcoef(sim_vals, obs_vals)[0, 1]

print(f'RMSE: {rmse:.3f} m w.e.')
print(f'Bias: {bias:.3f} m w.e.')
print(f'r: {r:.3f}')
```

## Verification

```bash
# Quick sanity checks on output
python -c "
import xarray as xr
ds = xr.open_dataset('data/output/Zhadang_ERA5_20090101-20090110.nc')

# Check mass balance sign convention
if 'MB' in ds:
    mb_sum = float(ds.MB.sum())
    print(f'Cumulative MB: {mb_sum:.4f} m w.e.')
    print(f'  Positive = mass gain, Negative = mass loss')

# Check surface temperature never exceeds melting point
if 'TS' in ds:
    ts_max = float(ds.TS.max())
    print(f'Max surface T: {ts_max:.2f} K (should be <= 273.16)')
    if ts_max > 273.5:
        print('  WARNING: Surface temp exceeds melting point!')

# Check albedo range
if 'ALBEDO' in ds:
    a_min, a_max = float(ds.ALBEDO.min()), float(ds.ALBEDO.max())
    print(f'Albedo range: {a_min:.3f} to {a_max:.3f}')
    print(f'  Expected: 0.3 (ice) to 0.85 (fresh snow)')

ds.close()
"
```

## Traps

1. **Surface temperature > 273.16 K**: COSIPY constrains surface temperature to the melting point. If TS consistently hits 273.16, the surface is melting. If TS > 273.16 appears, there is a numerical issue.

2. **All-NaN output**: Usually means the MASK is all zeros or the simulation period is outside the input data range. Check `MASK.sum()` and time overlap.

3. **Cumulative MB sign convention**: Positive MB = mass gain (accumulation dominant). Negative MB = mass loss (melt dominant). For most glaciers in summer, MB should be strongly negative.

4. **SNOWFALL output is in m w.e., not m snow**: The output `SNOWFALL` variable is `SNOWFALL_input * (density / water_density)`, i.e., converted to meters water equivalent. This differs from the input SNOWFALL which is in meters of snow height.

5. **Layer output requires full_field=true**: Variables like LAYER_HEIGHT, LAYER_RHO, LAYER_T are only written when `full_field = true` in config.toml. This significantly increases output file size.

## Example

```bash
# Full output analysis workflow
python ki/tools/parse_output.py -i data/output/Zhadang_ERA5_20090101-20090110.nc --mode both --output results.csv

# Plot time series
python -c "
import pandas as pd, matplotlib.pyplot as plt
df = pd.read_csv('results.csv', index_col=0, parse_dates=True)
fig, axes = plt.subplots(3, 1, figsize=(12, 10))
df['MB'].cumsum().plot(ax=axes[0], title='Cumulative Mass Balance (m w.e.)')
df['SNOWHEIGHT'].plot(ax=axes[1], title='Snow Height (m)')
df['TS'].plot(ax=axes[2], title='Surface Temperature (K)')
plt.tight_layout()
plt.savefig('cosipy_results.png', dpi=150)
"
```
