# Stage 4: Initial Conditions and Spin-up

## Purpose

Prepare initial conditions for ELM. For biogeochemistry runs, this requires
an extensive spin-up period (200-500 years) to equilibrate soil carbon,
nitrogen, and phosphorus pools. Skipping spin-up is the most common cause
of unrealistic carbon flux results (dt_009).

## Prerequisites

- Stage 0-3 completed
- Surface dataset and forcing data prepared

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| finidat file | NetCDF | Previous restart file (for warm start) |
| Surface dataset | NetCDF | Must match the grid of finidat |
| Forcing data | NetCDF | Multi-century forcing for spin-up |

## Outputs

| Output | Format | Description |
|--------|----------|-------------|
| *.elm.r.*.nc | NetCDF | Restart file (full model state) |
| *.elm.rh0.*.nc | NetCDF | History restart file |

## Procedure

### Cold Start (no finidat)

When `finidat = ''` in the namelist, ELM initializes all state variables
from the surface dataset and parameter file:

- Soil temperature: set to a reasonable profile based on latitude
- Soil moisture: set to field capacity
- Snow: none
- Carbon pools: **all zero** ← This is the problem (dt_009)
- Nitrogen pools: all zero
- Vegetation: set from surface dataset PFTs

### Spin-up Procedure (required for BGC runs)

**Why spin-up matters**: Without spin-up, soil organic carbon (SOC) starts at
zero. Since SOC accumulation takes centuries, a production run starting from
cold start will show:
- GPP that looks reasonable (set by leaf properties, not SOC)
- NPP that's too high (no nutrient limitation from decomposition)
- NEE that's strongly negative (net carbon sink into empty pools)
- Heterotrophic respiration near zero (no organic matter to decompose)

**Protocol**:

1. **Accelerated decomposition (AD) spin-up** (200-400 years):

```fortran
! user_nl_elm:
spinup_state = 1
! This accelerates soil C decomposition rates by 5-20x
! Run for 200-400 years until SOC stabilizes
```

2. **Normal spin-up** (100-200 years):

```fortran
! user_nl_elm:
spinup_state = 0
finidat = '/path/to/ad_spinup_restart.nc'
! Run at normal rates until fluxes stabilize
```

3. **Production run**:

```fortran
! user_nl_elm:
spinup_state = 0
finidat = '/path/to/normal_spinup_restart.nc'
! Now start your actual experiment
```

### Interpolating Initial Conditions

If your target resolution differs from the available finidat:

```bash
cd components/elm/tools
# Use interpinic to interpolate
./interpinic -i source_finidat.nc -o target_finidat.nc
```

**CRITICAL (dt_018)**: Interpolation from a very different resolution (e.g.,
1° to 0.25°) introduces artifacts. Always run at least 20-50 years of
additional spin-up after interpolation.

### Checking Spin-up Convergence

Monitor these variables over the spin-up period:

| Variable | Convergence Criterion | Typical Final Value |
|----------|-----------------------|---------------------|
| TOTECOSYSC | Inter-annual change < 1% | 5,000-30,000 gC/m² |
| NEE | Annual mean ≈ 0 ± 5 gC/m²/yr | Near zero |
| TOTSOMC | Inter-annual change < 0.5% | 3,000-20,000 gC/m² |
| TOTVEGC | Stable | 500-15,000 gC/m² |

## Verification

- [ ] After spin-up, NEE oscillates around zero (not trending)
- [ ] TOTECOSYSC year-to-year change < 1%
- [ ] TOTSOMC is non-zero and reasonable for the biome
- [ ] Soil temperature profile is physically reasonable
- [ ] finidat grid matches the case grid (dt_018)

## Traps

| Trap | dt_ID | Symptom | Prevention |
|------|-------|---------|------------|
| No spin-up | dt_009 | Zero SOC, unrealistic NEE | Always spin up BGC runs |
| Too short spin-up | dt_009 | SOC still increasing, net C sink | Check TOTECOSYSC trend |
| finidat grid mismatch | dt_018 | Interpolation artifacts | Run additional spin-up after interp |
| AD spin-up not finished | dt_009 | Soil C not equilibrated | Check if AD pools are stable |

## Example

```bash
# Step 1: Create AD spin-up case (200 years)
cd E3SM/cime/scripts
./create_newcase --case ../../elm_spinup_ad \
    --compset I1850CNPRDCTCBCTOP --res ne4pg2_ne4pg2 --mach chrysalis
cd ../../elm_spinup_ad
cat >> user_nl_elm << 'EOF'
spinup_state = 1
hist_nhtfrq = 0
hist_mfilt = 1
hist_fincl1 = 'TOTECOSYSC','TOTSOMC','TOTVEGC','NEE'
EOF
./xmlchange STOP_N=200,STOP_OPTION=nyears
./case.setup && ./case.build && ./case.submit

# Step 2: After AD spin-up completes, create normal spin-up (100 years)
./create_newcase --case ../../elm_spinup_normal ...
cat >> user_nl_elm << 'EOF'
spinup_state = 0
finidat = '/archive/elm_spinup_ad/rest/elm_spinup_ad.elm.r.0201-01-01-00000.nc'
EOF
./xmlchange STOP_N=100,STOP_OPTION=nyears
```
