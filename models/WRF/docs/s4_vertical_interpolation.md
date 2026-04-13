# Stage 4: Vertical Interpolation (real.exe)

## Purpose
Vertically interpolate the horizontally-interpolated meteorological fields (met_em files) onto WRF's terrain-following eta coordinate levels. Computes the base state atmosphere, balances the initial conditions, and generates lateral boundary conditions. Produces `wrfinput_d0N` and `wrfbdy_d01`.

## Inputs
| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| `met_em.d0N.*.nc` | NetCDF | Stage 3 | Horizontally interpolated met fields |
| `namelist.input` | Fortran namelist | Stage 5 | WRF configuration |
| Lookup tables | Text | WRF run/ | LANDUSE.TBL, VEGPARM.TBL, SOILPARM.TBL, etc. |

## Outputs
| Output | Format | Description |
|--------|--------|-------------|
| `wrfinput_d01` | NetCDF | Initial conditions for domain 1 |
| `wrfinput_d02` | NetCDF | Initial conditions for domain 2 (if nesting) |
| `wrfbdy_d01` | NetCDF | Lateral boundary conditions (domain 1 only) |

### Key Variables in wrfinput
| Variable | Description | Units | Notes |
|----------|-------------|-------|-------|
| `U` | U-wind | m s-1 | Staggered X |
| `V` | V-wind | m s-1 | Staggered Y |
| `W` | Vertical velocity | m s-1 | Staggered Z |
| `T` | Perturbation potential temp | K | **θ - 300** (subtract base state!) |
| `PH` | Perturbation geopotential | m2 s-2 | Staggered Z |
| `PHB` | Base geopotential | m2 s-2 | Staggered Z |
| `P` | Perturbation pressure | Pa | |
| `PB` | Base pressure | Pa | |
| `QVAPOR` | Water vapor mixing ratio | kg kg-1 | |
| `MU` | Perturbation dry air mass | Pa | Column mass perturbation |
| `MUB` | Base dry air mass | Pa | |
| `TSLB` | Soil temperature | K | (num_soil_layers) |
| `SMOIS` | Soil moisture | m3 m-3 | Volumetric |

## Procedure

### 1. Link required files
```bash
cd /path/to/WRF/test/em_real/   # or run directory
ln -sf ../../run/*.TBL .
ln -sf ../../run/RRTM* .
ln -sf ../../run/RRTMG* .
ln -sf ../../run/CAM* .         # if using CAM radiation
ln -sf /path/to/met_em.d0*.nc .
cp namelist.input .             # from Stage 5
```

### 2. Run real.exe
```bash
# Serial
./real.exe >& real.log

# Parallel (MPI)
mpirun -np 4 ./real.exe >& real.log
```

### 3. Check for success
```bash
# Check rsl.error.0000 for serial/MPI
tail -5 rsl.error.0000
# Should show: "real_em: SUCCESS EM REAL INIT"

# Verify output files
ls -la wrfinput_d* wrfbdy_d01
```

### 4. Quick sanity check
```python
import netCDF4 as nc
ds = nc.Dataset("wrfinput_d01")
# Potential temperature: T + 300 should be 250-320 K
t = ds.variables["T"][0,:,50,50]
print(f"Theta range: {(t+300).min():.1f} to {(t+300).max():.1f} K")
# Surface pressure: MU + MUB should be ~100000 Pa
mu = ds.variables["MU"][0,50,50]
mub = ds.variables["MUB"][0,50,50]
print(f"Column mass: {mu+mub:.0f} Pa")
ds.close()
```

## Verification
- [ ] `wrfinput_d0N` exists for each domain and is > 10 MB
- [ ] `wrfbdy_d01` exists and is > 50 MB
- [ ] `real_em: SUCCESS EM REAL INIT` appears in log
- [ ] T + 300 gives reasonable potential temperatures (250-400 K)
- [ ] Soil moisture is 0-0.6 m3/m3 (not 0 everywhere)
- [ ] Soil temperature is 250-320 K (not 0 K)
- [ ] No NaN values in key fields

## Traps
| Trap | Severity | Description |
|------|----------|-------------|
| Soil layer count mismatch | CRITICAL | `num_soil_layers` must match LSM: Noah=4, RUC=6, CLM4=10. Segfault otherwise. |
| Missing met_em files | CRITICAL | Gaps in temporal coverage cause silent extrapolation or crash. |
| T is perturbation | HIGH | T in wrfinput is θ-300, not actual temperature. Forgetting +300 gives ~0 K. |
| Wrong num_metgrid_levels | HIGH | Must match the number of pressure levels in met_em files. |
| Missing lookup tables | HIGH | Missing LANDUSE.TBL causes incorrect land-use category assignment. |
| SST defaults | MEDIUM | If SST not in met_em, real.exe uses skin temperature (less accurate). |

## Example
Check that real.exe produced valid initial conditions:
```bash
# Verify potential temperature
python3 -c "
import netCDF4 as nc; import numpy as np
ds = nc.Dataset('wrfinput_d01')
theta = ds.variables['T'][0,:,:,:] + 300
print(f'Theta: min={theta.min():.1f}, max={theta.max():.1f}, mean={theta.mean():.1f} K')
qv = ds.variables['QVAPOR'][0,:,:,:]
print(f'Qvapor: min={qv.min():.6f}, max={qv.max():.6f} kg/kg')
if np.any(np.isnan(theta)): print('WARNING: NaN in theta!')
ds.close()
"
```
