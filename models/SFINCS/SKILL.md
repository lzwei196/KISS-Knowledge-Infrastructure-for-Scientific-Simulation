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
SFINCS forcing tools are in `tools/s4_forcing/` in this KI:
- `tools/s4_forcing/prepare_sfincs_rainfall.py` — Converts CMFD/MSWX precipitation to SFINCS NetCDF rainfall (mm/3hr → mm/hr)
- `tools/s4_forcing/cama_to_sfincs_boundary.py` — Converts CaMa-Flood output to SFINCS boundary conditions (water level or discharge)

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.

---

# SFINCS v2.x (Super-Fast INundation of CoastS) — Knowledge Infrastructure

**Package**: `hydrocraft-sfincs` v1.0.0
**Model**: SFINCS v2.x (Deltares)
**Created by**: Jianyun Zhang Research Group, Hohai University
**Last updated**: 2026-03-22
**Stats**: 9 tools | 8 skill documents | 28 diagnostic triplets | 12 error log entries | ~2,379 lines of validated Python
**Validation**: Step 3 — Bengbu (Huai River) flood test (2026-03-22) — 384x455 cells, 100m, 397s, 6.99m max depth, CaMa-Flood cross-validated. Previous: Chaohe (2026-03-21) — 174x171 cells, 5.7s, 7.29m max depth.

---

## Overview

This knowledge infrastructure enables fully autonomous 2D flood inundation simulation using SFINCS on any domain worldwide, integrated with HydroCraft's VIC + CaMa-Flood pipeline. The 8 validated tools handle domain setup, DEM processing, forcing conversion, configuration, execution, and post-processing.

**What SFINCS does**: Reduced-complexity 2D shallow water solver for rapid flood inundation modeling:
- **Coastal flooding**: Storm surge, tides, sea-level rise, wave setup
- **Fluvial flooding**: River overflow from CaMa-Flood discharge as boundary condition
- **Pluvial flooding**: Rainfall-driven urban/rural flooding from CMFD/MSWX precipitation
- **Compound flooding**: Combined coastal + fluvial + pluvial (primary use case)
- **Subgrid**: Coarse computational grid (50-200m) with fine bathymetry resolution (5-10m)

**Key difference from CaMa-Flood**: CaMa-Flood routes water through 15-arcmin (~28km) river networks. SFINCS resolves flood depth and extent at 10-200m within a local domain. They are complementary: CaMa-Flood provides river boundary conditions for SFINCS.

**HydroMT-SFINCS**: The Python model builder (`hydromt_sfincs`, installed in venv) provides automated grid generation, DEM processing, and Manning's n from land cover. The validated tools wrap HydroMT-SFINCS calls and add HydroCraft-specific validation, unit conversion, and coupling logic.

---

## Installation

### Binary

```
SFINCS solver:    model/sfincs/bin/sfincs
Version:          v2.3.2 mt. Faber+ (compiled 2026-03-21)
Source:           github.com/Deltares/SFINCS main branch (GPL-3.0)
Build:            gfortran 13.3 + libnetcdff 4.6.0
Dependencies:     libnetcdff7, libgfortran5, libnetcdf19, libhdf5 (system packages)
Validated:        Chaohe basin flood test (174x171, 100m, 5.7s, 7.29m max depth) + 50x50 flat test
```

**To compile from source** (if binary not yet built):
```bash
cd /tmp
curl -sL -o sfincs.tar.gz https://github.com/Deltares/SFINCS/archive/refs/heads/main.tar.gz
tar xzf sfincs.tar.gz
cd SFINCS-main/source
# Install autotools if needed: sudo apt install autoconf automake libtool
bash build_gfortran_cpu.sh
cp src/sfincs /mnt/disk1/Hydrocraft_server/model/sfincs/bin/sfincs
chmod +x /mnt/disk1/Hydrocraft_server/model/sfincs/bin/sfincs
```

### Python dependencies (all in HydroCraft venv)

