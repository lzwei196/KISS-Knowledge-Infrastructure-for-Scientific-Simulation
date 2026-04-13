# Stage 0: Configuration

## Purpose

Define the simulation domain, time period, grid resolution, physics options, and file
paths before any data preparation begins. This stage produces the `namelist.hrldas`
file that controls all aspects of the Noah-MP HRLDAS offline simulation.

## Inputs

| Input | Source | Required |
|-------|--------|----------|
| Basin coordinates (lat, lon) | User specification | Yes |
| Simulation period (start, end) | User specification | Yes |
| Grid resolution (DX, DY) | User specification | Yes |
| Physics option selections | User preference / default | Yes |
| Soil layer configuration | User / default 4-layer | Yes |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `namelist.hrldas` | Fortran namelist | Master configuration file |

## Procedure

### 1. Choose simulation period

```
start_year  = 2010
start_month = 01
start_day   = 01
start_hour  = 00
start_min   = 00
khour       = 8760    ! 1 year = 365 * 24 hours
```

**Rule**: `khour` or `kday` must be set. If both are set, `khour` takes precedence.
Convert: `khour = kday * 24`.

### 2. Set timesteps

```
forcing_timestep = 3600   ! 1-hour forcing data [seconds]
noah_timestep    = 3600   ! Model integration step [seconds]
output_timestep  = 86400  ! Daily output [seconds]
```

**Constraint**: `output_timestep` must be an integer multiple of `noah_timestep`.
**Constraint**: `forcing_timestep` must be an integer multiple of `noah_timestep`.
**Recommendation**: `noah_timestep = 900` (15 min) for sub-hourly forcing;
`noah_timestep = 3600` (1 hr) for hourly forcing.

### 3. Configure soil layers

Standard 4-layer configuration:

```
NSOIL            = 4
soil_thick_input = 0.10, 0.40, 1.00, 2.00   ! Depth to interface [m]
```

This creates layers with thicknesses: 0.10, 0.30, 0.60, 1.00 m.
ZSOIL (internal): -0.10, -0.40, -1.00, -2.00 m (negative downward).

### 4. Select physics options

Recommended defaults for general-purpose hydrological simulation:

```
dynamic_veg_option                  = 4   ! Table LAI, calculated vegetation fraction
canopy_stomatal_resistance_option   = 1   ! Ball-Berry
btr_option                          = 1   ! Noah soil moisture factor
surface_runoff_option               = 3   ! Schaake96 (good general-purpose)
subsurface_runoff_option            = 3   ! Free drainage
surface_drag_option                 = 1   ! Monin-Obukhov
frozen_soil_option                  = 1   ! NY06
radiative_transfer_option           = 3   ! gap = 1-Fveg
snow_albedo_option                  = 1   ! BATS
pcp_partition_option                = 1   ! Jordan91
crop_option                         = 0   ! No crops
irrigation_option                   = 0   ! No irrigation
```

### 5. Set file paths

```
indir                = './forcing'           ! LDASIN forcing files
outdir               = './output'            ! LDASOUT output files
hrldas_setup_file    = './setup/wrfinput_d01' ! Setup/init file
restart_filename_requested = ''              ! Blank = cold start
```

## Verification

- [ ] `namelist.hrldas` is valid Fortran namelist syntax
- [ ] `forcing_timestep % noah_timestep == 0`
- [ ] `output_timestep % noah_timestep == 0`
- [ ] `NSOIL >= 1` and `soil_thick_input` has NSOIL values
- [ ] All file paths exist or will be created before execution

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| dt_009 | Forcing data alignment drift | Ensure forcing_timestep divides noah_timestep |
| dt_008 | Wrong parameter lookup | Match MMINLU in setup file to NoahmpTable.TBL |
| Wrong kday/khour | Model runs for wrong duration | Double-check unit (hours vs days) |

## Example

```fortran
&NOAHLSM_OFFLINE

  hrldas_setup_file  = './wrfinput_d01'
  indir              = './forcing'
  outdir             = './output'

  start_year   = 2010
  start_month  = 1
  start_day    = 1
  start_hour   = 0
  start_min    = 0

  khour        = 8760
  forcing_timestep = 3600
  noah_timestep    = 3600
  output_timestep  = 86400

  NSOIL        = 4
  soil_thick_input = 0.10, 0.40, 1.00, 2.00

  dynamic_veg_option  = 4
  canopy_stomatal_resistance_option = 1
  btr_option          = 1
  surface_runoff_option    = 3
  subsurface_runoff_option = 3
  snow_albedo_option  = 1
  pcp_partition_option = 1

/
```
