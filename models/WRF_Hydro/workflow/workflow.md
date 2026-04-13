# WRF-Hydro v5.2.0 Standalone — Pipeline Workflow

## Overview

This document describes the complete pipeline for running WRF-Hydro v5.2.0 in standalone (NoahMP offline) mode on any basin. The pipeline replaces the standard NCAR workflow (WPS geogrid + ArcGIS GIS_tool) with 9 validated Python tools that build all domain files from raw global datasets.

**Total stages**: 12 (s0 through s11)
**Total tools**: 9 validated Python scripts (3,946 lines)
**Validated on**: Chaohe basin, 126x116 cells, 7-day run, 168 hourly outputs, SUCCESS

---

## Pipeline Diagram (Text)

```
s0_config
    |
    v
s1_domain (define_lambert_domain.py)
    |
    +---> s2_geo_em (build_geo_em.py)
    |         |
    |         +---> s3_wrfinput (build_wrfinput.py)
    |         |
    |         +---> s5_soil_properties (build_soil_properties.py)
    |         |
    |         +---> s4_fulldom (build_fulldom_hires.py)
    |         |         |
    |         +---> s6_groundwater (build_groundwater.py)
    |         |         |
    |         |         +---> s7_spatial_metadata (validation)
    |         |
    |         +---> s8_forcing (convert_forcing_to_ldasin.py)
    |
    +---> s9_namelists (generate_namelists.py)  <-- depends on s3,s4,s5,s6,s8
              |
              v
         s10_execution (run_wrfhydro.py)
              |
              v
         s11_output (processing)
```

**Parallelism**: After s2 (geo_em), stages s3, s4, s5, s6, and s8 can run in parallel. Stage s9 is the synchronization point.

---

## Stage Details

### s0: Configuration

**Purpose**: Define the simulation parameters and verify data availability.

**Inputs**:
- Basin shapefile path
- Simulation time period (start/end dates)
- Grid spacing (dx, default 1000 m)
- LCC projection parameters (truelat1, truelat2, stand_lon)
- Data paths (DEM, land cover, HWSD, forcing)
- MPI process count

**Outputs**: No files; parameters passed to downstream tools via CLI arguments.

**Decision points**:
- Choose dx based on basin size: 1000 m for medium basins (1,000-50,000 km^2), 250 m for small basins (<1,000 km^2)
- AGGFACTRT=4 is the default (routing grid 4x finer than LSM)
- For basins in China, use CMFD forcing; outside China, use MSWX
- truelat1/truelat2 should bracket the basin latitude (e.g., 30/60 for mid-latitudes)

---

### s1: Lambert Domain Definition

**Tool**: `define_lambert_domain.py` (243 lines)

**Inputs**: basin_shp, dx, truelat1, truelat2, stand_lon, buffer_cells
**Outputs**: `domain_def.json`

**Procedure**:
1. Read basin shapefile, compute geographic bounds
2. Build LCC projection using WRF sphere R=6370000 m
3. Project basin extent to LCC, add buffer cells
4. Compute grid dimensions (e_we, e_sn)
5. Compute domain centre in geographic coordinates
6. Rebuild projection centred on actual domain centre
7. Save domain_def.json

**Validation**:
- Basin must be fully contained within the domain
- Grid dimensions >= 4 in each direction
- domain_def.json contains all required keys

**If it fails**: See dt_007 (WGS84 vs WRF sphere)

---

### s2: geo_em.d01.nc Construction

**Tool**: `build_geo_em.py` (988 lines)

**Inputs**: domain_json, dem_path, landcover_path, hwsd_raster, hwsd_mdb
**Outputs**: `DOMAIN/geo_em.d01.nc` (39 variables)