```
hydromt_sfincs==1.2.2, rasterio, xarray, geopandas, numpy, scipy, netCDF4, pyproj, matplotlib
```

### CLI Usage

SFINCS reads `sfincs.inp` from the current working directory. No command-line arguments.
```bash
cd /path/to/run_dir   # Must contain sfincs.inp and all referenced files
/path/to/sfincs       # Reads sfincs.inp, writes output to same directory
```

For parallel: `export OMP_NUM_THREADS=4; /path/to/sfincs`

---

## Pipeline (8 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 1 | Domain setup | `setup_sfincs_domain` | Define grid from shapefile/bbox, auto-UTM, compute resolution |
| 2 | Topography | `build_sfincs_topobathy` | Resample DEM to grid, build mask (active/outflow/inactive) |
| 3 | Roughness | `build_sfincs_roughness` | Manning's n from AVHRR land cover or uniform value |
| 4 | Forcing & BC | `prepare_sfincs_rainfall`, `cama_to_sfincs_boundary` | Precipitation (mm/hr) + river discharge/water level BC |
| 5 | Structures | (manual) | Optional: levees (sfincs.thd), weirs, drainage |
| 6 | Configuration | `generate_sfincs_inp` | Assemble sfincs.inp with CFL-stable timestep |
| 7 | Execution | `run_sfincs` | Preflight checks + run binary + output validation |
| 8 | Post-processing | `extract_sfincs_results`, `plot_sfincs_flood_map` | Flood depth/extent maps, statistics, GeoTIFF export |

### Parallelism

Stages 2, 3, 4 can run in parallel after stage 1.
Stage 5 is optional. Stage 6 depends on 2+3+4+(5).
Stage 7 depends on 6. Stage 8 depends on 7.

---

## Tools Reference

| Tool | Stage | Script Path | Lines | Purpose |
|------|-------|-------------|------:|---------|
| `setup_sfincs_domain` | s1 | `tools/s1_domain/setup_sfincs_domain.py` | 210 | Grid from shapefile/bbox, auto-UTM, CFL dt estimate |
| `build_sfincs_topobathy` | s2 | `tools/s2_topobathy/build_sfincs_topobathy.py` | 230 | DEM to sfincs.dep/msk/ind, auto-select China DEM or GLO-30 |
| `build_sfincs_roughness` | s3 | `tools/s3_roughness/build_sfincs_roughness.py` | 200 | AVHRR land cover to Manning's n map |
| `prepare_sfincs_rainfall` | s4 | `tools/s4_forcing/prepare_sfincs_rainfall.py` | 270 | CMFD/MSWX to NetCDF precip (mm/3hr -> mm/hr) |
| `cama_to_sfincs_boundary` | s4 | `tools/s4_forcing/cama_to_sfincs_boundary.py` | 290 | CaMa-Flood outflw/sfcelv to sfincs.src/.dis or .bnd/.bzs |
| `generate_sfincs_inp` | s6 | `tools/s6_config/generate_sfincs_inp.py` | 250 | sfincs.inp with auto CFL timestep |
| `run_sfincs` | s7 | `tools/s7_execution/run_sfincs.py` | 210 | Execute with preflight, log check, output validation |
| `extract_sfincs_results` | s8 | `tools/s8_postprocess/extract_sfincs_results.py` | 230 | Parse sfincs_map.nc, flood stats, GeoTIFF export |
| `plot_sfincs_flood_map` | s8 | `tools/s8_postprocess/plot_sfincs_flood_map.py` | 200 | Publication-quality flood depth map |

**Total**: 9 tools, ~2,379 lines of validated Python.

### Skill Documents

