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

#### Runoff / ET partitioning — hydroclimate decision rule (added 2026-07)

The general-purpose defaults above (`surface_runoff_option=3` Schaake96 +
`subsurface_runoff_option=3` free drainage, `btr_option=1` Noah) are tuned for
water-limited / semi-arid columns. In **humid, energy-limited, or forested
basins** free drainage over-drains the soil column and the restrictive Noah
btran factor then starves transpiration, so realized ET collapses and the model
**over-produces runoff** (measured +65 % PBIAS at 允景洪/Jinghong on the Lancang;
r=0.92, so timing is correct and the error is purely volume/partitioning). For
such basins use:

```
surface_runoff_option    = 1   ! SIMGM TOPMODEL (dynamic water table)
subsurface_runoff_option = 1   ! SIMGM groundwater baseflow (retains soil water)
btr_option               = 2   ! CLM soil-moisture factor (less restrictive than Noah=1;
                               !   lets the retained water be transpired -> raises ET,
                               !   lowers runoff overproduction)
```

Rule of thumb: choose by aridity index P/PET and land cover —
`P/PET > 1` (humid) and/or forest/woody cover → OPT_RUN=1 + BTR_OPTION=2;
`P/PET < 1` (arid/semi-arid) → keep the Schaake96 + free-drainage + Noah-btran
defaults. OPT_RUN=1 cold-starts with WA=WT≈4900 mm and a diagnosed water table
(no extra init needed). Note OPT_RUN=1 alone only partially closes the bias — it
retains water but BTR_OPTION=1 still throttles its use, so pair it with
BTR_OPTION=2. Routing cannot fix this: it is mass-conserving and the bias is a
partitioning error UPSTREAM of any routing.

#### Managed cropland — crop model and irrigation (added 2026-08)

The defaults above (`crop_option = 0`, `irrigation_option = 0`) describe a NATURAL
column.  For a site whose land use is managed cropland — FLUXNET BADM
`IGBP = CRO`, `DOM_DIST_MGMT = Agriculture`, or any cropland grid cell — those
defaults are a modelling error, not a neutral choice: the LAI cycle of a planted,
harvested, and (often) irrigated field is not the MODIS climatology, and at an
irrigated site the growing-season water supply is simply missing.

```
dynamic_veg_option = 4      ! VegFrac = SHDMAX; the crop model supplies LAI
crop_option        = 1      ! Liu et al. crop model, category from CROPTYPE
irrigation_option  = 2      ! 1 = always, 2 = crop season, 3 = LAI threshold
irrigation_method  = 1      ! 0 = SIFRACT/MIFRACT/FIFRACT split, 1 = sprinkler,
                            ! 2 = micro/drip, 3 = surface flooding
agdata_flnm        = './run/agdata.nc'   ! REQUIRED when irrigation_option >= 1
```

Preconditions, all enforced by `tools/build_hrldas_setup.py`:

| Requirement | Why |
|---|---|
| `IVGTYP` = 12 or 14 (MODIS-IGBP) | `FlagCropland` gates BOTH the crop model and every irrigation method (`GeneralInitMod.F90`) |
| `CROPTYPE` in the setup file, slot 5 >= 0.5 | activates the crop category; slots 1-4 are class weights, largest wins (1 = corn, 2 = soybean) |
| `PLANTING` / `HARVEST` in the setup file | read ONLY when `crop_option = 1`; otherwise `irrigation_option = 2` silently uses the NoahmpTable PLTDAY/HSDAY (dt_024) |
| `IRFRACT` (+ `SIFRACT`/`MIFRACT`/`FIFRACT`) in `agdata_flnm` | the trigger needs `IRFRACT >= IRR_FRAC` (table default 0.10); the setup file is NOT read for these (dt_023) |
| setup-file `LAI` = 0.05 for crop runs | the crop model turns setup LAI into leaf biomass and never resets it before the first harvest -> phantom winter canopy (dt_026) |

Planting and harvest days of year come from
`ki_tools_common.crop_calendar.get_planting_harvest(lat, lon, crop=...)` (GGCMI
Phase 3), not from the table defaults.

Irrigation parameters that behave as calibration knobs live in NoahmpTable.TBL,
not the namelist: `IRR_MAD` (management allowable deficit, default 0.60) is the
dominant control on applied volume, then `SPRIR_RATE` (6.4 mm/h),
`IRR_HAR` (stop 20 d before harvest), `IRR_LAI` (option-3 threshold) and
`IR_RAIN` (rain rate above which the trigger is skipped).

Noah-MP v5.2 has no fertilisation or nitrogen-limitation input, so there is no
fertilisation configuration step for this model.


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