**Procedure**:
1. Load domain definition, build LCC transformers
2. Compute coordinate arrays for mass, U, V, and corner stagger grids
3. Compute Lambert map scale factors at all stagger points
4. Compute Coriolis parameters (E, F) and grid rotation angles
5. Resample DEM to LCC grid (bilinear) -> HGT_M
6. Resample UMD land cover (nearest) -> apply UMD-to-USGS crosswalk -> LU_INDEX, LANDUSEF
7. Compute LANDMASK from LU_INDEX (water=0, land=1)
8. Resample HWSD raster, classify via USDA texture triangle -> SCT_DOM, SOILCTOP, SOILCBOT
9. Compute SOILTEMP (empirical function of elevation and latitude)
10. Compute GREENFRAC and LAI12M from climatological LUT by land use class
11. Compute corner coordinate global attributes
12. Write NetCDF with all 39 variables and WRF global attributes (MMINLU="USGS")
13. Validate output (check dimensions, attributes, fractional sums)

**Validation**:
- 39 variables present
- MMINLU = "USGS" (critical — see dt_008)
- LANDUSEF fractional sums = 1.0
- SOILTEMP > 230 K for land cells (see dt_009)
- MAPFAC_M in range 0.5-2.0

**If it fails**: See dt_008 (MMINLU), dt_009 (SOILTEMP=0K)

---

### s3: wrfinput_d01.nc Construction

**Tool**: `build_wrfinput.py` (274 lines)

**Inputs**: geo_em, output_path, start_month, soilparm_tbl
**Outputs**: `DOMAIN/wrfinput_d01.nc`

