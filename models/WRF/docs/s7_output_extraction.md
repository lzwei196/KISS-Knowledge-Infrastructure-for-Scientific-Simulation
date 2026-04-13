# Stage 7: Output Extraction & Analysis

## Purpose
Extract variables from WRF NetCDF output files (`wrfout_d0N_*`) for analysis, comparison with observations, and downstream coupling. This stage handles unit conversions, destaggering, derived variable computation, and format transformation to CSV or other analysis-ready formats.

## Inputs
| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| `wrfout_d0N_*.nc` | NetCDF | Stage 6 | WRF history output files |
| Observation data | CSV/NetCDF | External | Station observations for comparison |
| Target locations | lat/lon | User | Points or regions of interest |

## Outputs
| Output | Format | Description |
|--------|--------|-------------|
| Time series CSV | CSV | Variables at point locations over time |
| Spatial field CSV | CSV | 2D fields at specific times |
| Derived diagnostics | CSV/NetCDF | Computed quantities (wind speed, RH, etc.) |

## Procedure

### 1. Extract Point Time Series
Use `parse_wrfout.py` for automated extraction:
```bash
python parse_wrfout.py \
    --input wrfout_d01_2020-06-15_* \
    --output station_timeseries.csv \
    --mode timeseries \
    --lat 32.5 --lon 117.0 \
    --variables T2,PSFC,RAINC,RAINNC,U10,V10,SWDOWN,GLW,HFX,LH
```

### 2. Compute Derived Variables

**Total Precipitation (hourly rate):**
```python
import netCDF4 as nc
import numpy as np

files = sorted(glob.glob("wrfout_d01_*"))
for i in range(1, len(files)):
    ds0 = nc.Dataset(files[i-1])
    ds1 = nc.Dataset(files[i])
    rain0 = ds0.variables["RAINC"][-1,:,:] + ds0.variables["RAINNC"][-1,:,:]
    rain1 = ds1.variables["RAINC"][0,:,:]  + ds1.variables["RAINNC"][0,:,:]
    hourly_rain = rain1 - rain0  # mm per output interval
    ds0.close(); ds1.close()
```

**Actual Temperature from Potential Temperature:**
```python
# CRITICAL: T in wrfout is perturbation (θ - 300)
theta = ds.variables["T"][0,:,:,:] + 300.0  # Full potential temperature
p = ds.variables["P"][0,:,:,:] + ds.variables["PB"][0,:,:,:]  # Full pressure
T_actual = theta * (p / 100000.0) ** (287.0 / 1003.5)  # Actual temperature (K)
```

**Wind Speed and Direction:**
```python
# Destagger U and V first
u_raw = ds.variables["U10"][0,:,:]
v_raw = ds.variables["V10"][0,:,:]

# Earth-relative rotation (if needed)
cosalpha = ds.variables["COSALPHA"][0,:,:]
sinalpha = ds.variables["SINALPHA"][0,:,:]
u_earth = u_raw * cosalpha - v_raw * sinalpha
v_earth = v_raw * cosalpha + u_raw * sinalpha

wspd = np.sqrt(u_earth**2 + v_earth**2)
wdir = (270 - np.degrees(np.arctan2(v_earth, u_earth))) % 360
```

**Relative Humidity at 2m:**
```python
t2 = ds.variables["T2"][0,:,:]
q2 = ds.variables["Q2"][0,:,:]
psfc = ds.variables["PSFC"][0,:,:]
# Tetens formula
es = 611.2 * np.exp(17.67 * (t2 - 273.15) / (t2 - 29.65))
e = q2 * psfc / (0.622 + 0.378 * q2)
rh2 = 100.0 * e / es
```

### 3. Destagger 3D Fields
```python
def destagger(field, axis):
    """Average adjacent points along stagger dimension."""
    slc0 = [slice(None)] * field.ndim
    slc1 = [slice(None)] * field.ndim
    slc0[axis] = slice(None, -1)
    slc1[axis] = slice(1, None)
    return 0.5 * (field[tuple(slc0)] + field[tuple(slc1)])

# U is staggered in X (last axis for [time,z,y,x])
u_destag = destagger(ds.variables["U"][0,:,:,:], axis=2)
# V is staggered in Y
v_destag = destagger(ds.variables["V"][0,:,:,:], axis=1)
# W and PH are staggered in Z
w_destag = destagger(ds.variables["W"][0,:,:,:], axis=0)
```

### 4. Geopotential Height
```python
ph  = ds.variables["PH"][0,:,:,:]   # Perturbation geopotential (m2/s2)
phb = ds.variables["PHB"][0,:,:,:]  # Base geopotential (m2/s2)
z_stag = (ph + phb) / 9.81          # Height on staggered Z levels (m)
z = destagger(z_stag, axis=0)       # Height on mass levels (m)
```

## Verification
- [ ] Temperature values in correct range (200-330 K for T2)
- [ ] Precipitation is non-negative after differencing
- [ ] Wind speeds reasonable (0-80 m/s)
- [ ] RH is 0-100% (clip if needed due to numerical noise)
- [ ] Destaggered fields have correct dimensions

## Traps
| Trap | Severity | Description |
|------|----------|-------------|
| T is perturbation | CRITICAL | T in wrfout is θ-300. Must add 300 before any temperature calculation. |
| Accumulated precip | HIGH | RAINC/RAINNC accumulate. Must difference between times for rates. |
| Staggered grids | HIGH | U, V, W, PH have extra dimension due to staggering. Destagger before analysis. |
| Grid-relative winds | MEDIUM | U10/V10 need COSALPHA/SINALPHA rotation for earth-relative. |
| Pressure split | MEDIUM | Total pressure = P + PB. Forgetting PB gives only perturbation (~100 Pa). |
| Geopotential vs height | MEDIUM | PH/PHB are in m2/s2. Must divide by 9.81 for meters. |

## Example
Full extraction pipeline:
```bash
# Extract surface meteorology at Beijing (39.9N, 116.4E)
python parse_wrfout.py \
    --input wrfout_d01_* \
    --output beijing_sfc.csv \
    --mode timeseries \
    --lat 39.9 --lon 116.4 \
    --variables T2,T2C,WIND10,RH2,TOTAL_PRECIP,PSFC,SWDOWN,GLW,PBLH
```