| Stage | Document | Covers |
|-------|----------|--------|
| s1 | `docs/s1_domain_skill.md` | Grid resolution vs basin area, UTM selection, buffer sizing |
| s2 | `docs/s2_topobathy_skill.md` | DEM sources, vertical datum, subgrid tables |
| s3 | `docs/s3_roughness_skill.md` | Manning's n by land cover, urban roughness |
| s4 | `docs/s4_forcing_skill.md` | Precipitation units, CaMa-Flood coupling, compound events |
| s5 | `docs/s5_structures_skill.md` | Thin dams, weirs, drainage structures |
| s6 | `docs/s6_config_skill.md` | CFL timestep, physics options, output settings |
| s7 | `docs/s7_execution_skill.md` | Runtime estimation, GPU/CPU, convergence |
| s8 | `docs/s8_postprocess_skill.md` | Flood maps, depth classes, validation |

---

## Validated Results

### Chaohe Basin Flood Test (2026-03-21)
- **Domain**: 174x171 cells at 100m resolution, downstream Chaohe basin (40.50-40.65N, 116.60-116.80E)
- **Event**: Aug 2-12, 2008 monsoon rainfall (88.7mm total from CMFD via VIC forcing)
- **DEM**: China DEM 90m, elevation range 143-1387m
- **Runtime**: 5.7 seconds (OpenMP, 4 threads)
- **Max flood depth**: 7.29m (valley bottoms)
- **Flood volume**: 37.9 million m3
- **Flooded area**: 1,887 cells with depth >0.3m
- **Physical validation**: Water accumulates along NE-SW trending valleys matching terrain structure
- **Bugs found**: 6 (err_006 through err_010 + err_004), all fixed and promoted to triplets dt_v001-dt_v006
- **Key lesson**: First real-basin run exposed 3 FATAL bugs (ind format, precip column, time offset) and 1 SILENT bug (mask=2 draining inland terrain) that the 50x50 synthetic test did not catch

### Bengbu (Huai River) Flood Test (2026-03-22) — Step 3 Validation
- **Domain**: 384x455 = 174,720 cells at 100m resolution, Huai River floodplain near Bengbu city (32.7-33.1N, 117.1-117.5E)
- **Event**: July 2003 monsoon flood (390mm total rainfall from CMFD via VIC forcing)
- **DEM**: China DEM 90m, elevation range 3.5-310.2m (river channel to hills)
- **Runtime**: 397 seconds (OpenMP, 4 threads)
- **Max flood depth**: 6.99m (river channel depressions)
- **Flood volume**: 701 million m3
- **Flooded area**: 44,933 cells with depth >0.3m; 27,107 cells >1.0m; 2,179 cells >3.0m
- **Mass balance**: rain volume 681M m3, stored volume 701M m3 (ratio 1.03 — excellent conservation)
- **CaMa-Flood comparison**: CaMa max flood depth at same location/period = 8.17m at 15-arcmin resolution, consistent with SFINCS 6.99m at 100m resolution. CaMa peak discharge = 6,790 m3/s (confirms major flood event)
- **Validation criteria**: All 5 criteria PASS — (1) non-zero flood depth, (2) max < 20m, (3) water in low areas, (4) no NaN, (5) positive flood volume
- **Bugs found**: 2 new bugs (err_011: extract tool used zsmax instead of hmax, err_012: generate_sfincs_inp used netprecipfile instead of precipfile)
- **Key insight**: The 2003 Huai River flood was one of the worst in the period — 390mm in July produced extensive floodplain inundation. SFINCS results are physically consistent with both CaMa-Flood coarse routing and historical records. This validates SFINCS with real HydroCraft data at a different basin, climate zone (humid subtropical), and terrain (lowland floodplain vs Chaohe mountainous).

---

## Critical Domain Knowledge (Non-Obvious Facts)

These rules prevent **silent failures** — the model runs without error but results are wrong.

### 1. Mask values: 1=active, NOT 3 (dt_v009)

SFINCS mask convention: `0=inactive, 1=active (computed), 2=outflow boundary, 3=water level BC`.
Interior cells MUST be `1`. Using `3` makes SFINCS expect prescribed water levels instead of computing flow — the model runs but produces zero flood depth. Always verify: `np.unique(msk)` should show mostly `1` with some `2` at edges.

### 2. Precipitation: ASCII precipfile, NOT NetCDF netprecipfile

