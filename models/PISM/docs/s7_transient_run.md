# S7: Transient Run — Forward Simulation with Time-Varying Forcing

## Purpose

Run PISM forward in time with realistic, time-varying atmospheric and oceanic forcing
to simulate ice sheet response to climate change. This is the science production stage
that generates results for analysis and publication.

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Spinup output | S6 | Equilibrium initial state (restart file) |
| Climate projections | CMIP6 / RCM | Time-varying temperature and precipitation |
| Ocean projections | CMIP6 / ocean model | Time-varying ocean thermal forcing |
| Sea level history | Global model | If coupling to global sea level |

## Outputs

| Output | Description |
|--------|-------------|
| Main output | Full model state at end of run |
| Scalar time series | Time evolution of integrated quantities |
| Spatial diagnostics | Gridded fields at specified intervals |
| Snapshots | Full model state at specified times |

## Procedure

### Step 1: Prepare Time-Varying Forcing

Climate forcing file must have a time dimension:

```bash
# NetCDF structure for climate projections
# Dimensions: time, y, x
# Variables:
#   air_temp(time, y, x)    [kelvin]
#   precipitation(time, y, x) [kg m^-2 year^-1]
#   time                     [days since YYYY-MM-DD]
```

### Step 2: Continue from Spinup (Restart Mode)

```bash
mpiexec -n 16 pism \
  -i spinup_output.nc \           # Restart from spinup
  -ys 2015 -ye 2100 \            # Run 2015–2100
  -atmosphere given -atmosphere_given_file climate_projections.nc \
  -surface pdd \
  -ocean pico -ocean_pico_file ocean_projections.nc \
  -o transient_2100.nc \
  -scalar_file ts_transient.nc -scalar_times 2015:monthly:2100 \
  -spatial_file spatial_transient.nc -spatial_times 2015:yearly:2100 \
  -spatial_vars thk,usurf,velsurf_mag,mask,bmelt,climatic_mass_balance
```

### Step 3: Ensemble Runs (multiple scenarios)

```bash
for scenario in ssp126 ssp245 ssp585; do
  for sia_e in 2.0 3.0 5.0; do
    mpiexec -n 16 pism \
      -i spinup.nc \
      -ys 2015 -ye 2100 \
      -atmosphere given -atmosphere_given_file ${scenario}_atm.nc \
      -surface pdd \
      -sia_e ${sia_e} \
      -o transient_${scenario}_siae${sia_e}.nc \
      -scalar_file ts_${scenario}_siae${sia_e}.nc \
      -scalar_times 2015:yearly:2100
  done
done
```

### Step 4: ISMIP6 Experiments

```bash
pism ... \
  -output.ISMIP6 \                  # Enable ISMIP6 variable names
  -spatial_vars ISMIP6_spatial_variables \
  -atmosphere given,anomaly \
  -atmosphere_given_file present_day.nc \
  -atmosphere_anomaly_file cmip6_anomaly.nc
```

### Step 5: Checkpoint for Long Runs

```bash
pism ... \
  -checkpoint_interval 10    # Save checkpoint every 10 years
  -checkpoint_file ckpt.nc
```

To continue an interrupted run:
```bash
pism -i ckpt.nc -ye 2100 ...   # Restart from checkpoint
```

## Verification

### Sea Level Contribution

```bash
python3 -c "
from netCDF4 import Dataset
ds = Dataset('ts_transient.nc')
t = ds.variables['time'][:]
mass = ds.variables['ice_mass'][:]
# Convert mass loss to sea level equivalent
# 1 Gt = 1e12 kg; ocean area = 3.625e14 m²; water density = 1028 kg/m³
slr_mm = -(mass - mass[0]) / 1e12 / 3.625e14 * 1e3 / 1.028 * 1e3
print(f'Sea level rise by 2100: {slr_mm[-1]:.1f} mm')
ds.close()
"
```

### Mass Balance Check

```bash
# Check mass balance components sum correctly
python3 -c "
from netCDF4 import Dataset
ds = Dataset('ts_transient.nc')
smb = ds.variables.get('tendency_of_ice_mass_due_to_surface_mass_flux')
bmb = ds.variables.get('tendency_of_ice_mass_due_to_basal_mass_flux')
discharge = ds.variables.get('tendency_of_ice_mass_due_to_discharge')
total = ds.variables.get('tendency_of_ice_mass')
if all(v is not None for v in [smb, bmb, discharge, total]):
    residual = total[:] - smb[:] - bmb[:] - discharge[:]
    print(f'Mass balance residual: {abs(residual).max():.3f} Gt/yr')
ds.close()
"
```

## Traps

| Trap | Severity | Description |
|------|----------|-------------|
| Forcing time outside run period | FATAL | PISM can't interpolate forcing |
| Calendar mismatch | SILENT | Forcing applied at wrong dates |
| Starting from bootstrap instead of restart | DEGRADED | Lose spinup thermal state |
| No ocean forcing for marine sheets | SILENT | Zero melt → unrealistic shelf extent |
| Time step output too frequent | DEGRADED | Huge output files, slow I/O |
| Missing variables in restart file | FATAL | Cannot initialize sub-models |

## Example

```bash
# Greenland 2015-2100 under SSP5-8.5
mpiexec -n 32 pism \
  -i greenland_spinup_10km.nc \
  -ys 2015 -ye 2100 \
  -stress_balance ssa+sia \
  -sia_e 3.0 -pseudo_plastic -pseudo_plastic_q 0.25 \
  -atmosphere given,delta_T -atmosphere_given_file present_climate.nc \
  -atmosphere_delta_T_file ssp585_deltaT.nc \
  -surface pdd \
  -ocean constant -ocean.constant.melt_rate 10 \
  -calving eigen_calving,thickness_calving \
  -bed_def lc \
  -o greenland_2100_ssp585.nc \
  -scalar_file ts_ssp585.nc -scalar_times 2015:monthly:2100 \
  -spatial_file sp_ssp585.nc -spatial_times 2015:yearly:2100 \
  -spatial_vars thk,usurf,velsurf_mag,mask,bmelt,climatic_mass_balance
```
