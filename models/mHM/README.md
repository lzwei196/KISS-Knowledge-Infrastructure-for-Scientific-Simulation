---
name: mhm-hydrocraft
version: "1.0.0"
model: mHM v5.13.1
domain: distributed hydrology with parameter regionalization
validation_status: binary_only
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

---



# mHM Knowledge Infrastructure for HydroCraft

## Model Overview

**mHM (mesoscale Hydrological Model)** is a grid-based distributed hydrological model developed at the Helmholtz Centre for Environmental Research (UFZ), Leipzig. Its defining innovation is **Multiscale Parameter Regionalization (MPR)** -- a methodology that derives spatially distributed model parameters from high-resolution physiographic data through transfer functions with a small set of **global parameters** (~50-70). Because these global parameters encode process understanding (not location-specific values), they can be calibrated on gauged basins and transferred directly to ungauged basins.

**Binary**: `KISSPATH_BINARIES/mhm/mhm`
**Source**: `KISSPATH_BINARIES/mhm_src/` (v5.13.1, built from GitHub)
**Test domain**: KGE=0.75, NSE=0.77 on bundled Mosel basin test case

### What Makes mHM Unique in HydroCraft

| Capability | VIC | WRF-Hydro | **mHM** |
|-----------|-----|-----------|---------|
| Parameter regionalization | No (per-cell) | No (lookup) | **Yes (MPR)** |
| Transfer to ungauged basins | Recalibration needed | Recalibration needed | **Direct transfer** |
| Calibration parameters | 6 per cell | ~15 per cell | **~70 global** |
| Multi-basin simultaneous | No | No | **Yes (native)** |
| Built-in optimization | No | No | **Yes (DDS, SCE)** |
| Internal routing | External | Internal | **MRM (internal)** |

### Strategic Value

mHM enables a "calibrate once, apply everywhere" paradigm. Calibrate global parameters on well-gauged basins, then predict discharge for any ungauged basin using the same parameters + local physiographic data. This is transformative for data-sparse regions.

---

## Three-Grid Architecture (CRITICAL)

mHM operates on three hierarchical grids:

| Grid | Alias | Typical Resolution | Content |
|------|-------|-------------------|---------|
| **L0** | Morphological | ~100-1000 m | Raw physiographic data (DEM, soil, geology, land cover) |
| **L1** | Hydrological | ~1-25 km | Model grid where water balance is computed |
| **L11** | Routing | ~1-25 km | River routing network (MRM) |

**CRITICAL CONSTRAINT**: L1 and L11 resolutions must be integer multiples of L0 resolution. If L0=500m, then L1 must be 1000, 1500, 2000, ... etc. Violation causes `ERROR: Resolution mismatch` at startup.

**Coordinate system flag** (`iFlag_cordinate_sys` in `mhm.nml`):
- `0` = regular X-Y (projected/metric coordinates, cellsize in METERS)
- `1` = regular lat-lon (geographic coordinates, cellsize in DEGREES)

**CRITICAL**: For all HydroCraft basins using EPSG:4326 (lat/lon), **set `iFlag_cordinate_sys = 1`**. Using `0` with geographic coordinates causes cell areas to be computed as `cellsize^2` in m^2 (e.g., 0.25*0.25 = 0.0625 m^2 instead of ~680 km^2), producing ZERO routed discharge.

**Resolution units must match the coordinate system**: When `iFlag_cordinate_sys = 1`, `resolution_Hydrology` and `resolution_Routing` must be in DEGREES (e.g., 0.25), NOT in meters.

---

## Pipeline Stages

```
s0_config       Configuration & directory setup
    |
s1_domain       Domain grid setup (L0, L1, L11)
    |
s2_morphology   Morphological data (DEM, soil, geology, land cover) -> ESRI ASCII grids
    |
s3_mpr          MPR parameter file (transfer function coefficients)
    |
s4_forcing      Meteorological forcing (CMFD/MSWX -> mHM NetCDF)
    |
s5_gauge        Observed discharge preparation
    |
s6_namelist     Namelist assembly (4 .nml files)
    |
s7_execute      Model execution
    |
s8_postprocess  Output extraction & analysis
    |
s9_calibrate    Built-in DDS/SCE calibration (optional)
    |
s10_regionalize Transfer to ungauged basins (THE KEY STAGE)
```

---

## Tools Reference

