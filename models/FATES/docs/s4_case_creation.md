# S4: CTSM Case Creation and Execution

## Purpose

Create, configure, build, and submit a CTSM (Community Terrestrial Systems Model)
case with FATES enabled. This is the primary execution pathway for FATES — the model
cannot run as a standalone binary.

## Inputs

| Input | Format | Source | Required |
|-------|--------|--------|----------|
| CTSM source tree | Directory | `git clone` + `checkout_externals` | Yes |
| FATES parameter file | JSON | Stage 1 output | Yes |
| Surface dataset | NetCDF | Stage 2 output (or CTSM default) | Optional |
| Forcing data | NetCDF | Stage 3 configuration | Yes (default provided) |
| Site coordinates | lat/lon | Manual | Yes |
| Simulation period | Dates | Manual | Yes |

### Prerequisites

```bash
# CTSM with externals (including FATES)
git clone https://github.com/ESCOMP/CTSM.git
cd CTSM
./manage_externals/checkout_externals

# System requirements:
# - Fortran compiler (gfortran ≥ 8, ifort, or nvfortran)
# - NetCDF-C and NetCDF-Fortran libraries
# - ESMF (optional but recommended)
# - MPI library (OpenMPI, MPICH, or Intel MPI)
# - CMake ≥ 3.10
# - Python 3.6+ with numpy
```

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Case directory | Directory tree | Contains build, run scripts, namelists |
| CLM history files | NetCDF | `*.clm2.h0.*.nc` (monthly) |
| FATES restart files | NetCDF | `*.clm2.r.*.nc` (checkpoints) |
| Timing data | Text | `timing/` directory |

## Procedure

### Step 1: Create the Case

```bash
cd $CTSM_ROOT/cime/scripts

# FATES compsets (component sets):
# I2000Clm51FatesRs    — FATES with satellite phenology restart
# I2000Clm51Fates      — FATES default (year 2000 conditions)
# I1850Clm51Fates      — FATES pre-industrial
# IHistClm51Fates      — FATES transient historical

./create_newcase --case ~/cases/my_fates_run \
    --compset I2000Clm51FatesRs \
    --res f09_g17 \
    --run-unsupported
```

### Step 2: Configure the Case

```bash
cd ~/cases/my_fates_run

# Set simulation period
./xmlchange RUN_STARTDATE=2000-01-01
./xmlchange STOP_OPTION=nyears
./xmlchange STOP_N=5

# Configure output frequency
./xmlchange HIST_OPTION=nmonths
./xmlchange HIST_N=1

# Set DATM forcing period
./xmlchange DATM_CLMNCEP_YR_START=2000
./xmlchange DATM_CLMNCEP_YR_END=2005
```

### Step 3: Configure FATES Namelist

```bash
cat >> user_nl_clm << 'EOF'
! FATES core settings
use_fates = .true.
use_fates_sp = .false.
fates_spitfire_mode = 0

! Custom parameter file (if modified)
! fates_paramfile = '/path/to/custom_params.json'

! Output variables
hist_fincl1 = 'FATES_GPP','FATES_NPP','FATES_LAI','FATES_VEGC',
              'FATES_LEAFC','FATES_NPLANT','FATES_MORTALITY'
hist_mfilt = 12
hist_nhtfrq = 0
EOF
```

### Step 4: Build

```bash
./case.setup
./case.build   # Takes 10-30 minutes depending on system
```

### Step 5: Submit

```bash
./case.submit

# Monitor progress
tail -f CaseStatus
# Or check run directory:
ls $RUNDIR/*.clm2.h0.*.nc
```

### Using the Wrapper Tool

```bash
python ki/tools/run_fates_case.py \
    --ctsm-root /path/to/CTSM \
    --site-name BCI \
    --lat 9.15 --lon -79.85 \
    --start 2000-01-01 --stop 2005-01-01 \
    --compset I2000Clm51FatesRs \
    --submit
```

## Verification

- [ ] `case.build` completed without errors
- [ ] `CaseStatus` shows `case.submit success`
- [ ] CLM history files exist in run directory: `*.clm2.h0.*.nc`
- [ ] Output files contain FATES variables (not all-zero or all-NaN)
- [ ] Log file (`cesm.log.*` or `lnd.log.*`) shows no FATES errors
- [ ] Timing output indicates reasonable simulation speed

## Traps

| Trap ID | Description | Detection |
|---------|-------------|-----------|
| dt_003 | Trying to run FATES standalone without host model | Build failure |
| dt_013 | Using CDL params instead of JSON | Namelist parse error |
| dt_016 | Fire disabled by default (spitfire_mode=0) | Zero fire output |
| dt_017 | Plant hydraulics experimental and may crash | Runtime abort |
| dt_018 | Restart incompatible across FATES versions | Restart load error |

### Critical: Compset Selection

The compset determines which FATES features are active. Using the wrong compset
can silently disable critical components:

| Compset | Fire | Logging | Hydraulics | N/P |
|---------|------|---------|------------|-----|
| I2000Clm51FatesRs | Off | Off | Off | Off |
| I2000Clm51Fates | Off | Off | Off | Off |
| Custom | Configurable via `fates_spitfire_mode` | Via `use_fates_logging` | Via `use_fates_planthydro` | Via `fates_parteh_mode` |

### Critical: Build Errors

Common build failures:
1. **Missing NetCDF**: Set `NETCDF_C_PATH` and `NETCDF_FORTRAN_PATH` environment variables
2. **Missing ESMF**: Set `ESMF_ROOT` or build ESMF from source
3. **Compiler version**: gfortran < 8 may fail on Fortran 2003+ features
4. **CIME machine**: If no matching machine, create a custom machine definition

## Example

**Scenario**: 5-year FATES simulation at Barro Colorado Island with fire enabled.

```bash
# Create case
cd $CTSM_ROOT/cime/scripts
./create_newcase --case ~/cases/bci_fates_fire \
    --compset I2000Clm51FatesRs --res f09_g17 --run-unsupported

cd ~/cases/bci_fates_fire
./xmlchange RUN_STARTDATE=2000-01-01
./xmlchange STOP_N=5

# Enable SPITFIRE fire
cat >> user_nl_clm << 'EOF'
use_fates = .true.
fates_spitfire_mode = 1
hist_fincl1 = 'FATES_GPP','FATES_FIRE_INTENSITY','FATES_AREA_BURNT'
EOF

./case.setup && ./case.build && ./case.submit
```
