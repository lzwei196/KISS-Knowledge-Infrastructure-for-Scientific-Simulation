---
name: mhm-hydrocraft
description: >-
  mHM (mesoscale Hydrologic Model) v5.13 lineage with Multiscale Parameter Regionalization
  (MPR); Samaniego, Kumar & Attinger 2010 WRR methodology. Covers Distributed mesoscale
  catchment water balance across a basin; Canopy interception; Snow accumulation and melt
  (degree-day); Multi-horizon soil moisture dynamics; Infiltration and direct
  (sealed/saturation-excess) runoff. Use when the task involves running, configuring,
  calibrating or interpreting mHM.
version: 1.0.0
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
Then convert to mHM NetCDF format using this KI's tool: `tools/s4_forcing/convert_forcing_to_mhm.py`

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.




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

**CRITICAL CONSTRAINT — L0 MUST BE SQUARE** (dt_r12). Make `ncols_L0 == nrows_L0`,
with the side an exact multiple of the L1/L11 ratio. `setup_mhm_domain.py` now
enforces this by padding with nodata cells.

*Why:* mHM's `read_header_ascii()` declares `(header_ncols, header_nrows, …)` but
every call site passes `(nrows, ncols, …)` positionally, e.g.
`mo_meteo_handler.f90: call read_header_ascii(fName, unit, nrows2, ncols2, …)`.
The ASCII `ncols` line therefore lands in mHM's `nrows`, and
`calculate_grid_properties()` then derives `xllcornerOut` from `ncolsIn` — mixing
the x-origin with the y-extent. For a **non-square** L0 no geographically correct
header can satisfy the L2 check: at Wangjiaba (239 × 213 @ 0.01°) mHM demanded
`xll=113.12, yll=31.35` while the true origin is `(113.24, 31.46)`, and aborted with
`L2_variable_init: size mismatch in grid file for level2`. mHM's own test domains
are square (240 × 240), so upstream never trips over it. With a square L0 of side
`N` and ratio `R`, `xllOut = xll0 + N·cs0 − (N/R)·cs1 = xll0` under either reading.

**Coordinate system flag** (`iFlag_cordinate_sys` in `mhm.nml`):
- `0` = regular X-Y (projected/metric coordinates, cellsize in METERS)
- `1` = regular lat-lon (geographic coordinates, cellsize in DEGREES)

**CRITICAL**: For all HydroCraft basins using EPSG:4326 (lat/lon), **set `iFlag_cordinate_sys = 1`**. Using `0` with geographic coordinates causes cell areas to be computed as `cellsize^2` in m^2 (e.g., 0.25*0.25 = 0.0625 m^2 instead of ~680 km^2), producing ZERO routed discharge.

**Resolution units must match the coordinate system**: When `iFlag_cordinate_sys = 1`, `resolution_Hydrology` and `resolution_Routing` must be in DEGREES (e.g., 0.25), NOT in meters.

---

## Step 0 — Verify the basin BEFORE anything else (dt_s09)

**Cross-check the shapefile's area against the gauge's published drainage area.**
A truncated domain is unfixable downstream: if the grid contains half the
contributing area, simulated discharge is ~half of observed and *no* parameter set
can recover it. You will see good timing (`r > 0.8`) with a stubborn
`PBIAS ≈ −50%`, and you will waste the whole calibration chasing it.

Measured at Wangjiaba (2026-07-09):

| Source | Area | vs documented 30,630 km² |
|--------|------|--------------------------|
| `data/shp/wangjiaba_shp` (3 nested polygons, largest) | 15,952 km² | **−48%** |
| whitebox D8 on `china_dem_90m` at the gauge | 15,782 km² | −48% |
| **MERIT-Hydro `upa` at the snapped outlet** | **30,844 km²** | **+0.7%** |
| MERIT-Hydro reverse-traced catchment | 29,638 km² | −3.2% |