SFINCS has two precip input modes: `precipfile` (ASCII: `time_seconds precip_mmhr`) and `netprecipfile` (NetCDF). The NetCDF mode silently fails in some SFINCS versions. Always use ASCII `precipfile`. Format:
```
0.0 2.725272
10800.0 4.773856
21600.0 4.294822
```

### 3. CMFD precipitation is kg/m²/s, NOT mm/3hr

CMFD precip NetCDF attributes say `kg m-2 s-1`. To convert to SFINCS mm/hr: **multiply by 3600** (not divide by 3). This is the #1 unit trap across all models (PREFLIGHT.md). If max precip < 0.01 mm/hr, the units are wrong.

### 4. CaMa-Flood boundary times must be ≥ 0

The `cama_to_sfincs_boundary.py` tool reads CaMa output which may span multiple years. Times in `sfincs.dis` must be seconds since `tref` (≥ 0). Filter CaMa data to the requested simulation period before writing.

### 5. generate_sfincs_inp must reference src/dis/precip files

The config generator checks if files exist before adding them to `sfincs.inp`. Files must be checked in BOTH the current working directory AND the `--output_dir`. Missing references = SFINCS ignores the forcing silently.

### 6. Date filtering for CMFD files

CMFD has hundreds of monthly files. The rainfall tool MUST filter by `YYYYMM` in filename to avoid reading all years. Without filtering: works but takes hours instead of seconds.

---

## Critical Domain Knowledge

These non-obvious facts cause **silent failures** if violated.

### 1. Precipitation is mm/hr, NOT mm/3hr or mm/day (dt_001, dt_002)

SFINCS expects precipitation rate in **mm/hr**.
- CMFD/MSWX: mm/3hr -> divide by 3
- Some climate models: kg/m2/s (= m/s) -> multiply by 3,600,000
- VIC forcing ASCII: mm/timestep (3-hourly) -> divide by 3

Off by 3x produces flood depths 3x too high. Off by 3.6 million produces zero flooding. Both are silent.

### 2. Vertical datum consistency (dt_004)

DEM elevation and water level boundary conditions MUST use the same vertical datum:
- Copernicus GLO-30 and China DEM: EGM96 geoid heights
- CaMa-Flood sfcelv: relative to geoid (consistent with DEM)
- Tidal models (FES2014): usually MSL or chart datum
- EGM96 geoid vs WGS84 ellipsoid: 20-40m difference depending on location

For fluvial-only (CaMa-Flood BC), this is usually consistent. For coastal (tidal BC), verify datum.

### 3. SFINCS reads from CWD only (dt_017)

The binary has NO command-line arguments. It reads `sfincs.inp` from the current working directory. All file paths in `sfincs.inp` are relative to CWD. Always `cd` to the run directory before executing.

### 4. Mask value 2 = outflow (dt_007)

Edge cells of the active domain MUST have mask=2 (outflow) to allow water to exit. If set to 3 (active), water accumulates at boundaries unrealistically.

### 5. CFL stability (dt_009)

dt must satisfy: `dt <= dx / sqrt(g * h_max)`
For dx=100m, h_max=10m: dt_max = 10.1 seconds. Use 0.75 * dt_max for safety.

### 6. Double-counting precipitation (dt_014)

When coupling VIC/CaMa-Flood with SFINCS, the same rainfall must NOT be applied twice. Choose:
- (a) SFINCS has its own precipitation + CaMa river discharge at boundary only
- (b) SFINCS has VIC/CaMa runoff as source, NO precipitation

### 7. outputformat must be "net" (dt_018)

Add `outputformat = net` to sfincs.inp. Without it, output may be binary, and post-processing tools expect NetCDF (`sfincs_map.nc`).

### 8. sfincs.ind binary format is the #1 trap (dt_v001)

The index file must be written as: `[n_active int32] [n_active flat 1-based indices int32]`. If written as a full 2D grid of sequential indices, the first value (1) is read as n_active=1, giving a single-cell domain. The model reads silently with no error message. **Always verify**: read the first 4 bytes as int32 and check it equals your expected active cell count.

