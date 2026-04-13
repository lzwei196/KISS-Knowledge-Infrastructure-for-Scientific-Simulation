# Stage 5: Namelist Assembly

## Purpose
Configure the WRF model's `namelist.input` file with appropriate physics options, dynamics settings, domain parameters, and output controls. This is the single most important configuration step -- errors here silently corrupt results.

## Inputs
| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| Domain plan | Metadata | Stage 0 | Grid dimensions, nesting, projection |
| Physics selection | User decision | Literature/experience | Scheme combinations |
| Forcing data info | Metadata | Stage 2 | Temporal resolution, pressure levels |
| `README.namelist` | Reference text | WRF run/ | Complete namelist documentation |

## Outputs
| Output | Format | Description |
|--------|--------|-------------|
| `namelist.input` | Fortran namelist | Complete WRF configuration file |

## Procedure

### 1. &time_control Section
```fortran
&time_control
 run_days                = 3,
 run_hours               = 0,
 start_year              = 2020,   2020,
 start_month             = 06,     06,
 start_day               = 15,     15,
 start_hour              = 00,     00,
 end_year                = 2020,   2020,
 end_month               = 06,     06,
 end_day                 = 18,     18,
 end_hour                = 00,     00,
 interval_seconds        = 21600,           ! Must match forcing data frequency
 history_interval        = 60,    60,       ! Output every 60 minutes
 frames_per_outfile      = 24,    24,       ! 24 times per wrfout file
 io_form_history         = 2,               ! 2=netCDF
 io_form_input           = 2,
 io_form_boundary        = 2,
 io_form_restart         = 2,
 restart                 = .false.,
 restart_interval        = 1440,            ! Restart every 24 hours
/
```

### 2. &domains Section
```fortran
&domains
 time_step               = 60,              ! CFL: dt <= 6*dx(km)
 max_dom                 = 2,
 e_we                    = 150,  220,
 e_sn                    = 130,  190,
 e_vert                  = 45,   45,        ! Same for all domains
 dx                      = 12000, 4000,     ! meters
 dy                      = 12000, 4000,
 parent_id               = 1,     1,
 parent_grid_ratio       = 1,     3,        ! Must be ODD
 parent_time_step_ratio  = 1,     3,
 i_parent_start          = 1,     31,
 j_parent_start          = 1,     25,
 feedback                = 1,               ! Two-way nesting
 smooth_option           = 0,
/
```

### 3. &physics Section -- Recommended Combinations

**General-purpose (recommended starting point):**
```fortran
&physics
 mp_physics              = 8,     8,        ! Thompson microphysics
 ra_lw_physics           = 4,     4,        ! RRTMG longwave
 ra_sw_physics           = 4,     4,        ! RRTMG shortwave
 radt                    = 15,    15,       ! Radiation interval (min)
 sf_sfclay_physics       = 1,     1,        ! Revised MM5 surface layer
 sf_surface_physics      = 2,     2,        ! Noah LSM
 bl_pbl_physics          = 1,     1,        ! YSU PBL
 cu_physics              = 1,     0,        ! KF on d01, OFF on d02 (<5km)
 num_soil_layers         = 4,               ! Noah = 4 layers
 num_land_cat            = 21,              ! MODIS 21-cat
/
```

**Tropical/convective:**
```fortran
 mp_physics   = 6,  6,     ! WSM6
 cu_physics   = 16, 0,     ! New Tiedtke (better for tropics)
 bl_pbl_physics = 5, 5,    ! MYNN 2.5 (better for tropical BL)
```

**Winter/snow:**
```fortran
 mp_physics   = 10, 10,    ! Morrison 2-moment (ice processes)
 sf_surface_physics = 4,   ! Noah-MP (better snow physics)
```

### 4. &dynamics Section
```fortran
&dynamics
 rk_ord                  = 3,               ! 3rd order Runge-Kutta
 diff_opt                = 2,     2,        ! Full diffusion
 km_opt                  = 4,     4,        ! Horizontal Smagorinsky
 non_hydrostatic         = .true., .true.,
 hybrid_opt              = 2,               ! Hybrid vertical coord (recommended)
 h_mom_adv_order         = 5,     5,        ! 5th order momentum advection
 v_mom_adv_order         = 3,     3,
 h_sca_adv_order         = 5,     5,
 v_sca_adv_order         = 3,     3,
 moist_adv_opt           = 1,     1,        ! Positive-definite moisture advection
/
```

### 5. CFL Stability Check
```
For dx = 12000 m (12 km): dt_max = 6 * 12 = 72 s → use time_step = 60
For dx = 4000 m (4 km):   dt_max = 6 * 4 = 24 s → child gets 60/3 = 20 s ✓
```

## Verification
- [ ] `time_step` satisfies CFL: dt <= 6 * dx(km)
- [ ] `interval_seconds` matches forcing data frequency
- [ ] `parent_grid_ratio` is odd for all nests
- [ ] `num_soil_layers` matches `sf_surface_physics` (Noah=4, RUC=6, CLM4=10)
- [ ] `cu_physics = 0` for domains with dx < 5 km
- [ ] `e_vert` is the same for all domains
- [ ] `num_land_cat` matches the land-use dataset (MODIS=21, USGS=24)
- [ ] Physics options are consistent across domains (most should be same)

## Traps
| Trap | Severity | Description |
|------|----------|-------------|
| CFL violation | CRITICAL | dt > 6*dx(km) causes immediate blow-up |
| Soil layers wrong | CRITICAL | num_soil_layers must match LSM; causes segfault |
| cu_physics on fine grid | HIGH | Cumulus scheme at dx<5km double-counts convective rain |
| num_land_cat wrong | HIGH | Mismatch with geogrid data gives wrong surface properties |
| radt too large | MEDIUM | Radiation interval > 30 min misses diurnal cycle |
| Missing feedback | MEDIUM | feedback=0 loses fine-grid information in parent |

## Example
Generate a minimal namelist for a single-domain test:
```bash
cat > namelist.input << 'EOF'
&time_control
 run_hours = 6,
 start_year = 2020, start_month = 06, start_day = 15, start_hour = 00,
 end_year = 2020, end_month = 06, end_day = 15, end_hour = 06,
 interval_seconds = 21600,
 history_interval = 60,
 io_form_history = 2, io_form_input = 2, io_form_boundary = 2,
/
&domains
 time_step = 60, max_dom = 1,
 e_we = 100, e_sn = 100, e_vert = 35,
 dx = 12000, dy = 12000,
/
&physics
 mp_physics = 8, ra_lw_physics = 4, ra_sw_physics = 4, radt = 15,
 sf_sfclay_physics = 1, sf_surface_physics = 2, bl_pbl_physics = 1,
 cu_physics = 1, num_soil_layers = 4,
/
&dynamics
 rk_ord = 3, non_hydrostatic = .true., hybrid_opt = 2,
/
&bdy_control
 specified = .true.,
/
EOF
```
