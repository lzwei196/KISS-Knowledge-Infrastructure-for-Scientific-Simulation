# Stage 6: Model Execution

## Purpose

Build and run ELM through the CIME case control system. This stage handles
compilation, job submission, monitoring, and basic runtime diagnostics.

## Prerequisites

- Stages 0-4 completed
- Case created and configured (create_newcase + case.setup)
- user_nl_elm customized as needed
- Surface dataset and forcing data in place

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Case directory | create_newcase | Contains case configuration |
| user_nl_elm | Stage 3 | Namelist customizations |
| Surface/forcing data | Stages 1-2 | Input datasets |
| finidat | Stage 4 | Initial conditions (optional) |

## Outputs

| Output | Location | Description |
|--------|----------|-------------|
| Binary executable | $EXEROOT | Compiled ELM+driver executable |
| History files | $DOUT_S_ROOT/lnd/hist/ | NetCDF output |
| Restart files | $DOUT_S_ROOT/rest/ | For continuation runs |
| Timing data | $CASEROOT/timing/ | Performance metrics |
| CaseStatus | $CASEROOT | Run status log |

## Procedure

### 1. Build the model

```bash
cd /path/to/case
./case.build
```

Build takes 10-30 minutes depending on machine. Common build failures:

| Error | Cause | Fix |
|-------|-------|-----|
| `NetCDF not found` | Missing library | `module load netcdf` (dt_017) |
| `MPI_Init failed` | Wrong MPI config | Check machine config |
| `Fortran compile error` | Source code issue | Check stderr for line number |
| `CMake error` | CMake < 3.18 | Upgrade CMake |

### 2. Configure run length

```bash
# Set simulation length
./xmlchange STOP_OPTION=nmonths,STOP_N=12    # 1 year
./xmlchange STOP_OPTION=nyears,STOP_N=5      # 5 years

# Set restart frequency
./xmlchange REST_OPTION=nyears,REST_N=1      # Annual restarts

# Set MPI decomposition
./xmlchange NTASKS_LND=4,NTHRDS_LND=1
```

### 3. Submit the run

```bash
./case.submit
```

### 4. Monitor progress

```bash
# Check CaseStatus for completion
tail -f CaseStatus

# Check run output
ls $(./xmlquery --value RUNDIR)/*.elm.h0.*

# Check for errors
grep -i "error\|abort\|fail" $(./xmlquery --value RUNDIR)/elm.log*
```

### 5. Using the KI execution wrapper

```bash
# Full automated workflow
python tools/run_elm.py \
    --e3sm_root /path/to/E3SM \
    --case_name elm_production \
    --compset I1850CNPRDCTCBCTOP \
    --res ne4pg2_ne4pg2 \
    --machine chrysalis \
    --stop_n 12 --stop_option nmonths \
    --wait

# Check-only mode (verify environment)
python tools/run_elm.py \
    --e3sm_root /path/to/E3SM \
    --check_only \
    --machine chrysalis
```

### 6. Post-run archiving

After successful completion, CIME automatically archives output:

```bash
# Find archived history files
ls $(./xmlquery --value DOUT_S_ROOT)/lnd/hist/

# Find restart files
ls $(./xmlquery --value DOUT_S_ROOT)/rest/
```

## Runtime Troubleshooting

### MPI decomposition errors (dt_016)

If the number of MPI tasks doesn't evenly divide the grid:

```bash
# Check current decomposition
./xmlquery NTASKS_LND,NTHRDS_LND

# Fix: ensure NTASKS divides the number of grid cells
./xmlchange NTASKS_LND=4
```

### Disk quota exceeded (dt_019)

History files can be very large for high-frequency output:

```fortran
! Reduce output frequency or variables
hist_nhtfrq = 0           ! Monthly (not hourly)
hist_mfilt = 12           ! 12 months per file
hist_empty_htapes = .true. ! Remove all default variables
hist_fincl1 = 'GPP','QRUNOFF'  ! Only what you need
```

### Numerical instability (dt_005)

If the model crashes with floating-point exceptions:

```fortran
! Reduce timestep (normally 1800s = 30 min)
dtime = 900   ! 15 min — halving usually helps
```

## Verification

- [ ] `case.build` completes without errors
- [ ] `CaseStatus` shows "case.run success"
- [ ] History files exist in $DOUT_S_ROOT/lnd/hist/
- [ ] No NaN values in key output variables
- [ ] Energy balance closes (FSA - FIRA - FSH - EFLX_LH_TOT ≈ 0)
- [ ] Water balance closes (precip - ET - runoff ≈ ΔS)

## Traps

| Trap | dt_ID | Symptom | Prevention |
|------|-------|---------|------------|
| MPI task mismatch | dt_016 | "decomposition failed" error | Match NTASKS to grid |
| Missing NetCDF | dt_017 | "libnetcdf.so not found" at runtime | module load netcdf |
| Disk quota | dt_019 | "No space left on device" | Reduce history output |
| Timestep too large | dt_005 | FPE, energy imbalance | Reduce dtime |

## Example

```bash
# Quick test: 1-month SP run
cd E3SM/cime/scripts
./create_newcase --case ../../elm_quick_test \
    --compset IELM --res ne4pg2_ne4pg2 --mach chrysalis
cd ../../elm_quick_test
./case.setup
./xmlchange STOP_N=1,STOP_OPTION=nmonths
./case.build
./case.submit

# Monitor
watch -n 30 'tail -1 CaseStatus'

# After completion
ls $(./xmlquery --value DOUT_S_ROOT)/lnd/hist/*.elm.h0.*
```