### 9. Inland vs coastal mask strategy (dt_v005)

Mask value 2 (outflow) defaults to water level 0.0m (sea level). For inland mountainous terrain this creates a massive hydraulic gradient that drains everything instantly. **Rule**: if min_elevation > 10m, use mask=1 (closed boundary) for all cells, or provide explicit bzs water levels matching bed elevation. Only use mask=2 for domains that touch the coast.

### 10. Use ASCII precipitation, not NetCDF (dt_v004)

The `precipfile` keyword (ASCII format: time_seconds precip_mmhr) is reliable across all SFINCS versions. The `netprecipfile` keyword (NetCDF) may silently fail to load, showing "Precipitation: no" in the log without crashing. Always prefer ASCII for precipitation.

### 11. VIC forcing column order (dt_v002)

VIC forcing ASCII files have columns: TEMP(0), PREC(1), PRESSURE(2), SW(3), LW(4), VP(5), WIND(6). Column 0 is temperature, NOT precipitation. This is a common confusion because many tools assume column 0 is the primary variable.

### 12. gfortran cleanup SIGABRT is not an error (dt_v006)

SFINCS compiled with gfortran 13.3 may exit with code -6 (SIGABRT) after printing "Simulation finished". The output is valid. Check success by: (1) "Simulation finished" in sfincs.log AND (2) sfincs_map.nc exists with non-zero size. Do not re-run on exit code alone.

### 13. Use `hmax` not `zsmax` for flood depth (dt_v007)

SFINCS output contains both `hmax` (maximum water DEPTH above bed) and `zsmax` (maximum water SURFACE elevation). For flood depth mapping, always use `hmax`. Using `zsmax` gives values equal to terrain elevation + water depth (e.g., 310m instead of 7m), which is meaningless for flood analysis. The extract_sfincs_results.py tool was fixed to prioritize `hmax` over `zsmax`.

### 14. generate_sfincs_inp must use `precipfile` not `netprecipfile` (dt_v008)

The config generator must write `precipfile = sfincs.precip` (ASCII format: `time_seconds precip_mmhr`) when the precipitation file is ASCII. Writing `netprecipfile` when the file is actually ASCII causes SFINCS to silently fall back to "Precipitation: no" — the simulation runs without rainfall, producing zero flooding. This compounds with dt_v004 (NetCDF precip itself is unreliable).

---

## Coupling Points

| # | Source | Target | Variable | Tool |
|---|--------|--------|----------|------|
| c1 | CaMa-Flood | SFINCS | Discharge (m3/s) at river entry | `cama_to_sfincs_boundary` |
| c2 | CaMa-Flood | SFINCS | Water level (m) at coastal boundary | `cama_to_sfincs_boundary` |
| c3 | CMFD/MSWX | SFINCS | Precipitation (mm/hr) | `prepare_sfincs_rainfall` |
| c4 | VIC | SFINCS | Surface runoff (mm/day -> m3/s) | (direct coupling, use with caution) |

### Standard Workflow: VIC -> CaMa-Flood -> SFINCS

1. VIC produces watershed runoff at 0.1-0.25 degree
2. CaMa-Flood routes to river channels, produces daily discharge/stage
3. SFINCS simulates local flood inundation at 10-200m using CaMa discharge as boundary + local rainfall
4. No feedback needed (local flood does not significantly affect upstream hydrology)

---

## Data Requirements

| Data | Source | Status | Path |
|------|--------|--------|------|
| SFINCS binary | Compiled from source | Installed | `model/sfincs/bin/sfincs` |
| China DEM 90m | Local | Available | `data/dem/china_dem_90m/` |
| Copernicus GLO-30 | AWS (auto-download) | Available | Auto-downloaded by hydrobasin |
| CMFD forcing | Local | Available | `data/forcing/Data_forcing_03hr_010deg/` |
| MSWX forcing | Local | Available | `/mnt/disk3/msxw/` |
| CaMa-Flood output | From pipeline | Available | `model/cmf_v420_pkg/out/` |
| AVHRR land cover | Local | Available | `data/forcing/AVHRR/` |

