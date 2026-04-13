# Stage 0: Configuration and Compset Selection

## Purpose

Configure a CLM5/CTSM simulation by selecting the appropriate compset
(component set), resolution, machine, and physics options. This stage
determines the entire model behavior — incorrect configuration leads to
wrong science or build failures downstream.

## Prerequisites

- CTSM source code checked out with all submodules (via `git-fleximod`)
- CIME infrastructure available at `$CTSMROOT/cime`
- Machine configuration file (either built-in or custom in `~/.cime/`)
- Minimum: MPI, NetCDF-Fortran >= 4.7.4, ESMF, Fortran compiler

## Inputs

| Input | Description | Example |
|---|---|---|
| Compset | Physics/forcing combination | `I2000Clm60BgcCrop` |
| Resolution | Grid specification | `f09_g17` (0.9x1.25 deg) |
| Machine | Computing platform | `cheyenne`, `derecho`, custom |
| Project | Allocation account | depends on HPC center |

### Key Compset Naming Convention

```
TIME_ATM[%phys]_LND[%phys]_ICE_OCN_ROF_GLC_WAV[_BGC%phys]
```

Common compsets:
- `I2000Clm60Sp` — Year-2000 satellite phenology (simplest, fastest)
- `I2000Clm60Bgc` — Year-2000 with full biogeochemistry (CN cycling)
- `I2000Clm60BgcCrop` — BGC with prognostic crops
- `I1850Clm60BgcCrop` — Pre-industrial for spinup
- `IHistClm60BgcCrop` — Transient historical (1850-2015)
- `I2000Clm60Fates` — With FATES ecosystem demography

### Key CLM Physics Versions

| Version | Key Features |
|---|---|
| CLM4.5 | Legacy, CN biogeochemistry |
| CLM5.0 | Improved hydrology, LUNA photosynthesis, FUN nitrogen |
| CLM6.0 | Updated soil biogeochemistry, hillslope hydrology, FATES |

## Procedure

### Step 1: Create a new case

```bash
cd $CIMEROOT/scripts
./create_newcase --case ~/cases/my_test \
    --compset I2000Clm60Sp \
    --res f09_g17 \
    --run-unsupported
```

### Step 2: Modify case settings

```bash
cd ~/cases/my_test

# Set run length
./xmlchange STOP_OPTION=nmonths
./xmlchange STOP_N=12

# Set output frequency
./xmlchange HIST_OPTION=nmonths
./xmlchange HIST_N=1

# For BGC: enable accelerated spinup
./xmlchange CLM_ACCELERATED_SPINUP=on
```

### Step 3: Customize namelists

Edit `user_nl_clm` to add custom namelist settings:

```fortran
! Add extra history variables
hist_fincl1 = 'GPP', 'NPP', 'NEE', 'QRUNOFF', 'EFLX_LH_TOT'

! Change output frequency to daily
hist_nhtfrq = -24
hist_mfilt = 365

! Set CO2
co2_ppmv = 400.0
```

### Step 4: Setup and build

```bash
./case.setup
./case.build
```

## Outputs

| Output | Location | Description |
|---|---|---|
| Case directory | `~/cases/my_test/` | All scripts and configs |
| env_run.xml | Case directory | Runtime configuration |
| user_nl_clm | Case directory | User namelist overrides |
| CaseDocs/lnd_in | Case directory | Generated CLM namelist |
| Build directory | `bld/` subdirectory | Compiled binary |

## Verification

1. Check `CaseDocs/lnd_in` for correct physics options
2. Verify `./xmlquery COMPSET` matches intent
3. Confirm `./xmlquery LND_TUNING_MODE` is appropriate for forcing data
4. Run `./preview_namelists` to see generated namelists without building

## Common Traps

- **dt_007**: Calendar mismatch between forcing and model. GSWP3 uses noleap;
  ERA5 uses gregorian. Set via `./xmlchange CALENDAR=NO_LEAP`
- Using `Clm50` physics with `Clm60` tuning mode or vice versa — causes
  parameter mismatches and incorrect results
- Forgetting `--run-unsupported` for non-standard compsets causes immediate
  failure
- Not setting `CLM_FORCE_COLDSTART=on` when no initial conditions file
  is available for the chosen resolution/physics combination

## Example

Create a single-point simulation for a flux tower site:

```bash
cd $CIMEROOT/scripts
./create_newcase --case ~/cases/US-Ha1 \
    --compset I2000Clm60BgcCrop \
    --res CLM_USRDAT \
    --run-unsupported

cd ~/cases/US-Ha1
./xmlchange CLM_USRDAT_NAME=1x1_harvardForest
./xmlchange STOP_OPTION=nyears
./xmlchange STOP_N=5
./xmlchange DATM_CLMNCEP_YR_START=2000
./xmlchange DATM_CLMNCEP_YR_END=2005

cat >> user_nl_clm << 'EOF'
hist_nhtfrq = -24
hist_mfilt = 365
hist_fincl1 = 'GPP','NEE','EFLX_LH_TOT','FSH','QRUNOFF'
co2_ppmv = 380.0
EOF

./case.setup
./case.build
./case.submit
```