**Procedure**:
1. Read geo_em variables (XLAT_M, XLONG_M, HGT_M, LU_INDEX, SCT_DOM, GREENFRAC, LAI12M, SOILTEMP, LANDMASK)
2. Rename per WRF-Hydro convention (XLAT_M->XLAT, HGT_M->HGT)
3. Parse SOILPARM.TBL for REFSMC per soil type
4. Compute initial SMOIS (4 layers, REFSMC for cell's soil type)
5. Compute initial TSLB (interpolate TSK=290K to TMN=SOILTEMP)
6. Set defaults: SNOW=0, CANWAT=0, SEAICE=0, TSK=290K
7. Compute XLAND (1=land, 2=water) and SHDMAX/SHDMIN from GREENFRAC
8. Write wrfinput_d01.nc with copied geo_em global attributes

**Validation**:
- soil_layers_stag = 4
- SMOIS > 0 for land cells
- TMN > 200 K (no zero-K values)

---

### s4: Fulldom_hires.nc Construction

**Tool**: `build_fulldom_hires.py` (492 lines)

**Inputs**: geo_em, domain_json, dem_path, basin_shp, output_path, aggfactrt, stream_threshold
**Outputs**: `DOMAIN/Fulldom_hires.nc`

**Procedure**:
1. Compute routing grid dimensions: nx_rt = e_we * AGGFACTRT, ny_rt = e_sn * AGGFACTRT
2. Reproject DEM to routing LCC grid (bilinear)
3. Run WhiteboxTools: breach_depressions -> d8_pointer -> d8_flow_accumulation
4. Convert WBT D8 encoding to ArcGIS/WRF-Hydro D8 encoding
5. Threshold flow accumulation for channel extraction
6. Compute Strahler stream order via topological sort
7. Rasterize basin shapefile for basn_msk
8. Resample LU_INDEX from geo_em to routing resolution
9. Compute lat/lon for each routing cell
10. Write Fulldom_hires.nc with CRS variable and spatial reference

**CRITICAL**: After writing, ensure boundary cells have FLOWDIRECTION=0 (see dt_001). Also ensure x/y variables have `resolution` attribute (see dt_002, dt_003).

**Validation**:
- FLOWDIRECTION values in {0, 1, 2, 4, 8, 16, 32, 64, 128}
- Boundary cells have FLOWDIRECTION = 0
- CHANNELGRID has > 0 channel cells
- x and y variables have `resolution` attribute

**If it fails**: See dt_001 (boundary flow), dt_003 (missing x coordinate), dt_010 (D8 encoding)

---

### s5: soil_properties.nc Construction

**Tool**: `build_soil_properties.py` (302 lines)

**Inputs**: geo_em, output_path, soilparm_tbl, mptable_tbl
**Outputs**: `DOMAIN/soil_properties.nc`

**Procedure**:
1. Read ISLTYP (SCT_DOM) and IVGTYP (LU_INDEX) from geo_em
2. Parse SOILPARM.TBL for BB, DRYSMC, MAXSMC, REFSMC, SATPSI, SATDK, SATDW, WLTSMC, QTZ
3. Parse MPTABLE.TBL &noahmp_usgs_parameters for CWPVT, HVT, MFSNO, VCMX25, MP
4. For each cell: lookup soil params (4 layers identical), vegetation params
5. Write soil_properties.nc with 18 variables

**Validation**:
- smcmax > 0 for land cells
- bexp > 0 for land cells

---

### s6: Groundwater and Ancillary Files

**Tool**: `build_groundwater.py` (416 lines)

**Inputs**: geo_em, domain_json, basin_shp, output_dir, hydro_tbl
**Outputs**: GWBASINS.nc, GWBUCKPARM.nc, hydro2dtbl.nc, GEOGRID_LDASOUT_Spatial_Metadata.nc

**Procedure**:
1. Rasterize basin shapefile to LSM grid -> GWBASINS.nc (BASIN=1 for all basin cells)
2. Create GWBUCKPARM.nc with default bucket params (Coeff=1, Expon=3, Zmax=50, Zinit=10)
3. Parse HYDRO.TBL for OV_ROUGH per veg type and soil hydraulic params per soil type
4. Build hydro2dtbl.nc with LKSAT, OV_ROUGH2D, SMCMAX1, SMCREF1, SMCWLT1
5. Create GEOGRID_LDASOUT_Spatial_Metadata.nc with CRS and coordinate variables

**CRITICAL**: GEOGRID_LDASOUT_Spatial_Metadata.nc x/y variables MUST have `resolution` attribute (see dt_002).

---

### s7: Spatial Metadata Validation

**Tool**: None (manual validation step)

**Purpose**: Verify that x and y coordinate variables in Fulldom_hires.nc and GEOGRID_LDASOUT_Spatial_Metadata.nc have the `resolution` attribute. This is the most common cause of WRF-Hydro startup failures.

**Procedure**:
1. Open Fulldom_hires.nc, check `x.resolution` and `y.resolution` attributes exist
2. Open GEOGRID_LDASOUT_Spatial_Metadata.nc, check same
3. If missing, add: `ds['x'].resolution = float(dxrt)` (or dx for metadata file)

**If attribute is missing**: See dt_002, dt_003

---

### s8: Forcing Conversion to LDASIN

**Tool**: `convert_forcing_to_ldasin.py` (556 lines)

**Inputs**: forcing_dir, grid_nc, geo_em, domain_json, output_dir, start_date, end_date
**Outputs**: `FORCING/YYYYMMDDHH.LDASIN_DOMAIN1` files (one per hour)

**Unit conversion table**:

| VIC column | VIC unit | WRF-Hydro variable | WRF-Hydro unit | Conversion |
|------------|----------|--------------------|-----------------|-----------:|
| Col 0: Temperature | deg C | T2D | K | +273.15 |
| Col 1: Precipitation | mm/3hr | RAINRATE | mm/s = kg/m^2/s | /10800 |
| Col 2: Pressure | kPa | PSFC | Pa | *1000 |
| Col 3: Shortwave | W/m^2 | SWDOWN | W/m^2 | direct |
| Col 4: Longwave | W/m^2 | LWDOWN | W/m^2 | direct |
| Col 5: Vapor pressure | kPa | Q2D | kg/kg | q=0.622*e/(p-0.378*e) |
| Col 6: Wind speed | m/s | U2D, V2D | m/s | wind*cos(45), wind*sin(45) |

**Temporal interpolation**: VIC 3-hourly to hourly
- Linear interpolation: T2D, PSFC, LWDOWN, Q2D, U2D, V2D
- Step (piecewise constant): RAINRATE, SWDOWN

**Spatial interpolation**: scipy.interpolate.griddata (linear + nearest fill) from VIC lat/lon cells to LCC grid

**Validation**:
- T2D > 200 K
- RAINRATE >= 0
- PSFC > 10000 Pa
- File count = N_days * 24

**If it fails**: See dt_005 (no forcing data), dt_011 (RAINRATE units), dt_012 (VP->Q2D)

---

### s9: Namelist Generation

**Tool**: `generate_namelists.py` (384 lines)

**Inputs**: domain_dir, forcing_dir, output_dir, start_date, end_date, output_timestep
**Outputs**: `namelist.hrldas`, `hydro.namelist`

**Key parameters**:
- KHOUR = (end_date - start_date + 1 day) in hours
- FORCING_TIMESTEP = 3600 (hourly LDASIN)
- DXRT = dx / AGGFACTRT (auto-detected from domain files)
- AGGFACTRT = Fulldom x-dim / wrfinput x-dim (auto-detected)
- channel_option = 3 (diffusive wave, gridded)
- DTRT_CH = 10, DTRT_TER = 10 (seconds)

**Validation**:
- AGGFACTRT matches actual dimension ratio
- All 8 DOMAIN files referenced exist
- FORCING directory has LDASIN files

**If it fails**: See dt_013 (DTRT too large), dt_014 (AGGFACTRT mismatch)

---

### s10: WRF-Hydro Execution

**Tool**: `run_wrfhydro.py` (291 lines)

**Inputs**: run_dir, nproc, timeout
**Outputs**: LDASOUT, CHRTOUT, RTOUT, GWOUT NetCDF files

**Procedure**:
1. Preflight: verify DOMAIN/, FORCING/, namelists, all 8 required domain files
2. Symlink wrf_hydro.exe and *.TBL files into run directory
3. Execute: `mpirun -np N ./wrf_hydro.exe`
4. Check stdout for "The model finished successfully"
5. Collect output file inventory and sizes

**Success criterion**: stdout contains "The model finished successfully"

**Expected runtimes**:
- 7-day run, 126x116 grid, 4 MPI: ~2-5 minutes
- 1-year run, 126x116 grid, 8 MPI: ~30-60 minutes

**If it fails**: Check diag_hydro.00000 for error messages. See dt_001, dt_004, dt_013.

---

### s11: Output Processing

**Tool**: None yet (future development)

**Available outputs**:
- `*.LDASOUT_DOMAIN1`: Land surface variables (ET, soil moisture, runoff, snow) on LSM grid, hourly
- `*.CHRTOUT_DOMAIN1`: Channel streamflow at forecast points, hourly
- `*.RTOUT_DOMAIN1`: Routing variables (surface head, groundwater, channel flow) on routing grid
- `*.GW_DOMAIN1`: Groundwater bucket state

**Key variables for analysis**:
- LDASOUT: `SFCRNOFF` (surface runoff, mm), `UGDRNOFF` (subsurface runoff, mm), `ETRAN` (transpiration), `SOIL_M` (soil moisture)
- CHRTOUT: `streamflow` (m^3/s at forecast points)

---

## Coverage Summary

| Stage | Tool | Skill Doc | Triplets |
|-------|:----:|:---------:|:--------:|
| s0_config | - | planned | dt_006 |
| s1_domain | define_lambert_domain | planned | dt_007 |
| s2_geo_em | build_geo_em | planned | dt_008, dt_009 |
| s3_wrfinput | build_wrfinput | planned | - |
| s4_fulldom | build_fulldom_hires | planned | dt_001, dt_003, dt_010 |
| s5_soil_properties | build_soil_properties | planned | - |
| s6_groundwater | build_groundwater | planned | - |
| s7_spatial_metadata | - | planned | dt_002 |
| s8_forcing | convert_forcing_to_ldasin | planned | dt_005, dt_011, dt_012 |
| s9_namelists | generate_namelists | planned | dt_013, dt_014 |
| s10_execution | run_wrfhydro | planned | dt_004 |
| s11_output | - | planned | - |