Bare-earth D8 *reproduces the shapefile's error* rather than exposing it: on the
flat, leveed Huai plain the China 90 m DEM routes the Hong River (洪河, ~12,000 km²)
to a confluence just **downstream** of Wangjiaba. Two wrong methods agreeing is not
corroboration. MERIT-Hydro's flow direction is hydrologically corrected against
observed river networks and ships `upa` (upstream area, km²), so the outlet can be
snapped to the *documented* area instead of guessed:

```bash
python tools/s1_domain/delineate_basin_merit.py \
    --outlet_lon 115.617 --outlet_lat 32.433 --target_area_km2 30630 \
    --bbox 112.5 31.0 116.2 34.4 --snap_deg 0.06 \
    --out_shp runs/basin/wangjiaba_merit.shp
```

It refuses to emit a basin more than `--max_area_error_pct` (default 10%) from the
target, and also writes the `*_dir.tif` / `*_upa.tif` clips that s2 consumes.

MERIT-Hydro's D8 encoding is exactly mHM's ArcGIS convention
(1=E, 2=SE, … 128=NE; 0 = mouth, −1 = inland depression, 255 = nodata), so
`prepare_morpho_data.py --fdir_source merit --merit_dir_tif <…>_dir.tif` upscales
it straight onto L0. **Use `merit` on any flat or engineered basin**; keep
`--fdir_source dem` only where relief genuinely controls the drainage.

---

## Pipeline Stages

```
s1_domain       delineate_basin_merit  <-- FIRST: get the TRUE catchment
    |
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
| s1 | **delineate_basin_merit** | `tools/s1_domain/delineate_basin_merit.py` | **Run FIRST.** True catchment from MERIT-Hydro D8, snapped to the gauge's documented drainage area |
| s0 | configure_mhm_basin | `tools/s0_config/configure_mhm_basin.py` | Create directory structure and initial config |
| s1 | setup_mhm_domain | `tools/s1_domain/setup_mhm_domain.py` | Compute L0/L1/L11 grids from shapefile (pads L0 to a square) |
| s1 | generate_latlon_files | `tools/s1_domain/generate_latlon_files.py` | Create lat/lon NetCDF for domain |
| s2 | prepare_morpho_data | `tools/s2_morphology/prepare_morpho_data.py` | DEM, slope, aspect, flow dir, flow acc -> ASCII grids |
| s2 | hwsd_to_mhm_soil | `tools/s2_morphology/hwsd_to_mhm_soil.py` | HWSD -> mHM soil classes + classdefinition.txt |
| s2 | glim_to_mhm_geology | `tools/s2_morphology/glim_to_mhm_geology.py` | GLiM -> mHM geology classes |
| s2 | landcover_to_mhm_luse | `tools/s2_morphology/landcover_to_mhm_luse.py` | AVHRR -> mHM land use classes |
| s2 | generate_gauge_grid | `tools/s2_morphology/generate_gauge_grid.py` | Gauge location ASCII grid |
| s2 | validate_morph_grids | `tools/s2_morphology/validate_morph_grids.py` | Check all grids have identical headers |
| s3 | generate_mhm_parameters | `tools/s3_mpr/generate_mhm_parameters.py` | Create mhm_parameter.nml with climate-zone-aware defaults |
| s4 | convert_forcing_to_mhm | `tools/s4_forcing/convert_forcing_to_mhm.py` | CMFD/MSWX -> mHM NetCDF forcing |
| s5 | prepare_mhm_gauge | `tools/s5_gauge/prepare_mhm_gauge.py` | Convert obs Q to mHM gauge format |
| s6 | generate_mhm_namelists | `tools/s6_namelist/generate_mhm_namelists.py` | Assemble all 4 .nml files |
| s7 | run_mhm | `tools/s7_execute/run_mhm.py` | Execute with progress monitoring |
| s8 | parse_mhm_output | `tools/s8_postprocess/parse_mhm_output.py` | Extract Q, ET, SM from NetCDF output |
| s8 | compare_mhm_vic | `tools/s8_postprocess/compare_mhm_vic.py` | Cross-model comparison |
| s9 | setup_mhm_calibration | `tools/s9_calibration/setup_mhm_calibration.py` | Configure/run DDS/SCE calibration, extract best MPR params |
| s10 | transfer_mpr_params | `tools/s10_regionalize/transfer_mpr_params.py` | Apply calibrated params to new basin |

---

## MPR Calibration and Regionalization Workflow (THE KEY WORKFLOW)

This is the workflow that makes mHM uniquely valuable. Without calibration, MPR
parameters are German defaults (Mosel basin) that produce mediocre results
elsewhere.

**Reference (Wangjiaba 51030, Huai, 29,638 km², CMFD 0.25°, Oudin PET,
L0 0.01° / L1 = L11 0.25°, spin-up 1980):**

| Parameters | NSE | KGE | r | PBIAS |
|-----------|-----|-----|---|-------|
| German MPR defaults, full 1981–1990 | 0.442 | 0.456 | 0.861 | **+41.2%** |
| defaults, cal 1981–1985 | 0.302 | 0.301 | 0.887 | +48.2% |

The uncalibrated defaults *over*-predict runoff in a humid subtropical basin
(they under-evaporate), the mirror image of the sign you get in dry basins. The
`+41%` bias, not the correlation, is what calibration must fix — `r = 0.86`
already shows the routing and forcing are right.

> A prior Wangjiaba run reported `NSE = −0.344, PBIAS = −94.7%`. That was **not**
> an mHM property: it was three stacked input defects — a 52%-truncated basin
> (dt_s09), an ×10800 CMFD daily precipitation factor (dt_s10), and a Hargreaves
> PET of 98 mm/day from a synthesised diurnal range (dt_s11). Fixing the inputs
> moved the *uncalibrated* model from −0.344 to +0.442 before a single parameter
> was touched.

### Step 1: Calibrate on a Gauged Basin

```bash
# 1a. Set up basin through s0-s8 as usual (data prep + forward run to verify setup)
# 1b. Configure calibration (generates mhm.nml with optimize=.TRUE.)
python tools/s9_calibration/setup_mhm_calibration.py \
    --run_dir /path/to/gauged_basin \
    --opti_method 1 \
    --opti_function 10 \
    --n_iterations 1000 \
    --basin_type humid_subtropical

