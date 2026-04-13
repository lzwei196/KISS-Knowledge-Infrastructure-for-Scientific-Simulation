# Stage 0: Domain Configuration

## Purpose
Define the WRF simulation domain(s): map projection, grid spacing, nesting hierarchy, and time period. This stage produces the WPS configuration (`namelist.wps`) that controls all subsequent preprocessing.

## Inputs
| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| Study area bounds | lat/lon | User | Southwest and northeast corners of interest |
| Grid spacing | meters | User | Horizontal resolution (e.g., 12000 for 12 km) |
| Nesting plan | ratios | User | Parent-child domain ratios (must be odd: 3, 5, 7) |
| Map projection | string | User | lambert, mercator, polar, lat-lon |
| Simulation period | dates | User | Start/end in YYYY-MM-DD_HH format |
| Vertical levels | integer | User | Number of eta levels (e.g., 45) |

## Outputs
| Output | Format | Description |
|--------|--------|-------------|
| `namelist.wps` | Fortran namelist | WPS configuration for geogrid/ungrib/metgrid |
| `namelist.input` (draft) | Fortran namelist | Initial WRF configuration (refined in Stage 5) |

## Procedure

### 1. Choose Map Projection
- **Lambert Conformal** (`lambert`): Best for mid-latitude domains. Set `truelat1` and `truelat2` to bracket the domain (e.g., 30 and 60 for East Asia).
- **Mercator** (`mercator`): Best for tropical/equatorial domains.
- **Polar Stereographic** (`polar`): Best for polar regions.
- **Lat-lon** (`lat-lon`): For global or very large domains.

### 2. Set Grid Spacing
Rule of thumb: start with 3:1 nesting ratio.
- Domain 1 (parent): 12-36 km for synoptic/mesoscale
- Domain 2 (nest): 4-12 km for mesoscale features
- Domain 3 (nest): 1-4 km for convection-permitting

### 3. Configure Vertical Levels
Default 45 levels is adequate for most applications. For PBL studies, add levels below 1 km:
```
eta_levels = 1.000, 0.9975, 0.995, 0.990, 0.985, 0.980, 0.970, 0.960,
             0.950, 0.940, 0.930, 0.920, 0.910, 0.895, 0.880, 0.860,
             0.830, 0.800, 0.770, 0.740, 0.700, 0.650, 0.600, 0.550,
             0.500, 0.450, 0.400, 0.350, 0.300, 0.250, 0.200, 0.150,
             0.100, 0.070, 0.050, 0.030, 0.020, 0.010, 0.000
```

### 4. Set Time Period
- `interval_seconds` must match forcing data temporal resolution:
  - ERA5 hourly: 3600
  - GFS 6-hourly: 21600
  - FNL 6-hourly: 21600
- Allow 12-24 hours of spin-up before the analysis period.

### 5. Write namelist.wps
```
&share
 wrf_core = 'ARW',
 max_dom = 2,
 start_date = '2020-06-15_00:00:00', '2020-06-15_00:00:00',
 end_date   = '2020-06-18_00:00:00', '2020-06-18_00:00:00',
 interval_seconds = 21600,
/
&geogrid
 parent_id         = 1,   1,
 parent_grid_ratio = 1,   3,
 i_parent_start    = 1,   31,
 j_parent_start    = 1,   25,
 e_we              = 150, 220,
 e_sn              = 130, 190,
 dx = 12000,
 dy = 12000,
 map_proj = 'lambert',
 ref_lat   =  35.0,
 ref_lon   = 117.0,
 truelat1  =  30.0,
 truelat2  =  60.0,
 stand_lon = 117.0,
 geog_data_path = '/path/to/WPS_GEOG/',
/
```

## Verification
- [ ] Grid spacing appropriate for target phenomena
- [ ] Nesting ratio is odd (3, 5, 7)
- [ ] `interval_seconds` matches forcing data resolution
- [ ] Domain covers study area with 5+ grid points buffer
- [ ] `truelat1/truelat2` bracket the domain latitude range
- [ ] Spin-up period included before analysis start

## Traps
| Trap | Severity | Description |
|------|----------|-------------|
| Even nesting ratio | CRITICAL | `parent_grid_ratio` must be odd for real data. Even ratios cause interpolation errors. |
| CFL violation | CRITICAL | `time_step` > 6 * dx(km) causes blow-up. For dx=12km, dt <= 72s. |
| Missing spin-up | HIGH | Starting analysis at simulation start misses PBL/soil equilibration. |
| Wrong interval_seconds | HIGH | Mismatch with forcing data resolution causes interpolation artifacts. |

## Example
Configure a 2-domain setup over eastern China for a 3-day summer case:
- Domain 1: 12 km, 150x130, Lambert projection
- Domain 2: 4 km, 220x190, 3:1 ratio, convection-permitting
- Period: 2020-06-15_00 to 2020-06-18_00 (include 12h spin-up)
- Forcing: GFS 0.25deg 6-hourly (interval_seconds=21600)