| Stage | Tool | Script Path | Purpose |
|-------|------|-------------|---------|
| s0 | configure_mhm_basin | `tools/s0_config/configure_mhm_basin.py` | Create directory structure and initial config |
| s1 | setup_mhm_domain | `tools/s1_domain/setup_mhm_domain.py` | Compute L0/L1/L11 grids from shapefile |
| s1 | generate_latlon_files | `tools/s1_domain/generate_latlon_files.py` | Create lat/lon NetCDF for domain |
| s2 | prepare_morpho_data | `tools/s2_morphology/prepare_morpho_data.py` | DEM, slope, aspect, flow dir, flow acc -> ASCII grids |
| s2 | hwsd_to_mhm_soil | `tools/s2_morphology/hwsd_to_mhm_soil.py` | HWSD -> mHM soil classes + classdefinition.txt |
| s2 | glim_to_mhm_geology | `tools/s2_morphology/glim_to_mhm_geology.py` | GLiM -> mHM geology classes |
| s2 | landcover_to_mhm_luse | `tools/s2_morphology/landcover_to_mhm_luse.py` | AVHRR -> mHM land use classes |
| s2 | generate_gauge_grid | `tools/s2_morphology/generate_gauge_grid.py` | Gauge location ASCII grid |
| s2 | validate_morph_grids | `tools/s2_morphology/validate_morph_grids.py` | Check all grids have identical headers |
| s3 | generate_mhm_parameters | `tools/s3_mpr/generate_mhm_parameters.py` | Create mhm_parameter.nml with defaults |
| s4 | convert_forcing_to_mhm | `tools/s4_forcing/convert_forcing_to_mhm.py` | CMFD/MSWX -> mHM NetCDF forcing |
| s5 | prepare_mhm_gauge | `tools/s5_gauge/prepare_mhm_gauge.py` | Convert obs Q to mHM gauge format |
| s6 | generate_mhm_namelists | `tools/s6_namelist/generate_mhm_namelists.py` | Assemble all 4 .nml files |
| s7 | run_mhm | `tools/s7_execute/run_mhm.py` | Execute with progress monitoring |
| s8 | parse_mhm_output | `tools/s8_postprocess/parse_mhm_output.py` | Extract Q, ET, SM from NetCDF output |
| s8 | compare_mhm_vic | `tools/s8_postprocess/compare_mhm_vic.py` | Cross-model comparison |
| s10 | transfer_mpr_params | `tools/s10_regionalize/transfer_mpr_params.py` | Apply calibrated params to new basin |

---

## Critical Domain Knowledge

### D8 Flow Direction Convention
mHM uses the **standard ArcGIS D8** convention:
```
 32  64  128
 16   X    1
  8   4    2
```
- 1=E, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE
- 0 or -9999 = sink/outlet

This is the SAME convention used by GDAL and most GIS tools. WhiteboxTools uses a DIFFERENT convention -- must convert.

### Input Format: ESRI ASCII Grid
ALL morphological data must be in ESRI ASCII grid format (`.asc`):
```
ncols         <N>
nrows         <M>
xllcorner     <X>
yllcorner     <Y>
cellsize      <C>
NODATA_value  -9999
<data rows>
```
ALL grids for a domain MUST have identical headers (ncols, nrows, xllcorner, yllcorner, cellsize).

### Soil Class Definition Format
Tab-separated, first line: `nSoil_Types  <N>`
Header: `MU_GLOBAL  HORIZON  UD[mm]  LD[mm]  CLAY[%]  SAND[%]  BD[gcm-3]`
Data: one row per soil type per horizon

### Geology Class Definition Format
First line: `nGeo_Formations  <N>`
Header: `GeoParam(i)  ClassUnit  Karstic  Description`
Karstic: 1=karstic, 0=non-karstic

### LAI Class Definition Format
First line: `NoLAIclasses  <N>`
Header: `ID  LAND-USE  Jan.  Feb.  Mar.  ...  Dec.`
Monthly LAI values per class

### Meteorological Forcing Format
NetCDF with dimensions (time, lat, lon), daily or sub-daily:
- Precipitation: mm/day (variable name must match mhm.nml setting)
- Temperature: degrees Celsius
- PET: mm/day (if pre-computed) OR tmin/tmax for Hargreaves

### Unit Conversion Table (Silent Error Prevention)