# 1c. Run calibration (this executes the mHM binary with optimization enabled)
python tools/s9_calibration/setup_mhm_calibration.py \
    --run_dir /path/to/gauged_basin \
    --execute

# 1d. Parse results (extracts best parameters from FinalParam.nml)
python tools/s9_calibration/setup_mhm_calibration.py \
    --run_dir /path/to/gauged_basin \
    --parse_results
```

**Optimizer options**:
- `opti_method=1` (DDS, recommended): Fast convergence, 1000 iterations usually sufficient
- `opti_method=3` (SCE): More robust but slower, good for complex parameter spaces

**`opti_function` — verified against the v5.13.1 source. DO NOT GUESS.**
`src/mRM/mo_mrm_objective_function_runoff.F90` (discharge-only) and
`src/mHM/mo_objective_function.F90` (multi-variable):

| Code | Objective (minimised) | Needs `&optional_data`? |
|------|----------------------|--------------------------|
| **1** | `1 - NSE(Q)` — use when NSE is the reported metric | no |
| 2 | `1 - lnNSE(Q)` (low flows) | no |
| 3 | `1 - 0.5*(NSE+lnNSE)(Q)` | no |
| **9** | `1 - KGE(Q)` — the real KGE-of-discharge objective | no |
| 14 | multi-gauge KGE, power-6 norm | no |
| 10–13 | KGE / PD / SSE / corr of **soil moisture** | **YES** |
| 15 | `KGE(Q) * RMSE(TWS)` | **YES** |
| 17 | KGE of **neutrons** | **YES** |
| 27, 29, 30 | objectives involving **ET** | **YES** |

> **TRAP (dt_r15).** `opti_function=10` is **NOT** KGE of discharge — it is
> `1 - KGE of catchment-average SOIL MOISTURE`. Earlier revisions of this file
> recommended it; following that advice aborts the run with
> `POSITION_NML: namelist /optional_data/ MISSING`. For discharge calibration use
> **1** (1−NSE) or **9** (1−KGE).

> **TRAP (dt_r14).** `nIterations` must be **≥ 6**. FORCES `mo_dds.F90:169` does
> `stop 'Error DDS: max function evals must be minimum 6'`, and a Fortran
> `stop '<msg>'` exits with **status 0** — so mHM looks like a clean success while
> writing no `FinalParam.nml`. Never trust the exit code alone; assert that
> `FinalParam.nml` exists.

> **TRAP (dt_r16).** `setup_mhm_calibration.py` used to rewrite `mhm.nml` on
> *every* invocation. Because the documented recipe calls it three times
> (configure → `--execute` → `--parse_results`) and the last two carry no
> optimizer flags, the `--execute` call silently stamped the argparse **defaults**
> back into `mhm.nml`. Always `grep opti_function nIterations mhm.nml` immediately
> before launching.

**Calibration / validation split.** `eval_Per` is the window the optimizer sees.
Set it to the CALIBRATION years only, and give the spin-up as `warming_Days`
(mHM warms up on the days immediately *before* `eval_Per`, so the forcing must
start earlier). Then re-run forward over cal+val with `--param_nml FinalParam.nml`
and score the two periods separately:

```bash
# calibrate on 1981-1985 only, 1980 as spin-up
python tools/s6_namelist/generate_mhm_namelists.py --config ... --domain_info ... \
    --warmup_days 365 --eval_start_year 1981 --eval_end_year 1985 \
    --optimize --opti_method 1 --opti_function 1 --n_iterations 2000
