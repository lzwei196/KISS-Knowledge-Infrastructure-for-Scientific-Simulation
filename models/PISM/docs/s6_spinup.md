# S6: Spinup — Equilibrium Ice Sheet Initialization

## Purpose

Run PISM for a long period (typically 10,000–200,000 years) under constant or
paleo-climate forcing to bring the ice sheet to thermal and dynamic equilibrium.
The spinup provides the initial state for transient simulations. Poor spinup
is the #1 cause of model drift in forward runs.

## Inputs

| Input | Description |
|-------|-------------|
| Bootstrap file | From S2 (geometry + climate) |
| Paleo-temperature file | Optional: δ¹⁸O-derived ΔT time series |
| Paleo-sea-level file | Optional: sea level history |

## Outputs

| Output | Description |
|--------|-------------|
| Spinup output | Full model state for restart |
| Scalar time series | Ice volume, area, velocity evolution |
| Spatial snapshots | Periodic snapshots for monitoring |

## Procedure

### Step 1: Constant-Climate Spinup (simplest)

```bash
./spinup.sh 8 const 1000 20 sia
# → 8 processors, constant climate, 1000 years, 20 km, SIA-only
```

Equivalent manual command:
```bash
mpiexec -n 8 pism \
  -i pism_Greenland_5km_v1.1.nc -bootstrap \
  -dx 20km -dy 20km -Mz 101 -Lz 4000 -Mbz 11 -Lbz 2000 \
  -z_spacing equal -skip -skip_max 10 \
  -surface given -surface_given_file pism_Greenland_5km_v1.1.nc \
  -ys -1000 -ye 0 \
  -sia_e 3.0 \
  -o greenland_const_1000_20_sia.nc \
  -scalar_file scalar_greenland.nc -scalar_times -1000:yearly:0 \
  -spatial_file spatial_greenland.nc -spatial_times -1000:100:0 \
  -spatial_vars thk,usurf,velsurf_mag,mask,temppabase,bmelt
```

### Step 2: Grid Sequencing (recommended)

Start coarse, refine progressively:

```bash
# Phase 1: 40 km, 20,000 years, SIA-only
./spinup.sh 4  const 20000 40 sia g40km_20ka.nc

# Phase 2: 20 km, 10,000 years, regrid from 40km result
REGRIDFILE=g40km_20ka.nc ./spinup.sh 8  const 10000 20 sia g20km_10ka.nc

# Phase 3: 10 km, 5,000 years, hybrid dynamics, regrid from 20km
REGRIDFILE=g20km_10ka.nc ./spinup.sh 16 const 5000  10 hybrid g10km_5ka.nc
```

### Step 3: Paleo-Climate Spinup (full glacial cycle)

```bash
./spinup.sh 16 paleo 125000 20 hybrid greenland_paleo_125ka.nc
```

This uses:
- `-atmosphere searise_greenland,delta_T,precip_scaling`
- `-surface pdd`
- `-sea_level constant,delta_sl`
- Temperature and precipitation modified by ice core record

### Step 4: Monitor Convergence

Check stationarity of key quantities:

```bash
# Plot ice volume evolution
python3 -c "
from netCDF4 import Dataset
import matplotlib.pyplot as plt
ds = Dataset('scalar_greenland.nc')
t = ds.variables['time'][:]
vol = ds.variables['ice_volume_glacierized'][:]
plt.plot(t, vol)
plt.xlabel('Time (years)')
plt.ylabel('Ice Volume (m³)')
plt.savefig('spinup_volume.png')
"
```

Convergence criteria:
- Ice volume change < 0.1% per millennium
- Maximum velocity change < 1% per millennium
- Basal temperature field stabilized

### Step 5: Check Spinup Quality

```bash
pism_check_stationarity spatial_greenland.nc
```

## Verification

1. **Volume trend**: Should flatten (dV/dt → 0)
2. **Geometry**: Compare thickness map to observations
3. **Velocities**: Compare surface speed to satellite (MEaSUREs)
4. **Temperature**: Basal temperature should be realistic (-30 to 0°C)

```bash
# Quick comparison of ice volume
python3 -c "
from netCDF4 import Dataset
ds = Dataset('greenland_spinup.nc')
thk = ds.variables['thk'][:]
dx = 20000  # 20 km in meters
vol_km3 = (thk * dx * dx).sum() / 1e9
print(f'Ice volume: {vol_km3:.0f} km³')
print(f'Expected Greenland: ~2,900,000 km³')
ds.close()
"
```

## Traps

| Trap | Severity | Description |
|------|----------|-------------|
| Too short spinup | SILENT | Model drift in transient runs |
| No grid sequencing | DEGRADED | Very slow convergence at fine resolution |
| Wrong paleo-climate forcing | SILENT | Present-day ice ≠ paleo-equilibrium |
| Regrid without full variable list | SILENT | Missing basal temperatures → re-thermalization |
| SIA-only spinup for hybrid run | DEGRADED | Thermal state wrong for sliding |

## Example

```bash
# Complete 3-stage Greenland spinup
cd examples/std-greenland
./preprocess.sh

# Stage 1: Coarse SIA
./spinup.sh 4 const 20000 40 sia g40_20ka.nc

# Stage 2: Medium hybrid
REGRIDFILE=g40_20ka.nc \
  ./spinup.sh 8 const 5000 20 hybrid g20_5ka.nc

# Stage 3: Fine hybrid
REGRIDFILE=g20_5ka.nc \
  ./spinup.sh 16 const 2000 10 hybrid g10_2ka.nc
```
