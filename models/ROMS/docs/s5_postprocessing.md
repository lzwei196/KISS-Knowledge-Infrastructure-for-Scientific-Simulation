# S5: Post-processing and Analysis

## Purpose

Extract, analyze, and visualize ROMS output from NetCDF history, average, and
station files. Compute derived quantities (vorticity, transport, heat content),
extract time series at observation locations, and prepare data for validation.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| `roms_his.nc` | NetCDF | History file (snapshots) |
| `roms_avg.nc` | NetCDF | Time-averaged fields |
| `roms_sta.nc` | NetCDF | Station point data |
| `roms_grid.nc` | NetCDF | Grid file (for coordinates and bathymetry) |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Time series CSV | CSV | Variable vs. time at observation points |
| Vertical profiles | CSV | Variable vs. depth at locations |
| Surface maps | PNG | 2D field snapshots |
| Statistics | JSON | Domain-wide min/max/mean/std |

## Procedure

### Step 1: Extract time series at observation locations

```bash
python tools/parse_roms_output.py \
  --input roms_his.nc \
  --variable temp \
  --mode timeseries \
  --lon -74.0 --lat 39.5 \
  --level -1 \
  --output sst_station1.csv
```

This extracts surface (level=-1) temperature at the nearest grid point to
(74°W, 39.5°N).

### Step 2: Extract vertical profiles

```bash
python tools/parse_roms_output.py \
  --input roms_his.nc \
  --variable temp,salt \
  --mode profile \
  --lon -74.0 --lat 39.5 \
  --time-idx -1 \
  --output profile_station1.csv
```

### Step 3: Compute derived quantities

**Sea Surface Temperature (SST):**
```python
from netCDF4 import Dataset
ds = Dataset('roms_his.nc')
sst = ds.variables['temp'][:, -1, :, :]  # surface level
```

**Relative vorticity:**
```python
u = ds.variables['u'][:, -1, :, :]
v = ds.variables['v'][:, -1, :, :]
# dvdx - dudy on PSI points
dvdx = np.diff(v, axis=2)  # along XI
dudy = np.diff(u, axis=1)  # along ETA
vort = dvdx[:, :, :] - dudy[:, :, :]
```

**Volume transport through a section:**
```python
# Transport through a zonal section at j=j0
u_sec = ds.variables['u'][:, :, j0, :]  # (time, s_rho, xi_u)
# Integrate over depth and width
transport = np.sum(u_sec * dz * dy, axis=(1,2))  # m³/s → Sverdrup / 1e6
```

**Mixed layer depth (density criterion):**
```python
rho = ds.variables['rho'][:, :, j0, i0]  # density profile
rho_surf = rho[:, -1]  # surface density
for k in range(N-1, -1, -1):
    if rho[:, k] - rho_surf > 0.03:  # 0.03 kg/m³ criterion
        mld = depth[:, k]
        break
```

### Step 4: Domain statistics

```bash
python tools/parse_roms_output.py \
  --input roms_his.nc \
  --variable temp,salt,zeta \
  --mode statistics \
  --output domain_stats.json
```

### Step 5: Surface maps

```python
import matplotlib.pyplot as plt
from netCDF4 import Dataset
import numpy as np

ds = Dataset('roms_his.nc')
grd = Dataset('roms_grid.nc')

lon = grd.variables['lon_rho'][:]
lat = grd.variables['lat_rho'][:]
sst = ds.variables['temp'][-1, -1, :, :]  # last time, surface
mask = grd.variables['mask_rho'][:]
sst = np.ma.masked_where(mask == 0, sst)

fig, ax = plt.subplots(figsize=(10, 8))
pc = ax.pcolormesh(lon, lat, sst, cmap='RdYlBu_r', vmin=5, vmax=30)
ax.set_xlabel('Longitude')
ax.set_ylabel('Latitude')
ax.set_title('Sea Surface Temperature (°C)')
plt.colorbar(pc, ax=ax, label='Temperature (°C)')
plt.savefig('sst_map.png', dpi=150, bbox_inches='tight')
```

### Step 6: Compare with observations

Extract model values at observation locations and compute metrics:

```python
import numpy as np

def compute_rmse(obs, sim):
    return np.sqrt(np.mean((obs - sim)**2))

def compute_bias(obs, sim):
    return np.mean(sim - obs)

def compute_correlation(obs, sim):
    return np.corrcoef(obs, sim)[0, 1]

def compute_skill(obs, sim):
    """Willmott skill score (0-1, 1=perfect)"""
    num = np.sum((sim - obs)**2)
    den = np.sum((np.abs(sim - np.mean(obs)) + np.abs(obs - np.mean(obs)))**2)
    return 1 - num / den if den > 0 else 0
```

## Verification

After post-processing, check:
1. Time series are continuous (no gaps unless expected)
2. Values are in physical range (T: -2 to 35°C, S: 0–42 PSU)
3. Station locations match intended coordinates
4. Vertical profiles show expected structure (thermocline, halocline)
5. Surface maps show coherent spatial patterns

## Traps

| Trap | Description | Consequence |
|------|-------------|-------------|
| S-coordinate depth error | Wrong formula for actual depths | Profiles at wrong depth |
| Staggered grid mixing | Averaging u/v to wrong points | Spatial offsets in maps |
| Masked values not handled | Land values contaminate statistics | Wrong means/correlations |
| Time units confusion | Seconds vs. days vs. datetime | Wrong time axis on plots |
| Level indexing | 0=bottom in ROMS (k=0 is deepest) | Surface/bottom swapped |

## Example

```bash
# Full post-processing pipeline
python tools/parse_roms_output.py \
  --input roms_his.nc --variable temp --mode timeseries \
  --lon -74.0 --lat 39.5 --level -1 --output sst_ts.csv

python tools/parse_roms_output.py \
  --input roms_his.nc --variable temp,salt --mode statistics \
  --output domain_stats.json --format json
```