# forward run over 1981-1990 with the calibrated parameters
python tools/s6_namelist/generate_mhm_namelists.py --config ... --domain_info ... \
    --warmup_days 365 --eval_start_year 1981 --eval_end_year 1990 \
    --param_nml <cal_dir>/FinalParam.nml
```

**Basin type presets** adjust parameter bounds for the optimizer:
- `humid_subtropical`: wider infiltration/interflow, narrower snow
- `semi_arid`: high infiltration shape, narrow interflow, low recharge
- `cold_alpine`: wide snow parameters, moderate infiltration
- `tropical`: no snow, high interflow, intense rainfall infiltration

### Step 2: Transfer to Ungauged Basin

```bash
# 2a. Set up ungauged basin through s0-s7 (same L0 data sources!)
# 2b. Transfer calibrated MPR parameters
python tools/s10_regionalize/transfer_mpr_params.py \
    --calibrated_nml /path/to/gauged_basin/mhm_parameter_calibrated.nml \
    --target_dir /path/to/ungauged_basin \
    --source_basin "Bengbu" \
    --target_basin "Wangjiaba"

# 2c. Run forward simulation with transferred parameters
python tools/s7_execute/run_mhm.py --run_dir /path/to/ungauged_basin
```

**CRITICAL REQUIREMENT**: Both calibration and target basins MUST use the SAME L0
data sources (HWSD for soil, GLiM for geology, AVHRR for land cover). The MPR
transfer functions map physical properties to model parameters -- if the property
definitions change, the transfer functions become invalid.

### Why This Works (MPR Theory)

Traditional models calibrate per-cell parameters (e.g., Ksat at each grid cell).
These cannot be transferred because they encode both process AND location information.

MPR expresses parameters as **transfer functions** of measurable properties:
```
Ksat(cell) = f(sand%, clay%, bulk_density; gamma_1, gamma_2, gamma_3)
```

The `gamma` values are the **global parameters** (~70 total). They encode PROCESS
understanding ("how does sand content relate to hydraulic conductivity?") rather
than location-specific values. When you apply the same gammas to a new basin with
different soil/geology/land cover, the transfer functions automatically produce
locally appropriate Ksat values.

### Climate-Zone-Aware Parameter Initialization

The `generate_mhm_parameters.py` tool (s3) now supports `--climate_zone` with
four presets: `humid_subtropical`, `semi_arid`, `cold_alpine`, `tropical`.
These provide literature-informed starting values that are closer to optimal
for each climate, reducing calibration time and improving convergence.

```bash
python tools/s3_mpr/generate_mhm_parameters.py \
    --config config.json \
    --climate_zone humid_subtropical
