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

---

# WRF-Hydro v5.2.0 Standalone (NoahMP) — Knowledge Infrastructure

**Package**: `hydrocraft-wrfhydro-standalone` v2.2.0
**Model**: WRF-Hydro v5.2.0 offline (NoahMP land surface + gridded routing)
**Created by**: Jianyun Zhang Research Group, Hohai University
**Last updated**: 2026-03-21 (4 routing skill documents added)
**Stats**: 12 tools | 6 skill documents | 35 diagnostic triplets | 28 error log entries | ~5,200 lines of validated Python

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
| 4 | Fulldom routing grid | `build_fulldom_hires.py` (492 lines) | High-res DEM, D8 flow, channels |
| 5 | Soil properties | `build_soil_properties.py` (302 lines) | SOILPARM + MPTABLE lookup |
| 6 | Groundwater/ancillary | `build_groundwater.py` (416 lines) | GWBASINS, GWBUCKPARM, hydro2dtbl, metadata |
| 7 | Spatial metadata | (validation only) | Verify x/y resolution attributes |
| 8 | Forcing (direct CMFD) | `cmfd_to_ldasin.py` (790 lines) | CMFD -> hourly LDASIN directly (no VIC intermediate) |
| 9 | Namelist generation | `generate_namelists.py` (384 lines) | namelist.hrldas + hydro.namelist |
| 10 | Execution | `run_wrfhydro.py` (291 lines) | MPI run + output collection |
| 11 | Output processing | (manual/future tool) | Discharge extraction from CHRTOUT |
| -- | Full pipeline | `run_wrfhydro_full_pipeline.py` (438 lines) | End-to-end wrapper (stages 1-10) |

**Total**: 11 tools, ~5,173 lines of validated Python code.

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
| `build_fulldom_hires` | s4 | `tools/s4_fulldom/build_fulldom_hires.py` | 492 | Build routing domain with WhiteboxTools D8 + Strahler |
| `build_soil_properties` | s5 | `tools/s5_soil_properties/build_soil_properties.py` | 302 | Soil/veg params from SOILPARM.TBL + MPTABLE.TBL |
| `build_groundwater` | s6 | `tools/s6_groundwater/build_groundwater.py` | 416 | GWBASINS, GWBUCKPARM, hydro2dtbl, spatial metadata |
| `cmfd_to_ldasin` | s8 | `tools/s8_forcing/cmfd_to_ldasin.py` | 790 | CMFD 3hr NetCDF -> hourly LDASIN directly (no VIC) |
| `generate_namelists` | s9 | `tools/s9_namelists/generate_namelists.py` | 384 | Generate namelist.hrldas + hydro.namelist |
| `run_wrfhydro` | s10 | `tools/s10_execution/run_wrfhydro.py` | 291 | MPI execution wrapper with preflight + JSON summary |
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

---

## Diagnostic Triplets

35 triplets covering 8 failure domains + 6 Chaohe investigation errors + 3 audit additions (dt_v022-v024). 28 error log entries (all promoted). See `diagnostics/triplets.yaml` and `diagnostics/error_log.yaml` for full details.

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

# 8. Build forcing straight from the source (CMFD here; nasa_power_to_ldasin.py outside China)
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
    s5_soil_properties/build_soil_properties.py
    s6_groundwater/build_groundwater.py
    s8_forcing/nasa_power_to_ldasin.py
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