---

## Quick Start

```bash
# Activate venv
source /mnt/disk1/Hydrocraft_server/python_env/bin/activate

# 1. Define domain (from existing basin shapefile)
python tools/s1_domain/setup_sfincs_domain.py \
  --shp_path data/shp/chaohe_shp/chaohe.shp \
  --resolution 100 \
  --output_dir outputs/sfincs_test/

# 2. Build topography (auto-selects China DEM)
python tools/s2_topobathy/build_sfincs_topobathy.py \
  --grid_info outputs/sfincs_test/grid_info.json \
  --shp_path data/shp/chaohe_shp/chaohe.shp \
  --output_dir outputs/sfincs_test/

# 3. Build roughness
python tools/s3_roughness/build_sfincs_roughness.py \
  --grid_info outputs/sfincs_test/grid_info.json \
  --uniform_n 0.04 \
  --output_dir outputs/sfincs_test/

# 4. Prepare rainfall forcing
python tools/s4_forcing/prepare_sfincs_rainfall.py \
  --forcing_dir outputs/chaohe_run/vic_temp/forcing/forcing_final \
  --grid_info outputs/sfincs_test/grid_info.json \
  --start_date 2003-07-01 --end_date 2003-09-30 \
  --source vic_ascii \
  --output_dir outputs/sfincs_test/

# 5. Generate configuration
python tools/s6_config/generate_sfincs_inp.py \
  --grid_info outputs/sfincs_test/grid_info.json \
  --start_date 20030701 --end_date 20030930 \
  --precip_file outputs/sfincs_test/sfincs.precip \
  --output_dir outputs/sfincs_test/

# 6. Run SFINCS
python tools/s7_execution/run_sfincs.py \
  --run_dir outputs/sfincs_test/

# 7. Extract and plot results
python tools/s8_postprocess/extract_sfincs_results.py \
  --map_nc outputs/sfincs_test/sfincs_map.nc \
  --grid_info outputs/sfincs_test/grid_info.json \
  --output_dir outputs/sfincs_test/results/

python tools/s8_postprocess/plot_sfincs_flood_map.py \
  --flood_depth outputs/sfincs_test/results/flood_max_depth.npy \
  --grid_info outputs/sfincs_test/grid_info.json \
  --title "Chaohe Flood Inundation July-Sep 2003" \
  --output outputs/sfincs_test/flood_map.png
```

---

## Diagnostic Triplets

26 triplets covering 8 failure domains. See `diagnostics/triplets.yaml` for full details.

### Original triplets (dt_001 to dt_020) — from dissection

| ID | Severity | Domain | Summary |
|----|----------|--------|---------|
| dt_001 | **silent** | unit_conversion | Precip mm/3hr not divided by 3 (flood 3x too deep) |
| dt_002 | **silent** | unit_conversion | Precip in m/s instead of mm/hr (no flooding) |
| dt_003 | **silent** | unit_conversion | Discharge mm/day not converted to m3/s |
| dt_004 | **silent** | unit_conversion | Vertical datum EGM96 vs MSL offset 20-40m |
| dt_005 | fatal | spatial_error | CRS mismatch: geographic deg with metric dx/dy |
| dt_006 | **silent** | spatial_error | Grid origin mismatch after reprojection |
| dt_007 | **silent** | spatial_error | Edge cells mask=3 instead of mask=2 (no outflow) |
| dt_008 | degraded | spatial_error | Subgrid ratio > 30x causes checkerboard |
| dt_009 | fatal | timestep | CFL violation: dt > dx/sqrt(g*h) -> NaN crash |
| dt_010 | degraded | timestep | Advection + low alpha -> oscillations |
| dt_011 | degraded | timestep | Grid too fine -> 100x runtime |
| dt_012 | **silent** | boundary | Bnd point on inactive mask cell -> ignored |
| dt_013 | degraded | boundary | Source point on hilltop -> artificial pond |
| dt_014 | **silent** | coupling | Double-counted precipitation (VIC + SFINCS) |
| dt_015 | **silent** | coupling | CaMa discharge sign -> reverse flow |
| dt_016 | degraded | coupling | Daily CaMa BC -> artificial 24hr ramps |
| dt_017 | fatal | io_path | Binary not run from CWD containing sfincs.inp |
| dt_018 | degraded | io_path | outputformat missing -> binary not NetCDF |
| dt_019 | **silent** | io_path | Mask all zeros -> output all zeros |
| dt_020 | fatal | parameter | Manning's n < 0.01 -> CFL instability |

