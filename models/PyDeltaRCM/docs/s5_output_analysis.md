# Stage 5: Output and Analysis

## Purpose

Save model state to NetCDF files, generate figures, manage checkpoints, and analyze delta evolution over time.

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Model state arrays | Stages 2-4 | eta, stage, depth, velocity, discharge, sand_frac |
| `save_dt` | Config | Output interval in seconds (default 86400) |
| `save_*_grids` flags | Config | Which variables to save |
| `save_*_figs` flags | Config | Which figures to generate |
| `save_checkpoint` | Config | Enable checkpoint saving |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `pyDeltaRCM_output.nc` | NetCDF4 | Gridded time series |
| `eta_*.png` (etc.) | PNG images | Per-timestep figures |
| `pyDeltaRCM_checkpoint.npz` | NumPy archive | Checkpoint for resume |
| `pyDeltaRCM_*.log` | Text | Run log |

## Procedure

### 1. Data Output (`output_data`)

Called every timestep. Saves data only when elapsed model time since last save exceeds `save_dt`:

```python
if self._save_time_since_data >= self.save_dt:
    # Save all enabled grid variables to NetCDF
    # Save all enabled figures to disk
    self._save_time_since_data = 0
    self._save_iter += 1
```

### 2. Grid Variables (NetCDF)

For each enabled `save_*_grids` flag, the corresponding array is written to the NetCDF file at the current time index:

| Flag | Variable | Array |
|------|----------|-------|
| `save_eta_grids` | `eta` | Bed elevation |
| `save_stage_grids` | `stage` | Water surface |
| `save_depth_grids` | `depth` | Water depth |
| `save_discharge_grids` | `discharge` | `(qx² + qy²)^0.5` |
| `save_velocity_grids` | `velocity` | `(ux² + uy²)^0.5` |
| `save_sedflux_grids` | `sedflux` | Sediment flux `qs` |
| `save_sandfrac_grids` | `sandfrac` | Sand fraction |

If `save_discharge_components` or `save_velocity_components` is True, x/y components are also saved.

### 3. Figure Output

If `save_*_figs` is True, matplotlib figures are generated and saved. Figures are either sequential (numbered) or overwritten (latest only), controlled by `save_figs_sequential`.

### 4. Checkpoint Output (`output_checkpoint`)

If `save_checkpoint = True` and `checkpoint_dt` is set:
- Saves all model arrays and random state to `pyDeltaRCM_checkpoint.npz`
- Enables resume via `resume_checkpoint: true` in config

### 5. Post-Run Analysis

Use `tools/parse_output.py` to extract metrics from the NetCDF:

```bash
python tools/parse_output.py deltaRCM_Output/pyDeltaRCM_output.nc -o results/
```

This produces:
- `delta_metrics.csv`: Time series of area, volume, shoreline length, channels
- `eta_snapshot_*.png`: Bed elevation snapshots
- `parse_summary.json`: Summary statistics

## Verification

- [ ] NetCDF file grows with each save interval
- [ ] Time dimension in NetCDF matches expected number of saves
- [ ] Variable ranges are physical (eta: -10 to +5 m, depth: 0 to h0)
- [ ] Figures show delta progradation over time
- [ ] Delta area increases monotonically (without SLR/subsidence)

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| `save_dt` too small | Huge NetCDF file, slow run | Use save_dt = 86400 (1 model day) or larger |
| No save flags enabled | Empty NetCDF | Enable at least `save_eta_grids: true` |
| `clobber_netcdf: false` (default) | Error if output exists | Set `clobber_netcdf: true` or use new out_dir |
| Checkpoint not saved | Cannot resume | Enable `save_checkpoint: true` with `checkpoint_dt` |
| Figure saving slows run | 10x slower | Disable `save_*_figs` for production runs |

## Example: Complete Analysis Pipeline

```python
import pyDeltaRCM
import netCDF4
import numpy as np
import matplotlib.pyplot as plt

# Run model
delta = pyDeltaRCM.DeltaModel(
    out_dir='analysis_demo',
    save_eta_grids=True,
    save_depth_grids=True,
    save_dt=86400,
    seed=42
)

for t in range(50):
    delta.update()
delta.finalize()

# Read output
ds = netCDF4.Dataset('analysis_demo/pyDeltaRCM_output.nc')
eta = ds.variables['eta'][:]
times = ds.variables['seconds'][:]

# Plot delta growth
fig, axes = plt.subplots(1, 3, figsize=(15, 5))
for i, t_idx in enumerate([0, len(times)//2, -1]):
    ax = axes[i]
    im = ax.pcolormesh(eta[t_idx], cmap='terrain', vmin=-5, vmax=2)
    ax.set_title(f'Day {times[t_idx]/86400:.0f}')
    ax.set_aspect('equal')
plt.colorbar(im, ax=axes, label='Elevation (m)')
plt.savefig('delta_evolution.png', dpi=150)

ds.close()
```

## Stratigraphy

If `save_sandfrac_grids=True` and `save_eta_grids=True`, stratigraphy can be reconstructed:

```python
# See strat_preprocess.py in repo root
# Converts saved surfaces into 3D stratigraphy volume
# Output: stratigraphy.npy (nz × nx × ny array of sand fraction)
```

The stratigraphy records the sand fraction at each bed elevation over time, allowing 3D reconstruction of delta internal structure.