| Variable | CMFD Unit | MSWX Unit | mHM Unit | Conversion |
|----------|-----------|-----------|----------|------------|
| Precipitation | mm/3hr | mm/3hr | mm/day | multiply by 8 (sum 8 3-hourly steps) |
| Temperature | K | degC | degC | CMFD: subtract 273.15; MSWX: none |
| Wind speed | m/s | m/s | m/s | none (only for Penman-Monteith) |
| Radiation (SW) | W/m2 | W/m2 | W/m2 | none (only for Penman-Monteith) |

---

## Skill Documents

| ID | Stage | Document | Key Content |
|----|-------|----------|-------------|
| sd01 | s0 | `docs/s0_config_skill.md` | Resolution selection, PET method, coordinate system |
| sd02 | s1 | `docs/s1_domain_skill.md` | L0/L1/L11 relationship, grid alignment |
| sd03 | s2 | `docs/s2_morphology_skill.md` | ASCII grid format, HWSD/GLiM/AVHRR mapping |
| sd04 | s3 | `docs/s3_mpr_skill.md` | Transfer function theory, parameter ranges |
| sd05 | s4 | `docs/s4_forcing_skill.md` | CMFD/MSWX -> mHM conversion |
| sd06 | s5 | `docs/s5_gauge_skill.md` | Gauge format, GRDC/HYDAT integration |
| sd07 | s6 | `docs/s6_namelist_skill.md` | Namelist reference, process selection |
| sd08 | s7 | `docs/s7_execute_skill.md` | Runtime expectations, error interpretation |
| sd09 | s8 | `docs/s8_postprocess_skill.md` | Output structure, performance metrics |
| sd10 | s10 | `docs/s10_regionalize_skill.md` | Transfer protocol, data consistency |

---

## Diagnostic Triplets

See `diagnostics/triplets.yaml` for the full set. Key categories:
- **Grid alignment** (dt_r01, dt_r02): ASCII header mismatch, resolution not integer multiple
- **Forcing format** (dt_r03, dt_r06): Wrong NetCDF variable names, wrong units
- **D8 convention** (dt_r05): Wrong flow direction encoding = zero discharge
- **Soil/geology mapping** (dt_s01, dt_r07): Classdefinition format errors, missing classes
- **Silent errors** (dt_s02-dt_s08): Wrong PET method, wrong aspect, biased calibration

---

## Error Handling

When mHM produces unexpected results:
1. Check `ConfigFile.log` — look for `Resolution [m]: 0.` or `Effective Area: 0.000` which indicate wrong `iFlag_cordinate_sys`
2. Verify ALL ASCII grids have identical headers: use `validate_morph_grids.py`
3. Check forcing NetCDF variable names match mhm.nml expectations
4. **If discharge is zero**: Check THREE things in order:
   a. `iFlag_cordinate_sys` — must be `1` for lat/lon grids (this is the #1 cause of zero discharge)
   b. Gauge-to-L11 mapping — the gauge L0 cell may map to an L11 cell with no upstream drainage; use `move_gauge.py` after an initial run to place the gauge at the max-Q L11 cell
   c. D8 flow direction convention — must be ArcGIS (1=E, 2=SE, ... 128=NE)
5. If discharge is wildly wrong: check precipitation units (mm/day, not mm/3hr)
6. If baseflow is zero: check geology class mapping (all mapped to one class?)
7. **Gauge placement after L0-to-L11 upscaling**: The highest-facc cell at L0 may NOT map to the highest-Q cell at L11 due to resolution upscaling. After the first run, read `mRM_Fluxes_States.nc` to find the L11 cell with max Qrouted, then place the gauge at the max-facc L0 cell within that L11 cell.

---

## Coupling with HydroCraft

### Input Coupling (from HydroCraft global databases)
- DEM: China DEM 90m / Copernicus GLO-30 -> `dem.asc`
- Soil: HWSD global raster + MDB -> `soil_class.asc` + `soil_classdefinition.txt`
- Geology: GLiM lithology -> `geology_class.asc` + `geology_classdefinition.txt`
- Land cover: AVHRR 1km -> `lc_YYYY.asc`
- Forcing: CMFD (China) or MSWX (global) -> NetCDF per variable

### Output Coupling (to downstream models)
- Total runoff -> CaMa-Flood (flood inundation)
- Soil moisture -> DSSAT/WOFOST (crop models)
- Actual ET -> MODIS validation
- Baseflow -> MODFLOW (groundwater recharge)