```

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

> **TRAP (dt_s12).** The shipped land-cover raster is
> `data/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif` and it uses the **UMD**
> 14-class legend, **not IGBP** (its `.vat.dbf` global counts confirm it:
> value 11 = 11.8M cells = cropland; value 12 = 87M = bare). Under IGBP,
> 11 = Permanent Wetlands — so an IGBP lookup relabels all Huai cropland as wetland
> and replaces the seasonal crop LAI curve (0.0–5.2) with a flat 2–5 year-round.
> Use `--legend umd`. A **uniform** land-cover grid is never a valid result: it
> silently disables every land-cover-dependent MPR transfer function.

### Observed Discharge (Gauge) Format
Five header lines, then **six** columns — verified against
`mhm_src/test_domain/input/gauge/00398.txt`:

```
00398:GAUGE 1 (Abfluss)     DAILY
nodata  -9999
n       1       measurements per day [1, 1440]
start  1990  01  01  00  00   (YYYY MM DD HH MM)
end    1993  12  31  00  00   (YYYY MM DD HH MM)
1990  01  01  00  00    157.000
```

> **TRAP (dt_s13).** `mo_read_timeseries.f90` skips five header lines and parses
> `YYYY MM DD HH MM Q`. A bare 4-column `YYYY MM DD Q` file makes mHM eat the first
> data rows as the header and then read discharge out of the **DAY** column.

### Meteorological Forcing Format

Verified against `mhm_src/test_domain_2/input/meteo/`:

```
input/meteo/pre/pre.nc     + header.txt
input/meteo/tavg/tavg.nc   + header.txt
input/meteo/pet/pet.nc     + header.txt      # processCase(5) = 0
```

- **ONE concatenated file per variable** spanning the whole period — *not* one
  file per year. mHM opens `<dir>/<varname>.nc`.
- The NetCDF **variable name equals the directory name** (`pre`, `tavg`, `pet`).
- Dimensions `(time, yc, xc)`; georeferencing comes from `header.txt`.
- Write the **L2 (forcing) grid identical to the L1 grid** — same `xllcorner`,
  `yllcorner`, `cellsize` and shape. This is what `test_domain_2` does and it
  removes all L0→L2 `cellFactor` ambiguity.
- `lat` DESCENDING (N→S); `_FillValue = -9999.0`, never NaN; `time` as **int32**.

### Unit Conversion Table (Silent Error Prevention)

**Always load through `ki_tools_common.load_forcing.load_daily_forcing`** — it is
the one validated place where source units are normalised (`precip_mm` → mm/day,
`temp_mean_c` → °C). Do not hand-roll the arithmetic in the s4 tool.

| Variable | CMFD **3-hourly** | CMFD **daily** | MSWX | mHM | Note |
|----------|------------------|----------------|------|-----|------|
| Precipitation | kg m⁻² s⁻¹ | **kg m⁻² s⁻¹** (daily mean rate) | mm/3hr | mm/day | ×10800 per 3-h step, but **×86400** for the daily product |
| Temperature | K | K | degC | degC | CMFD: −273.15 |
| Wind speed | m/s | m/s | m/s | m/s | Penman-Monteith only |
| Radiation (SW) | W/m² | W/m² | W/m² | W/m² | Penman-Monteith only |

> **TRAP (dt_s10).** The `Data_forcing_01dy_*` (daily) CMFD product stores a daily
> **mean rate**, not a 3-hourly accumulation. Applying the 3-hourly factor 10800
> delivers exactly **1/8** of the true rainfall — a silent dry bias that drives
> PBIAS to ≈ −95% and that no calibration can undo. Gate on basin-mean
> precipitation ∈ [200, 4000] mm/yr.

### PET: which `processCase(5)` can this forcing support?

| Method | `processCase(5)` | Requires |
|--------|------------------|----------|
| PET read from file | **0** | `input/meteo/pet/pet.nc` |
| Hargreaves-Samani | 1 | `tmin/` **and** `tmax/` with a real diurnal range |
| Priestley-Taylor | 2 | net radiation |
| Penman-Monteith | 3 | wind, humidity, radiation, pressure |

> **TRAP (dt_s11).** CMFD **daily** carries a single temperature field, so
> `temp_max_c == temp_min_c == temp_mean_c`. Hargreaves scales with
> `sqrt(Tmax − Tmin)` and is therefore **identically zero**. Synthesising a fake
> diurnal range (`tavg ± 5 K`) does not recover the missing information — it
> fabricates the quantity the method integrates, and produced a basin-mean PET of
> **98 mm/day** (~20× physical) that evaporated the whole water balance.
>
> For temperature-only daily forcing use **`--pet_method 0`**: the s4 tool
> pre-computes **Oudin (2005)** PET from `tavg` + latitude and mHM reads it
> (`processCase(5)=0`). At Wangjiaba this gives 925 mm/yr, max 6.5 mm/day.
> `convert_forcing_to_mhm.py` refuses `--pet_method 1` when the mean diurnal
> range is < 0.1 K.

---

## Skill Documents

> **Note**: Skill documents have not yet been created. The procedural guidance
> for each stage is embedded directly in SKILL.md (this file) and in each
> tool's docstring. The table below lists planned documents for future expansion.

| ID | Stage | Document (planned) | Key Content |
|----|-------|--------------------|-------------|
| sd01 | s0 | `docs/s0_config_skill.md` | Resolution selection, PET method, coordinate system |
| sd02 | s1 | `docs/s1_domain_skill.md` | L0/L1/L11 relationship, grid alignment |
| sd03 | s2 | `docs/s2_morphology_skill.md` | ASCII grid format, HWSD/GLiM/AVHRR mapping |
| sd04 | s3 | `docs/s3_mpr_skill.md` | Transfer function theory, parameter ranges, climate presets |
| sd05 | s4 | `docs/s4_forcing_skill.md` | CMFD/MSWX -> mHM conversion |
| sd06 | s5 | `docs/s5_gauge_skill.md` | Gauge format, GRDC/HYDAT integration |
| sd07 | s6 | `docs/s6_namelist_skill.md` | Namelist reference, process selection |
| sd08 | s7 | `docs/s7_execute_skill.md` | Runtime expectations, error interpretation |
| sd09 | s8 | `docs/s8_postprocess_skill.md` | Output structure, performance metrics |
| sd10 | s9 | `docs/s9_calibration_skill.md` | Calibration setup, optimizer selection, convergence |
| sd11 | s10 | `docs/s10_regionalize_skill.md` | Transfer protocol, data consistency |

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

**mHM hangs after `Initialize domains ...` at ~100% CPU with no error** (dt_r13):
there is a **cycle** in the L0 flow-direction grid; mRM's L11 tracer follows `fdir`
until it reaches an outlet and never terminates. This bites when upscaling a fine
D8 network: a river meandering across a cell boundary yields `A→B` and `B→A`.
Guard: accept a downstream neighbour only when its max upstream area is *strictly*
greater (upa increases monotonically downstream, so the coarse network becomes a
DAG), map fine→coarse with integer arithmetic (`(mr - r0)//ratio`, never a lon/lat
round-trip — the grids are offset by a fraction of a fine cell), and assert
acyclicity before writing `fdir.asc`. A cycle checker must treat `fdir == 0` as an
**outlet, not a cycle**.

**mHM exits 0 having done nothing.** Fortran `stop '<msg>'` returns status **0**.
Two places do this: DDS with `nIterations < 6` (dt_r14), and any `stop` in the
namelist readers. Never trust the return code alone — assert the expected output
file exists (`FinalParam.nml`, `daily_discharge.out`).

When mHM produces unexpected results:
0. **Check the basin area first** (dt_s09) and the forcing totals (dt_s10/dt_s11):
   basin-mean precipitation ∈ [200, 4000] mm/yr and PET ≲ 8 mm/day. A structural
   area or unit error looks exactly like a "calibration problem" and is not one.
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
