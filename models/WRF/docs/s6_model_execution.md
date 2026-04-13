# Stage 6: Model Execution (wrf.exe)

## Purpose
Run the WRF atmospheric model to produce the time-varying forecast/simulation output. The model integrates the governing equations (continuity, momentum, thermodynamic, moisture) forward in time using Runge-Kutta time stepping with time-split acoustic modes.

## Inputs
| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| `wrfinput_d0N` | NetCDF | Stage 4 | Initial conditions per domain |
| `wrfbdy_d01` | NetCDF | Stage 4 | Lateral boundary conditions (domain 1) |
| `namelist.input` | Fortran namelist | Stage 5 | Complete model configuration |
| Lookup tables | Text | WRF run/ | LANDUSE.TBL, RRTM_DATA, etc. |

## Outputs
| Output | Format | Description |
|--------|--------|-------------|
| `wrfout_d0N_YYYY-MM-DD_HH:MM:SS` | NetCDF | History output (main results) |
| `wrfrst_d0N_YYYY-MM-DD_HH:MM:SS` | NetCDF | Restart files (for continuation) |
| `rsl.out.NNNN` | Text | Stdout per MPI process |
| `rsl.error.NNNN` | Text | Stderr per MPI process (timing, warnings) |

### Key Output Variables in wrfout
| Variable | Dims | Description | Units |
|----------|------|-------------|-------|
| `T2` | 2D | 2-m temperature | K |
| `Q2` | 2D | 2-m specific humidity | kg kg-1 |
| `U10` | 2D | 10-m U-wind | m s-1 |
| `V10` | 2D | 10-m V-wind | m s-1 |
| `PSFC` | 2D | Surface pressure | Pa |
| `RAINC` | 2D | Accumulated convective precip | mm |
| `RAINNC` | 2D | Accumulated grid-scale precip | mm |
| `SWDOWN` | 2D | Downward shortwave radiation | W m-2 |
| `GLW` | 2D | Downward longwave radiation | W m-2 |
| `T` | 3D | Perturbation potential temp (θ-300) | K |
| `U` | 3D | U-wind (staggered X) | m s-1 |
| `V` | 3D | V-wind (staggered Y) | m s-1 |
| `W` | 3D | Vertical velocity (staggered Z) | m s-1 |
| `QVAPOR` | 3D | Water vapor mixing ratio | kg kg-1 |

## Procedure

### 1. Ensure all input files are present
```bash
cd /path/to/run_directory/
ls wrfinput_d0* wrfbdy_d01 namelist.input
ls LANDUSE.TBL VEGPARM.TBL SOILPARM.TBL GENPARM.TBL
ls RRTM_DATA RRTMG_LW_DATA RRTMG_SW_DATA   # if using RRTM/RRTMG
```

### 2. Run wrf.exe
```bash
# Serial (single processor -- slow, only for testing)
./wrf.exe >& wrf.log

# MPI parallel (recommended)
mpirun -np 16 ./wrf.exe >& wrf.log

# OpenMP+MPI hybrid
export OMP_NUM_THREADS=2
mpirun -np 8 ./wrf.exe >& wrf.log
```

### 3. Monitor progress
```bash
# Watch rsl.error.0000 for timing information
tail -f rsl.error.0000
# Each line shows: "Timing for main: time YYYY-MM-DD_HH:MM:SS on domain N: X.XXXX elapsed seconds"

# Check for completion
grep "SUCCESS COMPLETE WRF" rsl.out.0000
```

### 4. Handle crashes
If the model crashes (CFL, NaN, etc.):
```bash
# Check what went wrong
grep -i "fatal\|cfl\|nan\|error" rsl.error.* | head -20

# CFL crash: reduce time_step
# NaN: check initial conditions or reduce time_step
# Memory: reduce domain size or increase MPI processes
```

## Verification
- [ ] `wrf: SUCCESS COMPLETE WRF` appears in `rsl.out.0000`
- [ ] wrfout files exist for all domains and expected times
- [ ] T2 values are 200-330 K (reasonable surface temperatures)
- [ ] RAINC + RAINNC is non-negative and not excessively large
- [ ] No NaN values in output fields
- [ ] Wind speeds are reasonable (0-80 m/s at surface)

## Traps
| Trap | Severity | Description |
|------|----------|-------------|
| CFL blow-up | CRITICAL | Model crashes with "cfl" in rsl.error. Fix: reduce time_step. |
| NaN propagation | CRITICAL | NaN in one field infects all fields within ~10 timesteps. |
| Missing tables | HIGH | Missing RRTM_DATA etc. at runtime causes crash or wrong physics. |
| Accumulated precip | HIGH | RAINC/RAINNC accumulate from start. Must difference for rates. |
| Grid-relative winds | MEDIUM | U10/V10 are grid-relative; need COSALPHA/SINALPHA rotation for earth-relative. |
| Staggered output | MEDIUM | 3D U staggered in X, V in Y, W/PH in Z. Must destagger for analysis. |
| Restart mismatch | HIGH | Restart with different physics or precision corrupts state silently. |

## Example
Post-run quick validation:
```python
import netCDF4 as nc
import numpy as np

ds = nc.Dataset("wrfout_d01_2020-06-15_06:00:00")
t2 = ds.variables["T2"][0,:,:]
rain = ds.variables["RAINC"][0,:,:] + ds.variables["RAINNC"][0,:,:]
print(f"T2: {t2.min():.1f} - {t2.max():.1f} K  (mean {t2.mean():.1f} K)")
print(f"Total precip: {rain.min():.1f} - {rain.max():.1f} mm")
if np.any(np.isnan(t2)):
    print("WARNING: NaN in T2!")
ds.close()
```
