# S4: Model Execution

## Purpose

Configure the ROMS standard input file (`roms.in`), compile the binary, execute
the model, and monitor the run for errors. This stage ties together all inputs
from S0–S3 and produces the output NetCDF files for analysis.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| `roms.in` | Text | Standard input configuration |
| `my_app.h` | Fortran header | CPP configuration (S1) |
| `roms_grid.nc` | NetCDF | Grid file (S0) |
| `roms_frc.nc` | NetCDF | Atmospheric forcing (S2) |
| `roms_ini.nc` | NetCDF | Initial conditions (S3) |
| `roms_bry.nc` | NetCDF | Boundary conditions (S3) |
| `varinfo.yaml` | YAML | Variable metadata |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `roms_his.nc` | NetCDF | History (snapshots) |
| `roms_avg.nc` | NetCDF | Time averages |
| `roms_rst.nc` | NetCDF | Restart file |
| `roms_sta.nc` | NetCDF | Station data |
| `roms.log` | Text | Run log with diagnostics |

## Procedure

### Step 1: Configure roms.in

Key parameters to set:

```
! Application title
TITLE = My Ocean Simulation

! Grid dimensions (must match grid file)
Lm == 120         ! interior XI-points
Mm == 80          ! interior ETA-points
N == 30           ! vertical levels
NAT == 2          ! active tracers (temp + salt)

! Time stepping
NTIMES == 8640    ! total time steps
DT == 300.0d0     ! baroclinic time step (seconds)
NDTFAST == 30     ! barotropic sub-steps per DT

! Time reference (YYYYMMDD.dd)
TIME_REF == 20200101.0d0

! Domain decomposition (NtileI * NtileJ = number of MPI procs)
NtileI == 4
NtileJ == 2

! Output intervals (in time steps)
NRST == 1440      ! restart every 5 days
NHIS == 72        ! history every 6 hours
NAVG == 288       ! averages every day
NSTA == 12        ! stations every hour

! Input files
VARNAME == ROMS/External/varinfo.yaml
GRDNAME == roms_grid.nc
ININAME == roms_ini.nc
FRCNAME == roms_frc.nc
BRYNAME == roms_bry.nc

! Output files
HISNAME == roms_his.nc
AVGNAME == roms_avg.nc
RSTNAME == roms_rst.nc
STANAME == roms_sta.nc

! Vertical coordinate parameters
Vtransform == 2
Vstretching == 4
THETA_S == 7.0d0
THETA_B == 2.0d0
TCLINE == 250.0d0

! Physical parameters
RHO0 == 1025.0d0        ! reference density (kg/m³)
VISC2 == 5.0d0           ! horizontal viscosity (m²/s)
TNU2 == 0.0d0 0.0d0      ! tracer diffusivity (m²/s)
AKT_BAK == 1.0d-6 1.0d-6 ! background tracer diffusivity
AKV_BAK == 1.0d-5        ! background viscosity
RDRG2 == 3.0d-3          ! quadratic bottom drag
Zob == 0.02d0            ! bottom roughness (m)

! Nudging time scales (days)
Tnudg == 10.0d0 10.0d0

! Output variables (T=write, F=skip)
Hout(idUvel) == T         ! 3D u-velocity
Hout(idVvel) == T         ! 3D v-velocity
Hout(idWvel) == T         ! vertical velocity
Hout(idOvel) == T         ! omega vertical velocity
Hout(idTvar) == T T       ! temperature, salinity
Hout(idFsur) == T         ! free-surface
```

### Step 2: Stability check

Before running, verify the CFL condition:
```python
import numpy as np
g = 9.81
hmax = 5000.0    # maximum depth (m)
dx_min = 1000.0  # minimum grid spacing (m)
dt = 300.0       # baroclinic step (s)
ndtfast = 30

c_ext = np.sqrt(g * hmax)       # external wave speed
dtfast = dt / ndtfast            # barotropic step
cfl_ext = c_ext * dtfast / dx_min

print(f"External wave speed: {c_ext:.1f} m/s")
print(f"Barotropic dt: {dtfast:.2f} s")
print(f"External CFL: {cfl_ext:.4f} (must be < 1)")
```

### Step 3: Compile

```bash
cd /path/to/roms
mkdir -p build && cd build
cmake .. -DAPP=MY_APP -DROMS_APP_HEADER=my_app.h
make -j$(nproc)
```

### Step 4: Execute

**Serial:**
```bash
./romsS < roms.in > roms.log 2>&1
```

**MPI (8 processes = NtileI(4) × NtileJ(2)):**
```bash
mpirun -np 8 ./romsM roms.in > roms.log 2>&1
```

### Step 5: Monitor

Check the log file during execution:
```bash
# Watch for BLOWUP or errors
tail -f roms.log | grep -E "BLOWUP|ERROR|NaN|DEF_HIS|GET_"

# Check energy diagnostics
grep "ENERGY" roms.log
```

### Step 6: Post-run validation

```bash
# Verify output files exist and have reasonable size
ls -lh roms_his.nc roms_avg.nc roms_rst.nc

# Quick check of output
ncdump -h roms_his.nc | head -40

# Check for NaN in final timestep
python3 -c "
from netCDF4 import Dataset
import numpy as np
ds = Dataset('roms_his.nc')
temp = ds.variables['temp'][-1]
print(f'Final temp: [{np.nanmin(temp):.2f}, {np.nanmax(temp):.2f}]')
print(f'NaN count: {np.isnan(temp).sum()}')
ds.close()
"
```

## Verification

A successful ROMS run should show:
1. Log file ends with "ROMS/TOMS - Output ..." without BLOWUP
2. History file contains expected number of time records
3. Temperature range is physically reasonable (-2 to 35°C)
4. Salinity range is reasonable (0 to 42 PSU)
5. Sea surface height is within ±2 m
6. No NaN values in output variables

## Traps

| Trap | Description | Consequence |
|------|-------------|-------------|
| NtileI × NtileJ ≠ nprocs | MPI process mismatch | Crash at startup |
| DT too large | CFL violation | BLOWUP after a few steps |
| NDTFAST too small | Poor barotropic coupling | Slow instability |
| Wrong VARNAME path | Can't find variable metadata | NetCDF read failures |
| Lm/Mm mismatch | Different from grid file | Array bounds error |
| NRREC mismatch | Wrong restart record | Wrong initial state |
| TIME_REF mismatch | Doesn't match forcing times | Forcing interpolated wrong |

## Example

```bash
# Full execution with wrapper
python tools/run_roms.py \
  --binary ./build/romsM \
  --config roms.in \
  --np 8 \
  --timeout 7200
```
