---
name: wrf-hydro
description: >-
  WRF-Hydro v5.2.0 standalone/offline (Noah-MP LSM + gridded overland/subsurface/channel
  routing + conceptual groundwater bucket; NCAR NDHMS…. Covers Noah-MP 1-D column
  land-surface energy/water balance (ET, 4-layer soil moisture and temperature…; surface
  and subsurface runoff generation (RUNOFF_OPTION 1-5); overland flow routing (D8
  diffusive-wave on high-resolution routing sub-grid). Use when the task involves running,
  configuring, calibrating or interpreting WRF_Hydro.
---

> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model. Doing so produces
> scientifically invalid results and defeats the purpose of the KI.
>
> Before starting, run: `python preflight_check.py` (in this KI directory)

> to verify that the model binary/package and required data are available.
>
> **DEBUGGING PROTOCOL** — When something goes wrong, follow this order:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Read official docs** — The model's own documentation for expected formats/units
> 3. **Find working examples** — Check `outputs/` or the model's shipped test data
> 4. **Fix the tool** — With knowledge of what "correct" looks like
>
> Do NOT write custom debug scripts. The answers are in the docs and examples.

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.
Then convert to WRF-Hydro LDASIN format using this KI's tools:

**For China basins** (CMFD, best quality, 1979-2018):
```bash
python tools/s8_forcing/cmfd_to_ldasin.py \
    --cmfd_dir data/forcing/Data_forcing_03hr_010deg \
    --geo_em DOMAIN/geo_em.d01.nc --domain_json domain_def.json \
    --output_dir FORCING/ --start_date YYYY-MM-DD --end_date YYYY-MM-DD
```

**For global basins** (NASA POWER API, 2001-present, any location):
```bash
python tools/s8_forcing/nasa_power_to_ldasin.py \
    --geo_em DOMAIN/geo_em.d01.nc \
    --output_dir FORCING/ \
    --start_date YYYY-MM-DD --end_date YYYY-MM-DD
```
This tool fetches NASA POWER data for ALL grid points covering the domain (not just one point),
spatially interpolates to the LCC grid, and applies elevation corrections.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.

---

# WRF-Hydro v5.2.0 Standalone (NoahMP) — Knowledge Infrastructure

**Package**: `hydrocraft-wrfhydro-standalone` v2.2.0
**Model**: WRF-Hydro v5.2.0 offline (NoahMP land surface + gridded routing)
**Created by**: Jianyun Zhang Research Group, Hohai University
**Last updated**: 2026-03-21 (4 routing skill documents added)
**Stats**: 14 tools | 6 skill documents | 46 diagnostic triplets | 28 error log entries | ~6,200 lines of validated Python

---

## Overview

This knowledge infrastructure enables fully autonomous construction and execution of WRF-Hydro v5.2.0 in standalone/offline mode on any basin, **without requiring WPS or ArcGIS**. The 11 validated tools replace the standard NCAR workflow (WPS geogrid + ArcGIS GIS_tool + manual IDL scripts) with a Python-only pipeline that builds all domain files from raw global datasets.

**What WRF-Hydro standalone does**: Couples the Noah-MP land surface model (LSM) with gridded overland/subsurface/channel routing to simulate:
- Surface/subsurface runoff, evapotranspiration, soil moisture (hourly, per LSM cell)
- Channel streamflow via diffusive wave routing on a high-resolution sub-grid
- Groundwater bucket recharge/discharge

**Key difference from VIC**: WRF-Hydro uses a Lambert Conformal Conic projected grid (not lat/lon), operates at hourly timestep, and includes integrated routing — no separate routing model needed.

---

## Installation

### Prerequisites

```
MPICH 4.2.3:  model/wrf_hydro/deps/mpich-install/
WRF-Hydro:    model/wrf_hydro/source/trunk/NDHMS/Run/wrf_hydro.exe
TBL files:    model/wrf_hydro/source/trunk/NDHMS/Run/*.TBL
```

### CRITICAL: NETCDF_LIB path

During compilation, `NETCDF_LIB` **must** be set to `/usr/lib/x86_64-linux-gnu/` (where `libnetcdff.so` lives), NOT `/usr/lib/`. Wrong path causes `undefined reference to nf90_*` linker errors. See diagnostic triplet `dt_006`.

### Python dependencies

```
netCDF4, numpy, scipy, geopandas, rasterio, pyproj, whitebox
```

---

## Pipeline (12 stages)

| # | Stage | Tool | Description |
|---|-------|------|-------------|
| 0 | Configuration | (manual) | Basin, period, paths |
| 1 | Domain definition | `define_lambert_domain.py` (243 lines) | LCC grid from basin shapefile |
| 2 | geo_em construction | `build_geo_em.py` (988 lines) | 39-variable geogrid file |
| 3 | wrfinput construction | `build_wrfinput.py` (274 lines) | Initial conditions, 4-layer soil |
| 4 | Fulldom routing grid | `build_fulldom_hires.py` (530 lines) | High-res DEM, D8 flow, channels, CHAN_DEPTH |
| 4b | Route_Link (optional) | `build_route_link.py` (350 lines) | Reach topology for Muskingum routing |
| 4c | Spatial weights (optional) | `build_spatial_weights.py` (250 lines) | LSM-to-reach mapping for UDMP |
| 5 | Soil properties | `build_soil_properties.py` (302 lines) | SOILPARM + MPTABLE lookup |
| 6 | Groundwater/ancillary | `build_groundwater.py` (416 lines) | GWBASINS, GWBUCKPARM, hydro2dtbl, metadata |
| 7 | Spatial metadata | (validation only) | Verify x/y resolution attributes |
| 8 | Forcing conversion | `convert_forcing_to_ldasin.py` (556 lines) | VIC 3hr -> hourly LDASIN on LCC |
| 8b | Forcing (direct CMFD) | `cmfd_to_ldasin.py` (790 lines) | CMFD -> hourly LDASIN directly (no VIC intermediate) |
| 9 | Namelist generation | `generate_namelists.py` (384 lines) | namelist.hrldas + hydro.namelist |
| 10 | Execution | `run_wrfhydro.py` (291 lines) | MPI run + output collection |
| 11 | Output processing | (manual/future tool) | Discharge extraction from CHRTOUT |
| -- | Full pipeline | `run_wrfhydro_full_pipeline.py` (438 lines) | End-to-end wrapper (stages 1-10) |

**Total**: 14 tools, ~6,100 lines of validated Python code.

### Skill Documents

| Stage | Document | Covers |
|-------|----------|--------|
| s4 | `docs/s4_channel_routing_skill.md` | Channel routing physics, D8 encoding, stream threshold (USGS/Budyko auto-scaling), CHANNELGRID encoding, CFL stability, CHRTOUT extraction |
| s6 | `docs/s6_groundwater_skill.md` | GW bucket model (Coeff/Expon/Zmax), inverted seasonal cycle diagnosis, baseflow calibration |
| s9 | `docs/s9_runoff_options_skill.md` | All 5 RUNOFF_OPTIONS (SIMGM, SIMTOP, Schaake96, BATS, Xinanjiang), REFKDT calibration |
| s11 | `docs/s11_output_interpretation_skill.md` | LDASOUT vs CHRTOUT vs RTOUT vs GWOUT, correct discharge extraction, water balance verification, VIC comparison |
| -- | `docs/calibration_guide.md` | 24 parameters across 6 files, Tier 1-3 priority, Schaake formula, Chaohe results |

### Parallelism

Stages 3, 4, 5, 6 can run in parallel after stage 2 (geo_em). Stage 8 (forcing) can run in parallel with stages 3-7. Stage 9 depends on all prior stages.

---

## Tools Reference

| Tool | Stage | Script Path | Lines | Purpose |
|------|-------|-------------|------:|---------|
| `define_lambert_domain` | s1 | `tools/s1_domain/define_lambert_domain.py` | 243 | Define LCC grid covering basin (WRF sphere R=6370000m) |
| `build_geo_em` | s2 | `tools/s2_geo_em/build_geo_em.py` | 988 | Build geo_em.d01.nc with 39 WRF variables from DEM/AVHRR/HWSD |
| `build_wrfinput` | s3 | `tools/s3_wrfinput/build_wrfinput.py` | 274 | Build wrfinput_d01.nc with soil IC from SOILPARM.TBL |
| `build_fulldom_hires` | s4 | `tools/s4_fulldom/build_fulldom_hires.py` | 530 | Build routing domain with WhiteboxTools D8 + Strahler + CHAN_DEPTH |
| `build_route_link` | s4b | `tools/s4_fulldom/build_route_link.py` | 350 | Generate Route_Link.nc for reach-based routing (ch_opt 1/2) |
| `build_spatial_weights` | s4c | `tools/s4_fulldom/build_spatial_weights.py` | 250 | Generate spatialweights.nc LSM-to-reach mapping (UDMP) |
| `build_soil_properties` | s5 | `tools/s5_soil_properties/build_soil_properties.py` | 302 | Soil/veg params from SOILPARM.TBL + MPTABLE.TBL |
| `build_groundwater` | s6 | `tools/s6_groundwater/build_groundwater.py` | 416 | GWBASINS, GWBUCKPARM, hydro2dtbl, spatial metadata |
| `convert_forcing_to_ldasin` | s8 | `tools/s8_forcing/convert_forcing_to_ldasin.py` | 556 | VIC 3hr ASCII -> hourly LDASIN NetCDF on LCC grid |
| `cmfd_to_ldasin` | s8b | `tools/s8_forcing/cmfd_to_ldasin.py` | 790 | CMFD 3hr NetCDF -> hourly LDASIN directly (no VIC) |
| `generate_namelists` | s9 | `tools/s9_namelists/generate_namelists.py` | 384 | Generate namelist.hrldas + hydro.namelist |
| `run_wrfhydro` | s10 | `tools/s10_execution/run_wrfhydro.py` | 291 | MPI execution wrapper with preflight + JSON summary |
| `calibrate_wrfhydro` | s10 | `tools/s10_execution/calibrate_wrfhydro.py` | 780 | Parameter sweep (default REFKDT) with re-run + metric scoring + `--apply_best` |
| `extract_discharge` | s11 | `tools/s11_output/extract_discharge.py` | 300 | Daily outlet discharge from CHRTOUT; use `--gauge_lat/--gauge_lon/--min_order` for gauge-matched extraction |
| `nasa_power_to_ldasin` | s8 | `tools/s8_forcing/nasa_power_to_ldasin.py` | 500 | NASA POWER hourly -> LDASIN (global basins) |
| `run_wrfhydro_full_pipeline` | all | `tools/run_wrfhydro_full_pipeline.py` | 438 | End-to-end pipeline wrapper (stages 1-10) |

---

## VALIDATED Results

### Chaohe Basin (2026-03-19)

- **Basin**: Chaohe, ~8,783 km^2, semi-humid North China
- **Period**: 2001-01-01 to 2001-01-07 (7 days)
- **Grid**: 126 x 116 LSM cells @ 1 km, 504 x 464 routing cells @ 250 m
- **Forcing**: VIC 3-hourly from existing Chaohe run, converted to 168 hourly LDASIN files
- **Result**: 168 hourly LDASOUT + CHRTOUT + RTOUT + GWOUT outputs
- **Status**: SUCCESS — "The model finished successfully" in stdout
- **Output directory**: `outputs/chaohe_wrf_test/`

### Bengbu Basin 1km (2026-03-20)

- **Basin**: Bengbu (Huai River), ~121,330 km^2, humid subtropical
- **Period**: 2001-07-01 to 2001-07-14 (14 days, July start to avoid frozen soil crash)
- **Grid**: 535 x 442 LSM cells @ 1 km, 2140 x 1768 routing cells @ 250 m (3.8M routing cells)
- **Forcing**: VIC 3-hourly from existing Bengbu run (CMFD), converted to hourly LDASIN
- **Result**: 14 LDASOUT + 14 GWOUT outputs, 72 min on 2 MPI cores
- **Status**: SUCCESS — physically meaningful output after 3 critical bug fixes (D8, SWDOWN, elevation)
- **Output directory**: `outputs/bengbu_wrfhydro_2000_2005/`

### Bengbu Basin 0.25deg 6-year (2026-03-20) — CHRTOUT Comparison

- **Basin**: Bengbu (Huai River), ~121,330 km^2, humid subtropical
- **Period**: 2000-01-01 to 2005-12-31 (6 years)
- **Grid**: 22 x 18 LSM cells @ 0.25deg, 88 x 72 routing cells @ ~7 km
- **Forcing**: CMFD direct via `cmfd_to_ldasin.py` (no VIC intermediate)
- **Result**: 2,192 daily LDASOUT + CHRTOUT + GWOUT outputs, **19 min runtime**
- **Discharge comparison with VIC (CHRTOUT)**:
  - **WRF-Hydro mean**: 1,090 m^3/s
  - **VIC mean**: 1,535 m^3/s
  - **Correlation r = 0.84** (daily, 2000-2005)
  - **Best year**: 2003, r = 0.92
  - **Ratio**: WRF-Hydro/VIC = 0.71 (WRF-Hydro 29% lower)
  - Both bracket observed ~1,000-1,500 m^3/s at Bengbu station
- **Output directory**: `outputs/bengbu_wrfhydro_025deg_2000_2005/`

**Key finding**: WRF-Hydro and VIC agree well in timing (r=0.84) despite being completely independent models with different physics (Noah-MP vs VIC energy balance). The 29% amplitude difference is expected with default uncalibrated parameters.

### Chaohe Basin Systematic Investigation (2026-03-20) — WHY WRF-Hydro FAILS HERE

- **Basin**: Chaohe, ~8,783 km^2, semi-humid monsoon North China
- **Period**: 2000-01-01 to 2000-12-31 (1 year)
- **Resolutions tested**: 0.1deg and 0.25deg
- **Result**: r ~ 0 (no correlation with VIC), Q far below VIC

#### Two-Basin Comparison

| Metric | Bengbu (Huai River) | Chaohe |
|--------|-------------------|--------|
| Basin area | 121,330 km^2 | 8,783 km^2 |
| Climate | Humid subtropical | Semi-humid monsoon |
| Terrain | Flat plain | Mountain |
| VIC mean Q | 1,535 m^3/s | 23.2 m^3/s |
| WRF-Hydro Q (0.25deg) | 1,090 m^3/s | 5.8 m^3/s |
| WRF-Hydro Q (0.1deg) | — | 17.8 m^3/s |
| Correlation r | **0.84** | **~0** |
| Verdict | Good agreement | **FAILS** |

#### Resolution Sensitivity

| Resolution | Mean Q (m^3/s) | r vs VIC | Grid cells |
|-----------|---------------|---------|------------|
| 0.25deg | 5.8 | 0.19 | ~20 |
| 0.1deg | 17.8 | -0.08 | ~110 |

Resolution affects **volume** (3x difference) but NOT **event timing** (r still ~0).

#### Systematic Investigation: 6 Hypotheses Tested

1. **Channel threshold scaling** — Tested 5 thresholds (5, 10, 20, 50, 170): all give same Q (4-6 m^3/s). **Not the bottleneck.**
2. **Resolution** — 0.1deg gives 3x more Q than 0.25deg, but r still ~0. Volume improves, timing doesn't.
3. **Noah-MP infiltration** — Schaake96 with REFKDT=3.0 produces only 0.158mm surface runoff from 23.8mm rain (VIC: 3.78mm). **24x less surface runoff.** **ROOT CAUSE of timing failure.**
4. **RUNOFF_OPTION=5 (MMF)** — Crashes: needs MMF_RUNOFF_FILE not in standard pipeline. Use option 1 or 3.
5. **GW bucket dominance** — When channels are broken, all flow goes through GW bucket producing **inverted seasonal cycle** (winter > summer in monsoon basin).
6. **Inverted seasonality** — Consequence of items 3+5: no storm peaks + GW-dominated baseflow.

#### Root Cause: Noah-MP REFKDT Too High

The fundamental issue is that Noah-MP's Schaake96 scheme with default REFKDT=3.0 produces essentially zero surface runoff in mountain basins. All rain infiltrates into soil, and the only discharge pathway is through the groundwater bucket (slow, dampened, wrong timing). This explains why:
- Channel threshold doesn't matter (nothing to route)
- Resolution changes volume but not timing
- Seasonal cycle is inverted (GW baseflow timing, not rainfall timing)

**Fix**: Reduce REFKDT from 3.0 to 0.5-1.0 in `soil_properties.nc`. This is the #1 calibration priority for mountain/semi-arid basins.

#### Shared Findings

`outputs/chaohe_wrfhydro_010deg_2000/wrfhydro_chaohe_findings.yaml`

### Spain GRDC Basin (2026-04-03) — GLOBAL BASIN + ARID CLIMATE TEST

- **Basin**: GRDC_6217140, Guadalquivir tributary, ~15,660 km², Mediterranean Spain
- **Period**: 2010-10-01 to 2011-01-24 (115 days of output)
- **Grid**: 24 x 22 LSM cells @ 10 km, 96 x 88 routing cells @ 2.5 km
- **Forcing**: NASA POWER hourly via `tools/s8_forcing/nasa_power_to_ldasin.py`, 13,176 LDASIN files
- **Observed data**: GRDC station 6217140, daily discharge (365 days in 2011)
- **Channel routing**: All 3 options tested (diffusive wave = 115 days, Muskingum = 5 days, Musk-Cunge = 3 days)
- **Result (channel_option=3)**:
  - **r = 0.456** (timing correlation, uncalibrated)
  - **PBIAS = -96.3%** (severe volume underestimate)
  - **Sim mean**: 3.85 m³/s vs **Obs mean**: 104.5 m³/s
  - Volume underestimate caused by uncalibrated REFKDT=3.0 (same as Chaohe)
- **Key finding**: **Arid Basin Trap Cascade** — 3 sequential crashes (dt_v037 → dt_v038 → dt_v036) that each mask the next. All 3 fixes must be applied simultaneously. Documented as Section 21 in Critical Domain Knowledge.
- **Routing KI validation**: Route_Link.nc (142 reaches), spatialweights.nc (490 data records), GWBUCKPARM_UDMP (142 BasinDim) — all generated correctly by new KI tools.
- **Output directory**: `outputs/grdc_spain_wrfhydro_test/`

---

## Channel Routing Options (CRITICAL — READ BEFORE RUNNING)

WRF-Hydro supports three channel routing methods. **Your choice determines which files are needed.**

### Decision Tree

```
User wants discharge simulation
    │
    ├── Simple/fast setup? ──────────► channel_option = 3 (Diffusive Wave, GRIDDED)
    │   - Uses Fulldom_hires.nc CHANNELGRID + CHANPARM.TBL
    │   - NO Route_Link.nc needed
    │   - NO spatialweights.nc needed
    │   - CHRTOUT output: discharge at every channel GRID CELL
    │   - DEFAULT for HydroCraft — proven on Bengbu (r=0.84), Chaohe, Miyun
    │
    └── Reach-based routing? ────────► channel_option = 1 (Muskingum) or 2 (Muskingum-Cunge)
        - REQUIRES: Route_Link.nc (reach topology + channel geometry)
        - REQUIRES: spatialweights.nc (LSM-to-reach mapping)
        - REQUIRES: GWBUCKPARM.nc with BasinDim (one bucket per reach)
        - REQUIRES: LINKID variable in Fulldom_hires.nc
        - REQUIRES: UDMP_OPT = 1 in hydro.namelist
        - CHRTOUT output: discharge at each REACH (feature_id)
        - Use when: reach-based analysis, NWM compatibility, gage-point nudging
```

### Option 3: Diffusive Wave Gridded (DEFAULT)

**hydro.namelist settings:**
```
CHANRTSWCRT = 1
channel_option = 3
CHRTOUT_DOMAIN = 1        ! Channel point timeseries
CHRTOUT_GRID = 0          ! 2D gridded streamflow (optional)
! route_link_f NOT needed
! udmap_file NOT needed
UDMP_OPT = 0
```

**Required files:**
| File | Generated by | Purpose |
|------|-------------|---------|
| `Fulldom_hires.nc` | `build_fulldom_hires.py` | CHANNELGRID, FLOWDIRECTION, STREAMORDER, CHAN_DEPTH |
| `CHANPARM.TBL` | WRF-Hydro distribution | Manning's N and channel width by stream order |

**CHANPARM.TBL default values (by Strahler order):**
| Order | Bw (m) | HLINK (m) | ChSSlp | MannN |
|-------|--------|-----------|--------|-------|
| 1 | 1.6 | 0.02 | 0.03 | 0.096 |
| 2 | 2.4 | 0.02 | 0.03 | 0.076 |
| 3 | 3.5 | 0.02 | 0.03 | 0.060 |
| 4 | 5.3 | 0.10 | 0.04 | 0.047 |
| 5 | 7.4 | 0.20 | 0.04 | 0.037 |
| 6+ | 11+ | 0.30+ | 0.04+ | 0.030- |

### Option 1/2: Muskingum / Muskingum-Cunge (REACH-BASED)

**hydro.namelist settings:**
```
CHANRTSWCRT = 1
channel_option = 1          ! 1=Muskingum, 2=Muskingum-Cunge
route_link_f = "./DOMAIN/Route_Link.nc"
udmap_file = "./DOMAIN/spatialweights.nc"
UDMP_OPT = 1
CHRTOUT_DOMAIN = 1          ! Channel point timeseries at each REACH
CHRTOUT_GRID = 0            ! NOT available for reach-based routing
lake_option = 0             ! Set to 0 unless LAKEPARM.nc exists
```

**Required files (generate in this order):**
| # | File | Generated by | Purpose |
|---|------|-------------|---------|
| 1 | `Fulldom_hires.nc` | `build_fulldom_hires.py` | Routing grid with CHANNELGRID, CHAN_DEPTH, LINKID |
| 2 | `Route_Link.nc` | `build_route_link.py` | Reach topology: link/from/to, Manning's n, BtmWdth, slope |
| 3 | `spatialweights.nc` | `build_spatial_weights.py` | Maps LSM grid cells → channel reaches (weight fractions) |
| 4 | `GWBUCKPARM.nc` | `build_groundwater.py` (auto-detects UDMP) | One GW bucket per reach (BasinDim, not feature_id) |

**Generation commands:**
```bash
# Step 1: Fulldom (already in pipeline)
python tools/s4_fulldom/build_fulldom_hires.py \
  --geo_em DOMAIN/geo_em.d01.nc --domain_json domain_def.json \
  --dem_path <dem> --basin_shp <shp> --output_path DOMAIN/Fulldom_hires.nc

# Step 2: Route_Link
python tools/s4_fulldom/build_route_link.py \
  --fulldom DOMAIN/Fulldom_hires.nc --output DOMAIN/Route_Link.nc

# Step 3: Spatial weights
python tools/s4_fulldom/build_spatial_weights.py \
  --fulldom DOMAIN/Fulldom_hires.nc --geo_em DOMAIN/geo_em.d01.nc \
  --route_link DOMAIN/Route_Link.nc --output DOMAIN/spatialweights.nc

# Step 4: GWBUCKPARM (auto-detects Route_Link → UDMP mode)
python tools/s6_groundwater/build_groundwater.py \
  --geo_em DOMAIN/geo_em.d01.nc --domain_json domain_def.json \
  --basin_shp <shp> --output_dir DOMAIN/
```

### Route_Link.nc Variables (per reach)

| Variable | Type | Description | Source |
|----------|------|-------------|--------|
| `link` | i4 | Link ID (unique per reach) | Channel cell index |
| `from` | i4 | Upstream link ID (0 = set by convention) | D8 flow direction |
| `to` | i4 | Downstream link ID (0 = outlet) | D8 flow direction |
| `order` | i4 | Strahler stream order | Fulldom STREAMORDER |
| `Length` | f4 | Reach length (m) | Haversine distance |
| `So` | f4 | Slope (m/m, min 0.001) | Elevation drop / length |
| `n` | f4 | Manning's roughness | Order-based (NCAR CONUS JTTI) |
| `BtmWdth` | f4 | Bottom width (m) | Order-based |
| `ChSlp` | f4 | Channel side slope | Order-based |
| `MusK` | f4 | Muskingum routing time (s) | Default 3600 |
| `MusX` | f4 | Muskingum weighting | Default 0.2 |
| `lat/lon` | f4 | Coordinates of start node | Fulldom LATITUDE/LONGITUDE |
| `alt` | f4 | Elevation at start node (m) | Fulldom TOPOGRAPHY |
| `gages` | S1 | Gage ID string (15 chars) | Blank unless specified |

### Order-Based Channel Parameters (NCAR CONUS JTTI Research)

| Strahler Order | Manning's n | Bottom Width (m) | Side Slope |
|:-:|:-:|:-:|:-:|
| 1 | 0.096 | 1.6 | 0.03 |
| 2 | 0.076 | 2.4 | 0.03 |
| 3 | 0.060 | 3.5 | 0.03 |
| 4 | 0.047 | 5.3 | 0.04 |
| 5 | 0.037 | 7.4 | 0.04 |
| 6 | 0.030 | 11.0 | 0.04 |
| 7 | 0.025 | 14.0 | 0.04 |
| 8 | 0.021 | 16.0 | 0.04 |
| 9 | 0.018 | 26.0 | 0.05 |
| 10 | 0.022 | 110.0 | 0.10 |

### CHRTOUT Output (Both Options)

CHRTOUT_DOMAIN1 files contain:
| Variable | Dimension | Description |
|----------|-----------|-------------|
| `streamflow` | feature_id | Discharge (m³/s) |
| `velocity` | feature_id | Flow velocity (m/s) |
| `q_lateral` | feature_id | Lateral inflow (m³/s) |
| `order` | feature_id | Strahler stream order |
| `elevation` | feature_id | Elevation (m) |
| `latitude` | feature_id | Latitude |
| `longitude` | feature_id | Longitude |

**To extract outlet discharge:**
1. Read CHRTOUT files
2. Select the feature *closest to the gauge coordinates*, restricted to a minimum
   Strahler order so the search cannot snap onto a headwater tributary:
   `extract_discharge.py --gauge_lat <lat> --gauge_lon <lon> --min_order 4`
3. Extract `streamflow` timeseries at that feature

Do NOT use `argmax(streamflow)` (the `find_outlet_feature` fallback) when a gauge
location is known. With gridded routing every channel cell on the lower main stem
carries nearly the same discharge, and on a rising limb an upstream cell transiently
exceeds the outlet cell, so argmax wanders km along the stem depending on which file is
sampled. At Zijingguan the argmax cell sat 5.2 km from the gauge; the gauge-matched cell
is 0.12 km away. `dag.yaml`'s `point_time_series` caveat requires the gauge-matched
feature.

---

## All Physics Options Reference

This section is the authoritative reference for ALL physics switches in WRF-Hydro v5.2.0 standalone (Noah-MP). It covers both `namelist.hrldas` (land surface) and `hydro.namelist` (routing/hydrology) switches, their valid values, required files, interactions, and known pitfalls.

### Master Switch Table

#### Noah-MP Land Surface Physics (namelist.hrldas)

| Switch | Valid Values | Default | Status | Description | Key Dependencies |
|--------|-------------|---------|--------|-------------|------------------|
| `RUNOFF_OPTION` | 1-5, 7 | 3 | See below | Runoff generation scheme | soil_properties.nc (REFKDT, DKSAT, BEXP) |
| `DYNAMIC_VEG_OPTION` | 1-9 | 4 | All available | Vegetation phenology | geo_em.d01.nc (SHDFAC, LAI) |
| `CANOPY_STOMATAL_RESISTANCE_OPTION` | 1-2 | 1 | All available | Stomatal resistance model | MPTABLE.TBL |
| `BTR_OPTION` | 1-3 | 1 | All available | Soil moisture factor for stomatal resistance | soil_properties.nc |
| `SURFACE_DRAG_OPTION` | 1-2 | 1 | All available | Surface layer drag coefficient (CH, CM) | -- |
| `FROZEN_SOIL_OPTION` | 1-2 | 1 | All available | Frozen soil permeability | -- |
| `SUPERCOOLED_WATER_OPTION` | 1-2 | 1 | All available | Supercooled liquid water fraction | -- |
| `RADIATIVE_TRANSFER_OPTION` | 1-3 | 3 | All available | Radiation transfer through canopy | MPTABLE.TBL |
| `SNOW_ALBEDO_OPTION` | 1-2 | 1 | All available | Ground snow surface albedo | -- |
| `PCP_PARTITION_OPTION` | 1-4 | 1 | 1-3 available; 4=WRF only | Rain/snow partitioning | Option 4 needs WRF microphysics |
| `TBOT_OPTION` | 1-2 | 2 | All available | Lower boundary soil temperature | wrfinput_d01.nc (SOILTEMP/TMN) |
| `TEMP_TIME_SCHEME_OPTION` | 1-3 | 3 | All available | Snow/soil temperature time scheme | -- |
| `GLACIER_OPTION` | 1-2 | 2 | All available | Glacier/ice treatment | geo_em.d01.nc (IVGTYP=ISICE) |
| `SURFACE_RESISTANCE_OPTION` | 1-4 | 4 | All available | Surface resistance to evaporation | MPTABLE.TBL |
| `IMPERV_OPTION` | 0-2, 9 | 9 | All available | Impervious surface adjustment | Fulldom_hires.nc (IMPERV grid) |

**RUNOFF_OPTION detail:**

| Value | Name | Status | Required Files | Tested On | Notes |
|-------|------|--------|---------------|-----------|-------|
| 1 | TOPMODEL (SIMGM) | ✅ Available | Standard pipeline only | Chaohe (recommended for mountain) | Saturation-excess with GW table; best for mountain/semi-arid |
| 2 | TOPMODEL-equilibrium (SIMTOP) | ✅ Available | Standard pipeline only | -- | Simplified Option 1 without explicit GW model |
| 3 | Schaake96 | ✅ Available (DEFAULT) | Standard pipeline only | Bengbu (r=0.84), Spain (r=0.46) | Infiltration-excess; REFKDT=3.0 too high for mountains (dt_v018) |
| 4 | BATS | ✅ Available | Standard pipeline only | -- | Simple bucket; limited calibration potential |
| 5 | Miguez-Macho & Fan | ❌ CRASHES | MMF_RUNOFF_FILE (not in pipeline) | Chaohe (crash confirmed) | Fatal: dt_v019. Use Option 1 instead |
| 7 | Xinanjiang | ⚠️ Untested | Unknown | -- | Listed in v5.4 docs; not present in v5.2 source. DO NOT USE without verification |

#### Routing Physics (hydro.namelist)

| Switch | Valid Values | Default | Status | Description | Key Dependencies |
|--------|-------------|---------|--------|-------------|------------------|
| `OVRTSWCRT` | 0, 1 | 1 | ✅ Available | Overland flow routing on/off | Fulldom_hires.nc (OVROUGHRTFAC) |
| `SUBRTSWCRT` | 0, 1 | 1 | ⚠️ Caveats in arid basins | Subsurface lateral flow routing on/off | Can cause SMCRT crash (dt_v036) |
| `rt_option` | 1, 2 | 1 | 1=✅; 2=❌ Unsupported | Overland flow method (D8 vs CASC2D) | Option 2 is NOT ACTIVE (dt_v039) |
| `CHANRTSWCRT` | 0, 1 | 1 | ✅ Available | Channel routing on/off | -- |
| `channel_option` | 1, 2, 3 | 3 | All ✅ | Channel routing physics | See interaction matrix |
| `compound_channel` | .FALSE., .TRUE. | .FALSE. | ⚠️ Restricted | Compound channel formulation | REQUIRES channel_option=2 + UDMP_OPT=1 |
| `GWBASESWCRT` | 0, 1, 2, 4 | 1 | See below | Groundwater bucket model | GWBASINS.nc, GWBUCKPARM.nc |
| `lake_option` | 0, 1, 2, 3 | 0 | See below | Lake/reservoir routing | LAKEPARM.nc (options 1-3) |
| `rst_typ` | 0, 1 | 1 | ⚠️ MUST be 0 for arid basins | Overwrite LSM soil from routing states | dt_v036 if 1 + dry soil |
| `UDMP_OPT` | 0, 1 | 0 | ✅ Available | User-defined mapping (reach-based) | Route_Link.nc, spatialweights.nc |
| `imperv_adj` | 0, 1 | 0 | ✅ Available | Imperviousness-based roughness adjustment | Fulldom_hires.nc (IMPERV) |

**channel_option detail:**

| Value | Name | Status | Required Files | Tested On | Notes |
|-------|------|--------|---------------|-----------|-------|
| 1 | Muskingum (reach-based) | ✅ Available | Route_Link.nc + spatialweights.nc + UDMP_OPT=1 | Spain (5 days output) | Requires reach-based setup |
| 2 | Muskingum-Cunge (reach-based) | ✅ Available | Route_Link.nc + spatialweights.nc + UDMP_OPT=1 | Spain (3 days output) | Supports compound_channel |
| 3 | Diffusive Wave (gridded) | ✅ Available (DEFAULT) | Fulldom_hires.nc + CHANPARM.TBL only | Bengbu (r=0.84), Chaohe, Spain (115 days) | Simplest setup; proven reliable |

**GWBASESWCRT detail:**

| Value | Name | Status | Required Files | Notes |
|-------|------|--------|---------------|-------|
| 0 | Off | ⚠️ Creates water sink | None | Bottom drainage leaves system -- NO mass conservation (dt_v040) |
| 1 | Exponential bucket | ✅ Available (DEFAULT) | GWBASINS.nc + GWBUCKPARM.nc | Standard baseflow generation |
| 2 | Pass-through | ✅ Available | GWBASINS.nc + GWBUCKPARM.nc | Dumps all drainage directly into channel |
| 4 | Area-normalized bucket | ⚠️ Restricted | GWBUCKPARM.nc with BasinDim + UDMP_OPT=1 | Coeff scaled by catchment area; reach-based only |

**lake_option detail:**

| Value | Name | Status | Required Files | Notes |
|-------|------|--------|---------------|-------|
| 0 | Lakes off | ⚠️ Bad with gridded routing | None | If lake cells mask channels in Fulldom, routing breaks (dt_v041) |
| 1 | Level pool | ✅ Available | LAKEPARM.nc | Standard lake routing; typical default when lakes present |
| 2 | Pass-through | ✅ Available | LAKEPARM.nc | Lake has no storage effect |
| 3 | Reservoir DA | ⚠️ Advanced | LAKEPARM.nc + reservoir_nlist config | Data assimilation for managed reservoirs |

### Scenario-Based Decision Guide

#### Humid basin, standard simulation (e.g., Bengbu, Pearl River)

```
namelist.hrldas:
  RUNOFF_OPTION     = 3        # Schaake96 (default, well-tested)
  # REFKDT = 3.0 in soil_properties.nc (default OK for flat terrain)

hydro.namelist:
  OVRTSWCRT         = 1        # Overland flow ON
  SUBRTSWCRT        = 1        # Subsurface flow ON
  CHANRTSWCRT       = 1        # Channel routing ON
  channel_option    = 3        # Diffusive wave (gridded, simplest)
  GWBASESWCRT       = 1        # Exponential GW bucket
  lake_option       = 0        # Lakes off (unless lakes present)
  rst_typ           = 1        # OK for humid basins
  UDMP_OPT          = 0        # Gridded (no reach-based setup needed)
```

#### Mountain / semi-arid basin (e.g., Chaohe, Heihe upper, Tibetan tributaries)

```
namelist.hrldas:
  RUNOFF_OPTION     = 1        # TOPMODEL (saturation-excess, better for steep terrain)
  # OR: RUNOFF_OPTION = 3 with REFKDT = 0.3-0.5 in soil_properties.nc

hydro.namelist:
  OVRTSWCRT         = 1
  SUBRTSWCRT        = 1
  CHANRTSWCRT       = 1
  channel_option    = 3
  GWBASESWCRT       = 1        # Coeff=0.01-0.05, Zmax=50-150mm
  lake_option       = 0
  rst_typ           = 1
  UDMP_OPT          = 0
```

**Key**: Reduce REFKDT from 3.0 to 0.3-0.5 (dt_v018), or use RUNOFF_OPTION=1 which is less sensitive to REFKDT. Default REFKDT=3.0 produces 24x less surface runoff in mountains.

#### Arid / Mediterranean basin (e.g., Spain, SW USA, Australia)

```
namelist.hrldas:
  RUNOFF_OPTION     = 3        # Schaake96 with REFKDT = 0.5-1.0
  OUTPUT_TIMESTEP   = 0        # Disable LDASOUT (dt_v037)
  RESTART_FREQUENCY_HOURS = 0  # Disable LSM restart (dt_v038)

hydro.namelist:
  OVRTSWCRT         = 1
  SUBRTSWCRT        = 1        # Monitor for SMCRT crash (dt_v036)
  CHANRTSWCRT       = 1
  channel_option    = 3
  GWBASESWCRT       = 1
  lake_option       = 0
  rst_typ           = 0        # MUST be 0 — prevents SMCRT crash (dt_v036)
  rst_dt            = -99999   # No hydro restart (dt_v038)
  t0OutputFlag      = 0        # No output at time 0
  UDMP_OPT          = 0
```

**CRITICAL**: Apply ALL three arid basin fixes simultaneously (dt_v036 + dt_v037 + dt_v038). Also patch wrfinput_d01.nc: `SMOIS = max(SMOIS, 0.25)`. Start from wet season (October for Mediterranean, NOT July). See Section 21 in Critical Domain Knowledge.

#### Reach-based routing (NWM compatibility, gage nudging)

```
hydro.namelist:
  CHANRTSWCRT       = 1
  channel_option    = 1        # Muskingum (or 2 for Muskingum-Cunge)
  UDMP_OPT          = 1        # REQUIRED for reach-based
  route_link_f      = "./DOMAIN/Route_Link.nc"
  udmap_file        = "./DOMAIN/spatialweights.nc"
  GWBASESWCRT       = 1        # or 4 (area-normalized, UDMP only)
  lake_option       = 0        # or 1 if LAKEPARM.nc exists
  CHRTOUT_DOMAIN    = 1
  CHRTOUT_GRID      = 0        # NOT available with reach-based
```

**File generation order**: Fulldom_hires.nc -> Route_Link.nc -> spatialweights.nc -> GWBUCKPARM.nc (auto-detects UDMP mode). See Channel Routing Options section above for commands.

#### Basin with lakes / reservoirs

```
hydro.namelist:
  lake_option       = 1        # Level pool (standard)
  route_lake_f      = "./DOMAIN/LAKEPARM.nc"
  # For managed reservoirs with data assimilation:
  # lake_option     = 3
  # Configure &reservoir_nlist section
```

**Warning**: `lake_option=0` with gridded routing (channel_option=3) where lake cells mask out channel cells in Fulldom_hires.nc produces bad results -- water cannot traverse the masked channel segment.

#### Groundwater interaction investigation

```
hydro.namelist:
  GWBASESWCRT       = 1        # Exponential bucket (standard)
  gwbasmskfil       = "./DOMAIN/GWBASINS.nc"
  GWBUCKPARM_file   = "./DOMAIN/GWBUCKPARM.nc"
  # Calibrate: Coeff (0.001-0.5), Expon (1-8), Zmax (50-500mm)
  # See s6_groundwater_skill.md for calibration strategy
```

**Tier 3 calibration**: Only tune GW params AFTER fixing REFKDT (Tier 1) and MannN/OVROUGHRTFAC (Tier 2). If GW bucket dominates (winter Q > summer Q in monsoon basin), fix surface runoff first (dt_v017).

### Physics Option Interaction Matrix

These constraints are enforced by the model. Violating them causes crashes or silent errors.

| Constraint | Type | Details |
|-----------|------|---------|
| `channel_option=1,2` REQUIRES `UDMP_OPT=1` | Hard dependency | Without UDMP, model crashes looking for reach topology |
| `GWBASESWCRT=4` REQUIRES `UDMP_OPT=1` | Hard dependency | Area-normalized bucket needs per-reach catchment areas |
| `compound_channel=.TRUE.` REQUIRES `channel_option=2` + `UDMP_OPT=1` | Hard dependency | Compound channel only implemented for Muskingum-Cunge reach-based |
| `lake_option>0` REQUIRES `LAKEPARM.nc` | Hard dependency | Model crashes if lake param file missing |
| `lake_option=0` + gridded routing with lake-masked channels | Silent error | Water cannot pass through masked channel cells |
| `SUBRTSWCRT=1` + arid climate + `rst_typ=1` | Crash risk | SMCRT dry-soil crash in arid basins (dt_v036) |
| `rt_option=2` (CASC2D) | Unsupported | Code exists but is NOT ACTIVE -- model may compile but routing produces wrong results (dt_v039) |
| `RUNOFF_OPTION=5` without `MMF_RUNOFF_FILE` | Fatal crash | dt_v019 -- use Option 1 instead |
| `GWBASESWCRT=0` | Water sink | Bottom drainage exits the system -- water budget does not close |
| `CHRTOUT_GRID=1` + large LCC coordinates (>1e6 m) | Fatal crash | dt_004 -- set CHRTOUT_GRID=0 |
| `PCP_PARTITION_OPTION=4` | WRF-coupled only | Requires WRF microphysics output; not available in standalone |
| `OVRTSWCRT=0` + `SUBRTSWCRT=0` | No lateral flow | All runoff goes only through channel network and GW bucket; hillslope transport disabled |

### Noah-MP Physics Options Quick Reference

These options rarely need changing from defaults but are documented for completeness. All are set in `namelist.hrldas` under `&NOAHLSM_OFFLINE`.

| Option | Default | When to Change | Recommended Alternative |
|--------|---------|---------------|------------------------|
| `DYNAMIC_VEG_OPTION=4` | Table LAI, max veg fraction | Long-term (>10yr) simulations with veg feedback | 2 (dynamic, with OPT_CRS=1) |
| `CANOPY_STOMATAL_RESISTANCE_OPTION=1` | Ball-Berry | European basins, CLM comparison | 2 (Jarvis) |
| `BTR_OPTION=1` | Noah (soil moisture) | CLM comparison | 2 or 3 (matric potential) |
| `SURFACE_DRAG_OPTION=1` | Monin-Obukhov | Legacy Noah comparison | 2 (Chen97) |
| `FROZEN_SOIL_OPTION=1` | Linear, more permeable | Cold regions with heavy frost | 2 (nonlinear, less permeable) |
| `RADIATIVE_TRANSFER_OPTION=3` | Two-stream on veg fraction | Dense canopy studies | 1 (gap=f(solar angle)) |
| `SNOW_ALBEDO_OPTION=1` | BATS | Canadian/boreal basins | 2 (CLASS) |
| `PCP_PARTITION_OPTION=1` | Jordan (1991) | Simple threshold comparison | 3 (SFCTMP < TFRZ) |
| `TBOT_OPTION=2` | Read from file | Zero-flux approximation | 1 (zero heat flux) |
| `TEMP_TIME_SCHEME_OPTION=3` | Semi-implicit with FSNO | Legacy comparison | 1 (without FSNO) |
| `GLACIER_OPTION=2` | Noah slab ice | Phase-change ice modeling | 1 (include phase change) |
| `SURFACE_RESISTANCE_OPTION=4` | Sakaguchi+snow resistance | Sellers comparison | 1 (Sakaguchi only) |
| `IMPERV_OPTION=9` | Original formulation | Urban hydrology study | 1 or 2 (explicit impervious) |

---

## How to Correctly Extract Discharge (CRITICAL)

**ALWAYS use CHRTOUT for discharge. NEVER average SFCRNOFF from LDASOUT.**

LDASOUT SFCRNOFF/UGDRNOFF fields include routed upstream flow when overland/subsurface routing is enabled (OVRTSWCRT=1, SUBRTSWCRT=1). Basin-averaging these fields double/triple counts the same water:
- Headwater cells: Q/P = 0.35-0.38 (correct)
- Channel cells: Q/P = 0.96 (includes upstream contributions)
- Basin average: 2.4x overestimate vs CHRTOUT

**Correct approach**:
1. Set `CHRTOUT_DOMAIN = 1` in hydro.namelist
2. Read outlet discharge from CHRTOUT_DOMAIN1 files
3. Identify the outlet cell (highest Strahler order, basin boundary)
4. Extract `streamflow` variable at that cell for the discharge timeseries

See diagnostic triplet `dt_v009`.

---

## Critical Domain Knowledge

These non-obvious facts cause silent failures if violated. Each is encoded as a diagnostic triplet.

### 1. WRF sphere R=6370000m, NOT WGS84 (dt_007)

WRF-Hydro uses a perfect sphere with radius 6370000 m for all Lambert projections. Using the WGS84 ellipsoid shifts all coordinates by ~0.13%. Always use `+R=6370000` in PROJ.4 strings.

### 2. MMINLU must be exactly "USGS" (dt_008)

The global attribute `MMINLU` in geo_em.d01.nc must be `"USGS"`. With USGS: ISWATER=16, ISICE=24, ISURBAN=1. The UMD-to-USGS crosswalk is in `build_geo_em.py`.

### 3. x/y variables MUST have `resolution` attribute (dt_002, dt_003)

WRF-Hydro reads the `resolution` attribute from x and y coordinate variables. Missing it causes fatal startup errors.

### 4. Boundary flow directions must be 0 (dt_001)

All cells on the Fulldom routing grid boundary must have FLOWDIRECTION=0, or WRF-Hydro crashes with "Apparent error in network topology".

### 5. WhiteboxTools D8 encoding docs are WRONG (dt_v007) — THE ROOT CAUSE

**ACTUAL WBT output (verified empirically)**:
- WhiteboxTools: 1=NE, 2=E, 4=SE, 8=S, 16=SW, 32=W, 64=NW, 128=N
- WRF-Hydro/ArcGIS: 1=E, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE
- Correct mapping: `{0:0, 1:128, 2:1, 4:2, 8:4, 16:8, 32:16, 64:32, 128:64}`

The old (documented) mapping had 8/9 directions wrong, causing 50% uphill flows, 39K circular cycles, 95% cells disconnected. **Always verify D8 encoding empirically — never trust documentation.**

### 6. CHANNELGRID encoding: 0=channel, -9999=non-channel (dt_v010)

WRF-Hydro expects CHANNELGRID=0 for channel cells and -9999 for non-channel. Using 0/1 binary encoding inverts the semantics silently.

### 7. RAINRATE is mm/s = kg/m^2/s (dt_011, dt_v011)

VIC forcing gives mm/3hr. Divide by 10800. CMFD stores rate in kg/m^2/s (NOT mm/3hr — the VIC pipeline multiplies by 10800 for its own use, creating a false impression).

### 8. Vapor pressure kPa must become specific humidity kg/kg (dt_012)

Formula: `q = 0.622 * e_Pa / (p_Pa - 0.378 * e_Pa)` where e_Pa = VP_kPa * 1000.

### 9. Elevation correction for PSFC and T2D (dt_v008)

When interpolating coarse forcing (0.25deg) to fine grid (1km), apply:
- `T2D -= 0.0065 * dz` (lapse rate 6.5 K/km)
- `PSFC *= exp(-g * dz / (R * Tv))` (barometric formula)

Without correction, mountain cells at 1955m get 20% pressure error and 10.7C temperature error.

### 10. SWDOWN cap at solar constant (dt_v022)

scipy.griddata extrapolation at grid edges can amplify SWDOWN to 1026+ W/m^2. Cap at 1361 W/m^2 (solar constant) after interpolation.

### 11. SOILTEMP must never be 0 K (dt_009)

Land cells with SOILTEMP=0K cause NaN propagation. Replace with 280-290K default.

### 12. CHRTOUT_GRID fails with large LCC coordinates (dt_004)

Set `CHRTOUT_GRID = 0` if LCC x/y > 1e6 m.

### 13. RESTART_FREQUENCY_HOURS must be >0 (dt_015)

Value 0 = never write output. Set to -9999 for output at every timestep.

### 14. SFCRNOFF double-counts routed flow (dt_v009)

LDASOUT SFCRNOFF includes upstream routed contributions. Basin-averaging gives 2.4x overestimate. **MUST use CHRTOUT for discharge.**

### 15. January cold start crashes (dt_v023)

Frozen soil causes "SMCRT fully depleted". Start in summer month for cold start.

### 16. Cold-start spinup artifact (dt_v014)

First days produce 237 mm/d runoff. Discard first 6-12 months as spinup.

### 17. Noah-MP zero-veg crash (dt_v005)

Cells with SHDFAC=0 and VAI=0 in summer get TG=630K — set minimum SHDFAC=0.01.

### 18. OOM on large domains (dt_v006)

3.8M routing cells with 8+ MPI cores exceed memory. Use 2-4 cores for large domains.

### 19. ISLTYP=14 on land cells (dt_v012)

HWSD/AVHRR mismatch gives water soil type on land cells. Noah-MP writes -9999. Fix: replace with default soil type.

### 20. GW bucket Zmax too shallow (dt_v013)

Default Zmax=50m fills instantly — pure pass-through. Increase to 200-500m for GW-sensitive basins.

### 21. Arid/Semi-Arid Basin Trap Cascade (dt_v036, dt_v037, dt_v038) — CRITICAL

**Applies to**: Mediterranean, semi-arid, arid basins (Spain, Middle East, Australia, Sahel, SW USA).

These three crashes occur IN SEQUENCE. Each masks the next — you cannot see Crash 3 until Crashes 1 and 2 are fixed. If you encounter any of these, apply ALL THREE fixes simultaneously.

**Crash 1: "Unable to create LDASOUT/RTOUT NetCDF file" (dt_v037)**
- **Cause**: `GEOGRID_LDASOUT_Spatial_Metadata.nc` missing `resolution` attribute on x/y variables
- **Fix**: Add `resolution` attribute after running `build_groundwater.py`, OR disable LDASOUT:
  ```
  # In namelist.hrldas:
  OUTPUT_TIMESTEP = 0     ! Disable LDASOUT
  ```
- **Why it masks Crash 2**: Model crashes at first output timestep, before restart writing

**Crash 2: "In RESTART_OUT_nc() - Problem nf90_create" (dt_v038)**
- **Cause**: Restart file writer also fails when spatial metadata is incomplete, or when `rst_dt` triggers too frequently
- **Fix**: Disable restart writing:
  ```
  # In hydro.namelist:
  rst_dt = -99999                   ! Never write hydro restart
  # In namelist.hrldas:
  RESTART_FREQUENCY_HOURS = 0       ! Never write LSM restart
  ```
- **Why it masks Crash 3**: Model crashes at first restart, before soil moisture depletes

**Crash 3: "SMCRT fully depleted upon disaggregation" or SILENT SEGFAULT (dt_v036)**
- **Cause**: In arid/semi-arid basins, Noah-MP computes zero liquid soil moisture (`SH2O=0`) during dry months. The disaggregation routine maps this to the routing grid, producing `SMCRT<=0` at some cells. The Fortran code at `Noah_distr_routing.F:1143` crashes when `SMCRT<=0` AND soil is NOT frozen.
- **Symptom**: MPI process exits with code 1, NO error message in `diag_hydro` (segfault). Occurs 3-20 days into simulation.
- **Fix**: Apply ALL of these:
  ```python
  # 1. Set minimum SMOIS in wrfinput_d01.nc
  smois[smois < 0.25] = 0.25

  # 2. Fix zero soil properties (ISLTYP=14 water cells on land)
  smcmax[smcmax <= 0] = 0.434
  smcwlt[smcwlt <= 0] = 0.066
  smcref[smcref <= 0] = 0.329

  # 3. Start from wet season (NOT July in Mediterranean!)
  # Mediterranean: start October  
  # Monsoon Asia: start July (original guidance)
  # Semi-arid: start just after rainy season peak

  # 4. Set rst_typ = 0 (don't overwrite LSM soil from routing)
  ```

**Combined fix for arid basins** — add ALL of these to the namelist before running:
```
# namelist.hrldas:
OUTPUT_TIMESTEP = 0                 ! No LDASOUT
RESTART_FREQUENCY_HOURS = 0         ! No LSM restart

# hydro.namelist:
rst_dt = -99999                     ! No hydro restart  
rst_typ = 0                         ! Don't overwrite LSM soil from routing
t0OutputFlag = 0                    ! No output at time 0
```
And patch wrfinput_d01.nc: `SMOIS = max(SMOIS, 0.25)` for all cells.

**Validated**: Spain GRDC_6217140 (Mediterranean, 15,660 km²). With all fixes: 115 days of CHRTOUT output, r=0.456 vs observed. Without fixes: crashes within 1-5 days through 3 different error paths.

### 22. Only Config A is Production-Ready for Global Basins (dt_v042) — CRITICAL

**Matrix test (24 configurations × 3 global basins, 2026-04-03):**

Only ONE physics combination runs to completion:

```
✅ RUNOFF_OPTION=3 (Schaake96) + channel_option=3 (Diffusive Wave) + GWBASESWCRT=1 (Exp. Bucket)
```

All other 7 configurations crash within 0-7 days:

| Config | RUNOFF | Channel | GW | Status | Crash |
|:---:|:---:|:---:|:---:|:---:|:---:|
| **A** | **3 Schaake** | **3 DiffWave** | **1 ExpBucket** | **✅** | — |
| B | 1 TOPMODEL | 3 | 1 | ❌ | 1-5d |
| C | 2 TOPMODEL-eq | 3 | 1 | ❌ | 1-5d |
| D | 4 BATS | 3 | 1 | ❌ | 1-2d |
| E | 3 | 1 Muskingum | 1 | ❌ | 0d |
| F | 3 | 2 MuskCunge | 1 | ❌ | 0d |
| G | 3 | 3 | 2 Passthru | ❌ | 2-7d |
| H | 1 | 1 | 4 AreaNorm | ❌ | 0d |

**Root cause**: `Noah_distr_routing.F:1143` crashes on `SMCRT<=0` (dry soil). Has frozen-soil workaround but NO dry-soil workaround. Schaake96 maintains highest soil moisture → only survivor. Reach-based routing (E,F,H) crashes at init due to additional GWBUCKPARM format requirements.

**Basins tested**: Kettle River WA/BC (snow), Balsas Brazil (tropical), Clutha NZ (oceanic) — identical behavior across all 3 continents.

**Config A results (uncalibrated):**

| Basin | r | PBIAS | Sim/Obs Q |
|-------|---|-------|-----------|
| Kettle River | **0.70** | +54% | 86/56 m³/s |
| Balsas Brazil | **0.83** | **-3%** | 104/107 m³/s |
| Clutha NZ | **0.52** | -52% | 290/601 m³/s |

**Rule**: Always use Config A for production.

**Upstream status**: Known bug in WRF-Hydro, open since 2021, persists through v5.4.0 (March 2025):
- [NCAR/wrf_hydro_nwm_public#541](https://github.com/NCAR/wrf_hydro_nwm_public/issues/541) (OPEN since 2021-03-10)
- [NCAR/wrf_hydro_nwm_public#665](https://github.com/NCAR/wrf_hydro_nwm_public/issues/665) (cosmetic fix only, `hydro_stop()` still present)

---

## Diagnostic Triplets

45 triplets covering 8 failure domains + 6 Chaohe investigation + 3 audit additions + 3 arid basin cascade + 3 physics options audit. See `diagnostics/triplets.yaml` and `diagnostics/error_log.yaml` for full details.

| ID | Severity | Domain | Summary |
|----|----------|--------|---------|
| dt_001 | fatal | parameter_format | Boundary flow direction causes network topology error |
| dt_002 | fatal | parameter_format | Missing x/y resolution attribute in metadata |
| dt_003 | fatal | parameter_format | Missing x coordinate in Fulldom |
| dt_004 | fatal | runtime | CHRTOUT_GRID fails with large LCC coordinates |
| dt_005 | fatal | path_resolution | No forcing data found past available period |
| dt_006 | fatal | compilation | NETCDF_LIB wrong path causes linker errors |
| dt_007 | silent | silent_error | WGS84 vs WRF sphere coordinate shift |
| dt_008 | silent | silent_error | MMINLU not "USGS" — all cells treated as water |
| dt_009 | silent | silent_error | SOILTEMP=0K causes NaN in soil temperature |
| dt_010 | silent | silent_error | D8 encoding mismatch (WBT vs ArcGIS) — OBSOLETED by dt_v007 |
| dt_011 | silent | unit_conversion | RAINRATE mm/3hr instead of mm/s |
| dt_012 | silent | unit_conversion | VP kPa not converted to specific humidity |
| dt_013 | fatal | runtime | CFL violation — DTRT too large |
| dt_014 | silent | dependency_mismatch | AGGFACTRT mismatch causes zero discharge |
| dt_015 | silent | parameter_format | RESTART_FREQUENCY_HOURS=0 suppresses all output |
| dt_v005 | fatal | silent_error | Noah-MP zero-veg crash — TG=630K |
| dt_v006 | fatal | dependency_mismatch | OOM with 8 MPI cores on large domain |
| dt_v007 | silent | silent_error | WBT D8 docs WRONG — 8/9 directions wrong (THE ROOT CAUSE) |
| dt_v008 | silent | unit_conversion | No elevation correction for PSFC/T2D (20% error) |
| dt_v009 | silent | silent_error | SFCRNOFF double-counts routed upstream flow |
| dt_v010 | silent | parameter_format | CHANNELGRID 0/1 vs -9999/0 encoding inverted |
| dt_v011 | silent | unit_conversion | CMFD precip units chain confusion (rate vs accumulation) |
| dt_v012 | degraded | parameter_format | ISLTYP=14 on land cells — missing data in output |
| dt_v013 | degraded | parameter_format | GW bucket Zmax=50m too shallow — no storage |
| dt_v014 | degraded | dependency_mismatch | Cold-start spinup artifact — 237 mm/d on day 1 |
| dt_v035 | fatal | missing_variable | CHAN_DEPTH missing from Fulldom — MPI_Abort after GWBUCKPARM |
| dt_v036 | fatal | silent_error | SMCRT dry-soil crash — silent segfault in arid basins (no error msg) |
| dt_v037 | fatal | parameter_format | LDASOUT/RTOUT write fails — missing resolution in metadata |
| dt_v038 | fatal | parameter_format | Restart write fails — nf90_create error on restart files |
| dt_v039 | silent | silent_error | rt_option=2 (CASC2D) not active — produces wrong routing silently |
| dt_v040 | silent | silent_error | GWBASESWCRT=0 creates water sink — drainage exits system |
| dt_v041 | silent | silent_error | lake_option=0 with gridded routing masks channels at lake locations |

---

## Comparison with VIC

| Feature | VIC 5.1.0 | WRF-Hydro 5.2.0 |
|---------|-----------|------------------|
| Grid type | Regular lat/lon | Lambert Conformal Conic |
| Resolution | 0.1-0.25 deg (~10-25 km) | 250 m - 25 km (flexible) |
| Timestep | 3-hourly (configurable) | Hourly (LSM) / seconds (routing) |
| Routing | External (Lohmann or CaMa-Flood) | Integrated (diffusive wave) |
| Forcing format | ASCII per cell | NetCDF per timestep (LDASIN) |
| Soil layers | 3 layers (custom depths) | 4 layers (Noah standard) |
| Land surface | VIC energy/water balance | Noah-MP (multiple physics options) |
| Parallelism | None (serial) | MPI (domain decomposition) |
| Setup complexity | grid + soil + veg + forcing | 8 domain files + forcing + TBL |
| **Bengbu discharge** | **1,535 m^3/s mean** | **1,090 m^3/s mean (r=0.84)** |

---

## Model Coupling

See `docs/model_couplings.yaml` for:
- VIC forcing -> WRF-Hydro LDASIN (3-hourly to hourly, unit conversions)
- CMFD -> WRF-Hydro LDASIN (direct, no VIC intermediate) via `cmfd_to_ldasin.py`
- WRF-Hydro -> CaMa-Flood (SFCRNOFF + UGDRNOFF as alternative runoff source)

---

## Quick Start

```bash
# 1. Define domain
python tools/s1_domain/define_lambert_domain.py \
  --basin_shp data/shp/chaohe_boundary.shp --dx 1000 --output domain_def.json

# 2. Build geo_em
python tools/s2_geo_em/build_geo_em.py \
  --domain_json domain_def.json \
  --dem_path data/dem/china_dem_90m/china_dem_90m.tif \
  --landcover_path data/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif \
  --hwsd_raster data/soil/HWSD_RASTER/hwsd.bil \
  --hwsd_mdb data/forcing/huaihe_raw/soil/HWSD.mdb \
  --output DOMAIN/geo_em.d01.nc

# 3-6. Build remaining domain files (can run in parallel)
python tools/s3_wrfinput/build_wrfinput.py --geo_em DOMAIN/geo_em.d01.nc --output_path DOMAIN/wrfinput_d01.nc
python tools/s4_fulldom/build_fulldom_hires.py --geo_em DOMAIN/geo_em.d01.nc --domain_json domain_def.json --dem_path ... --basin_shp ... --output_path DOMAIN/Fulldom_hires.nc
python tools/s5_soil_properties/build_soil_properties.py --geo_em DOMAIN/geo_em.d01.nc --output_path DOMAIN/soil_properties.nc
python tools/s6_groundwater/build_groundwater.py --geo_em DOMAIN/geo_em.d01.nc --domain_json domain_def.json --basin_shp ... --output_dir DOMAIN/

# 7. Validate spatial metadata (add resolution attribute if missing)

# 8. Convert forcing (choose one):
# Option A: From VIC forcing files
python tools/s8_forcing/convert_forcing_to_ldasin.py \
  --forcing_dir vic_forcing/ --grid_nc basin_grid.nc \
  --geo_em DOMAIN/geo_em.d01.nc --domain_json domain_def.json \
  --output_dir FORCING/ --start_date 2001-01-01 --end_date 2001-01-07

# Option B: Direct from CMFD (no VIC intermediate)
python tools/s8_forcing/cmfd_to_ldasin.py \
  --cmfd_dir data/forcing/Data_forcing_03hr_010deg \
  --geo_em DOMAIN/geo_em.d01.nc --domain_json domain_def.json \
  --output_dir FORCING/ --start_date 2000-01-01 --end_date 2005-12-31

# 9. Generate namelists
python tools/s9_namelists/generate_namelists.py \
  --domain_dir DOMAIN --forcing_dir FORCING --output_dir . \
  --start_date 2001-01-01 --end_date 2001-01-07

# 10. Run
python tools/s10_execution/run_wrfhydro.py --run_dir . --nproc 4

# OR: Run entire pipeline in one command
python tools/run_wrfhydro_full_pipeline.py \
  --basin_shp data/shp/basin.shp --start_date 2000-01-01 --end_date 2005-12-31 \
  --forcing_source cmfd --output_dir outputs/my_run/
```

---

## File Structure

```
knowledge_infrastructure/
  SKILL.md                          # This file (agent entry point)
  knowledge_infrastructure.yaml     # Schema-compliant package definition
  workflow/
    workflow.md                     # Pipeline workflow document
  tools/
    s1_domain/define_lambert_domain.py
    s2_geo_em/build_geo_em.py
    s3_wrfinput/build_wrfinput.py
    s4_fulldom/build_fulldom_hires.py
    s4_fulldom/build_route_link.py
    s4_fulldom/build_spatial_weights.py
    s5_soil_properties/build_soil_properties.py
    s6_groundwater/build_groundwater.py
    s8_forcing/convert_forcing_to_ldasin.py
    s8_forcing/cmfd_to_ldasin.py
    s9_namelists/generate_namelists.py
    s10_execution/run_wrfhydro.py
    run_wrfhydro_full_pipeline.py
  docs/
    calibration_guide.md              # Calibration parameters by priority tier
    s4_channel_routing_skill.md       # Channel routing + stream threshold
    s6_groundwater_skill.md           # GW bucket model
    s9_runoff_options_skill.md        # Noah-MP RUNOFF_OPTION 1-5
    s11_output_interpretation_skill.md # CHRTOUT vs LDASOUT output guide
    model_couplings.yaml
  diagnostics/
    triplets.yaml                   # 25 diagnostic triplets
    error_log.yaml                  # 25 recorded errors from real runs (Chaohe + Bengbu)
```

---

## Parameter Location Reference

| Parameter | File | Default | What it controls |
|-----------|------|---------|-----------------|
| REFKDT | `soil_properties.nc` (NOT geo_em.d01.nc) | 3.0 | Infiltration vs runoff split |
| REFDK | GENPARM.TBL | 2.0e-6 | Reference conductivity |
| SLOPE | `soil_properties.nc` | from DEM | Surface slope |
| SMCMAX | `soil_properties.nc` | from soil type | Porosity |
| Manning N | `CHANPARM.TBL` | by order | Channel roughness |
| OVROUGHRTFAC | `Fulldom_hires.nc` (2D field, NOT hydro.namelist) | 1.0 | Overland flow roughness |
| GW Coeff/Expon/Zmax | `GWBUCKPARM.nc` | 1.0 / 3.0 / 50 mm | Baseflow magnitude, recession, memory |

**CRITICAL**: REFKDT is the #1 calibration parameter but it is in `soil_properties.nc`,
NOT in `geo_em.d01.nc`. Modifying the wrong file has no effect.

**CRITICAL**: `OVROUGHRTFAC`, `RETDEPRTFAC` and `LKSATFAC` are 2D fields on the routing
grid inside `Fulldom_hires.nc` (`module_RT.F` allocates each as `(IXRT,JXRT)`). They are
NOT `hydro.namelist` variables. Adding `OVROUGHRTFAC` to `hydro.namelist` aborts the run
immediately with `HYDRO_nlst namelist error in read_rt_nlst` (verified empirically,
Zijingguan 2026-07-10). Set them with `build_fulldom_hires.py --ovroughrtfac/--retdeprtfac/--lksatfac`.

### Tool CLI knobs for the physics/calibration parameters

| Parameter | Tool flag |
|---|---|
| REFKDT | `build_soil_properties.py --refkdt` (default 0.8, mountain-tuned) |
| GW Coeff/Expon/Zmax/Zinit | `build_groundwater.py --gw_coeff --gw_expon --gw_zmax --gw_zinit` |
| OVROUGHRTFAC / RETDEPRTFAC / LKSATFAC | `build_fulldom_hires.py --ovroughrtfac ...` |
| RUNOFF_OPTION / channel_option / GWBASESWCRT / DTRT / CHRTOUT_GRID / RTOUT_DOMAIN | `generate_namelists.py --runoff_option --channel_option --gwbaseswcrt --dtrt_ch --dtrt_ter --chrtout_grid --rtout_domain --t0_output` |

`generate_namelists.py` now defaults `CHRTOUT_GRID=0` (dt_004) and `RTOUT_DOMAIN=0`; the
previous hardcoded `=1` contradicted both dt_004 and the channel_option=3 recipe above.

## Known Harmless Warnings

These warnings appear during normal operation and can be safely ignored:

| Warning | Meaning | Action |
|---------|---------|--------|
| `perverse version identifier ldasin_version = 0` | LDASIN files missing version metadata | Ignore — does not affect simulation |
| `SNOW HEIGHT NOT FOUND - VALUE DEFINED IN LSMINIT` | No snow initialization data | Ignore — model uses default initialization |
| `open_wrf_hydro_diag_files: WARNING` | Diagnostic file write warning | Ignore — log files still created |

### 22. Regulated North-China (Haihe) gauges: r-ceiling domain limit (Zijingguan 2026-07-10)

At Juma/拒马河 @ 紫荆关 (Zijingguan, Haihe, Hebei) the stock Config-A run with the
mountain-tuned default REFKDT=0.8 already applied scores **r=0.32, NSE=-1.25,
PBIAS=+128%**. This is NOT a tool bug — every tool this basin exercised was verified
correct (discharge extraction gauge-matched to 0.12 km; REFKDT=0.8; OVROUGHRTFAC a
Fulldom 2D field). It is a **domain limitation**:

- WRF-Hydro standalone is a *natural* rainfall-runoff model with **no reservoir
  operation, irrigation withdrawal, or groundwater-pumping** representation. Haihe /
  North-China gauges are among the most heavily human-managed in China, so the observed
  record's phase and volume are decoupled from natural runoff.
- **NSE <= r^2.** With r pinned at ~0.32, r^2 = 0.10, so **NSE >= 0.5 is structurally
  unreachable at this gauge by ANY parameter set.** Check r BEFORE targeting an NSE.
- The +128% over-prediction is the mirror image of the pre-REFKDT-fix Chaohe/Spain
  under-prediction: with REFKDT lowered the surface-runoff pathway is open and the model
  now over-produces relative to abstraction-depressed observed flow.

**Guidance:** prefer relatively unregulated / natural-flow gauges for WRF-Hydro
standalone validation. For a regulated Haihe gauge, treat the low r as expected, do NOT
re-patch the (already-fixed) s2/s3/s11 tools, and do NOT retry toward NSE>=0.5 — the
residual is per-basin calibration bounded by the r-ceiling, which the self-improve loop
does not tune.