### Validated triplets (dt_v001 to dt_v006) — from Chaohe basin test

| ID | Severity | Domain | Summary | Error Log |
|----|----------|--------|---------|-----------|
| dt_v001 | **fatal** | file_format | sfincs.ind binary format wrong (full 2D grid vs header+indices) | err_006 |
| dt_v002 | **fatal** | unit_conversion | VIC forcing col 0 is temp, not precip — wrong column read | err_007 |
| dt_v003 | **fatal** | temporal_alignment | Multi-year VIC forcing time offset not computed | err_008 |
| dt_v004 | degraded | file_format | NetCDF precip via netprecipfile silently fails — use ASCII | err_009 |
| dt_v005 | **silent** | boundary_condition | mask=2 drains inland terrain at 0m water level | err_010 |
| dt_v006 | degraded | runtime | gfortran SIGABRT after "Simulation finished" — output valid | err_004 |

### Validated triplets (dt_v007 to dt_v008) — from Bengbu flood test

| ID | Severity | Domain | Summary | Error Log |
|----|----------|--------|---------|-----------|
| dt_v007 | **silent** | variable_selection | extract_sfincs_results used `zsmax` (water surface elevation) instead of `hmax` (water depth) — flood depths 310m instead of 7m | err_011 |
| dt_v008 | **silent** | config_generation | generate_sfincs_inp wrote `netprecipfile` but ASCII precip needs `precipfile` — silently falls back to no precipitation | err_012 |

**Total**: 28 triplets. **Silent error count**: 13/28 (46%). **Validated from real runs**: 8/28 (29%).

---

## File Structure

```
models/SFINCS/knowledge_infrastructure/
  DISSECTION_PLAN.md              # Original dissection plan
  SKILL.md                        # This file (agent entry point)
  knowledge_infrastructure.yaml   # Schema-compliant package definition
  tools/
    s1_domain/
      setup_sfincs_domain.py      # Grid from shapefile/bbox
    s2_topobathy/
      build_sfincs_topobathy.py   # DEM to sfincs.dep/msk/ind
    s3_roughness/
      build_sfincs_roughness.py   # Manning's n from land cover
    s4_forcing/
      prepare_sfincs_rainfall.py  # CMFD/MSWX to sfincs.precip (mm/hr)
      cama_to_sfincs_boundary.py  # CaMa-Flood to sfincs.src/.dis or .bnd/.bzs
    s5_structures/
      (future: setup_sfincs_structures.py)
    s6_config/
      generate_sfincs_inp.py      # Generate sfincs.inp with CFL dt
    s7_execution/
      run_sfincs.py               # Execute with preflight checks
    s8_postprocess/
      extract_sfincs_results.py   # Parse sfincs_map.nc, flood stats
      plot_sfincs_flood_map.py    # Flood depth map visualization
  docs/
    s1_domain_skill.md ... s8_postprocess_skill.md
  diagnostics/
    triplets.yaml                 # 26 diagnostic triplets (20 from dissection + 6 from Chaohe validation)
    error_log.yaml                # 10 error log entries (6 promoted to triplets)

model/sfincs/
  bin/sfincs                      # SFINCS v2.3.2 binary (compiled from source, validated)
  bin/VERSION                     # Build metadata
  compile_sfincs.sh               # Compilation script (for rebuilding)
```
