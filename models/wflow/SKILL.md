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

> **HWSD soil lookup:** Use `from ki_tools_common.soil_utils import lookup_hwsd` to get sand/silt/clay/OC/pH for any lat/lon. Returns texture class and Saxton-Rawls hydraulic properties.
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
Then convert to wflow forcing format using this KI's tool: `tools/s2_forcing/convert_forcing_to_wflow.py`

### Soil properties

**Data Sources**: Use `from ki_tools_common.soil_utils import lookup_hwsd` for soil properties.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.

### USLE factors for sediment model (automated — replaces manual lookup)
```bash
# K-factor from HWSD soil texture (Wischmeier-Smith 1978 equation):
python tools/s6_sediment/derive_usle_k.py \
    --staticmaps [STATICMAPS_NC] --output [USLE_K_NC]
# Or patch directly into sediment staticmaps:
python tools/s6_sediment/derive_usle_k.py \
    --staticmaps [STATICMAPS_NC] --patch_nc [STATICMAPS_SEDIMENT_NC]
# Point verification:
python tools/s6_sediment/derive_usle_k.py --lat [LAT] --lon [LON]

# C-factor from AVHRR land cover classification:
python tools/s6_sediment/derive_usle_c.py \
    --staticmaps [STATICMAPS_NC] --output [USLE_C_NC]
# Or patch directly into sediment staticmaps:
python tools/s6_sediment/derive_usle_c.py \
    --staticmaps [STATICMAPS_NC] --patch_nc [STATICMAPS_SEDIMENT_NC]
# Point verification:
python tools/s6_sediment/derive_usle_c.py --lat [LAT] --lon [LON]
```

---

# wflow v1.1.0 (Deltares) — Knowledge Infrastructure

**Package**: `hydrocraft-wflow` v1.1.0
**Model**: wflow v1.1.0-dev (Wflow.jl) — wflow_sbm + wflow_sediment
**Status**: **PRODUCTION_VALIDATED** (Bengbu basin, 2026-03-22)
**Created by**: Jianyun Zhang Research Group, Hohai University
**Last updated**: 2026-04-03
**Stats**: 21 tools | 9 skill documents | 29 diagnostic triplets | ~5,681 lines of validated Python + Julia

---

## Validated Basins

### Bengbu (Huai River) — Production Validated (2026-03-22)

| Metric | Value |
|--------|-------|
| Basin | Huai River @ Bengbu (~121,330 km2) |
| Period | 2003-2005 (2003 warmup) |
| Resolution | 0.25 deg (224 cells, 16x24 grid) |
| Forcing | CMFD 3-hourly -> daily (P, T, PET Hargreaves) |
| Soil | HWSD via VIC soil params (KsatVer, theta_s, theta_r, expt) |
| DEM | china_dem_90m (resampled to 0.25 deg) |
| Routing | Kinematic wave (built-in), daily timestep |
| wflow mean Q | 1,088 m3/s (2004-2005) |
| VIC mean Q | 1,767 m3/s (raw unrouted runoff sum) |
| wflow/VIC ratio | 0.615 |
| Correlation r | 0.404 (lag=0), **0.621 (lag=-3d)** |
| Monsoon cycle | Present (Jul ~5,500 m3/s, Jan ~90 m3/s) |
| Runtime | 14 seconds (1,096 timesteps, 224 cells) |
| Output dir | `outputs/bengbu_wflow_test/` |

**Key findings**:
- The 3-day lag between wflow and VIC is expected: VIC Q is raw runoff+baseflow sum without routing, while wflow applies kinematic wave routing through the river network.
- wflow mean Q is ~38% lower than VIC raw runoff sum, partly because routing introduces storage/lag effects and the kinematic wave attenuates peaks.
- Annual precip ~1,125 mm/yr, PET ~1,009 mm/yr, wflow runoff ~283 mm/yr, VIC runoff ~459 mm/yr.

### Critical: LDD Generation (3 interacting problems — dt_w027)

The LDD (local drain direction) in `staticmaps.nc` is the #1 failure point. Three problems interact — fixing only one leaves the others:

**Problem 1: Naive D8 creates cycles.** On coarse grids (>=0.25°), flat areas produce reciprocal flows (A→B→A). Fix: use WhiteboxTools `breach_depressions` + `d8_pointer` instead of hand-coded D8.

**Problem 2: DEM masking creates artificial barriers.** Setting cells outside the basin to nodata/-9999 makes WhiteboxTools route water INTO the nodata "walls". Fix: sample the FULL DEM for ALL grid cells (including outside the basin), fill gaps with nearest-neighbor (NOT basin mean).

**Problem 3: wflow's coordinate transformation breaks boundary cells.** wflow reads `(y,x)` → transposes to Julia `(x,y)` → reverses y to ascending (via `read_standardized` in `io.jl`). Its `flowgraph()` uses `searchsortedfirst()` to find neighbors. If a cell's LDD target is outside the active domain in this TRANSFORMED space, `searchsortedfirst` returns a WRONG node — creating phantom cycles that Python cycle checks won't detect. Fix: verify boundary conditions in BOTH numpy-space AND wflow-space.

**Also:** Brooks-Corey `c` must have a `layer` dimension `(layer, y, x)`. Without it, wflow errors with "type InputEntries has no field" (dt_w031).

The `run_hydromt_build.py` tool handles all of this automatically since 2026-04-10. See `diagnostics/triplets.yaml` dt_w014, dt_w027, dt_w031 for details.

### Critical: the DOMAIN must come from the FLOW NETWORK, not a shapefile (2026-07-20)

This is the failure that silently invalidates a basin run, and it is NOT the
same bug as the cycle problem above. dt_w014's remedy says "if the LDD target
leaves the active mask, set LDD = 5 (pit)". That rule is correct *given* a mask
that agrees with the flow network — but when the mask is a rasterised shapefile
(derived from a different, finer DEM) it does NOT agree cell-for-cell, so every
misaligned edge cell becomes a pit. Xixian at 0.1° produced **20 outlets in a
128-cell basin**: 19 fabricated sub-basins draining nowhere, and discharge at the
gauge integrating only a fraction of the catchment. wflow runs happily. There is
no error. The hydrograph just has the wrong magnitude.

**Always check `n_outlets` in the s1 build output. It must be exactly 1.**
`run_hydromt_build.py` now fails loudly instead of returning a shattered domain.

The fix is to delineate the domain FROM the same coarse network the model routes
on — trace upstream from the snapped outlet — so the domain is upstream-closed by
construction and only the true outlet is a pit.

### Critical: on low-relief basins, coarse-DEM D8 is noise — use MERIT-Hydro

Deriving D8 from a nearest-neighbour-resampled DEM works on terrain with relief.
On a floodplain it does not: neighbouring 0.1° cells on the Huai plain differ by
a few metres, so the drainage pattern is essentially arbitrary. At Xixian this
snapped the outlet ~30 km from the gauge and got the area +13% wrong.

Pass `--merit_hydro_dir` to upscale MERIT-Hydro's hydrologically corrected
3-arcsec D8 (`*_dir.tif`) and upstream-area (`*_upa.tif`) grids instead. Each
coarse cell's outlet pixel is the max-`upa` basin pixel inside it; walking
downstream on the fine network to the next active coarse cell gives the coarse
direction. At Xixian this gave 97 cells / 10,171 km², **−0.2%** against the
published 10,190 km², one outlet, zero cycles.

MERIT-Hydro tiles ship as 30°×30° tars under `KISSPATH_DATA/MERIT_Hydro/v1.0.1/`.
Do NOT hand-roll `tar xf` (the member path and the s/w hemisphere tile names are
easy to get wrong, and the failure surfaces only as
`no MERIT-Hydro 'dir' tiles ... for bbox`). Stage them with the KI tool — it is
resumable and takes the bbox straight from the basin shapefile:

```bash
python tools/s1_hydromt/fetch_merit_hydro_tiles.py \
  --shapefile data/shp/<basin>.shp --pad_deg 0.4 --kinds dir,upa,elv \
  --out_dir KISSPATH_DATA/merit_hydro_cache
```

**Always pass `--kinds dir,upa,elv`.** `--kinds` defaults to `dir,upa`, which is
only what the coarse LDD upscaling needs. Without `elv`, s1 cannot walk the fine
3-arcsec main stem inside each cell and silently drops back to the coarse D8
drop for `RiverSlope` — the build reports
`"river_slope_method": "coarse_d8_fallback"` and a `river_slope_note` telling you
to stage `elv`. Read those two fields; kinematic-wave celerity on the channel
network is set by `RiverSlope`.

### Critical: the GAUGE cell must be activated BEFORE the coarse LDD (dt_w041)

In MERIT-Hydro mode a coarse cell is active when ≥ `--merit_cell_fraction`
(default 0.5) of it lies inside the traced basin. The outlet cell sits at the
downstream tip and is routinely far below that — 24 % at Rio Pelotas. Activating
it *after* the upscaled LDD is built is too late: every upstream trace has
already walked past an "inactive" gauge cell and attached to the first active
cell **downstream** of it, so nothing drains to the outlet and the reachability
prune deletes the entire basin (`Domain: 80 cells` → `Pruned 79 cell(s)` →
`Domain after prune: 1 cells`). `run_hydromt_build.py` now forces the gauge cell
active first and prints `Outlet cell (j,i) is only N% in-basin — activating it
anyway`.

### Critical: outside China the DEM default is a FLAT PLACEHOLDER (dt_w040)

`run_hydromt_build.py` used to default `dem_path` to `china_dem_90m.tif`. On any
non-China basin every sample is nodata, the gap fill has no donor, and the tool
fell through to a **flat 500 m placeholder** — `Slope` and `RiverSlope` then
collapse to the 1e-4 floor and kinematic-wave celerity is set by that floor
instead of the terrain. wflow runs; the hydrograph is simply wrong.

The DEM is now resolved per basin: `--dem_path` > config `data.dem_path` > auto
(China 90 m DEM when the whole window is inside China, otherwise the global
MERIT DEM tile directory `KISSPATH_DATA/MERIT_DEM`). `--dem_path` accepts either
a single GeoTIFF or a **directory of MERIT 5°×5° `<tile>_dem.tif` tiles**, which
are merged over the window. If the DEM covers none of the window the build now
FAILS instead of substituting a placeholder. Always read the s1 line:

```
DEM sampled from KISSPATH_DATA/MERIT_DEM: 374/391 cells valid, -0 - 1738 m
```

### Critical: dt_w040's DEM fix has been ROLLED BACK once — verify it every run

The auto-resolution of the elevation source (`_resolve_dem_path` /
`_sample_dem` in `run_hydromt_build.py`) was reverted at some point between the
2026-08-05 Rio Pelotas run and 2026-08-08, leaving the old hard default to
`china_dem_90m.tif`. On the Saar every sample came back nodata, the
nearest-neighbour gap fill had no donor, and the build carried on over a uniform
-9999 surface — `DEM sampled: -9999 - -9999 m`, `RiverSlope` median 1.67e-04
(the floor). It restores to `86 - 887 m` and 1.57e-03 once the fix is back.

**Read the `DEM sampled from ...` line every single run.** It must name a real
source and report `N/N cells valid` with a plausible elevation range. If it says
`-9999 - -9999`, or the line is missing entirely, the fix has been rolled back
again; the domain will still look perfect (MERIT-Hydro supplies it) and wflow
will still run.

### Critical: HWSD has NON-SOIL mapping units — a city or a lake is not an error

HWSD reserves mapping units for surfaces with no soil profile: **7001 UR
(urban)**, **7003 WR (water bodies)**, plus glacier / rock / salt-flat / dune /
no-data units. All of them carry `ISSOIL = 0` and **every** soil attribute,
REF_DEPTH included, is NaN by definition.

`derive_landsurface_params.py` used to read ONE HWSD pixel per cell, at the cell
centre, so a single cell centred on a city or a reservoir failed the whole build
with `mapping unit(s) [7001, 7003] carry no usable REF_DEPTH row ... fix the soil
join`. Nothing is wrong with the join — the Saar basin simply contains
Saarbrücken and open water. It now samples the cell's FULL footprint and
area-weights REF_DEPTH / texture over the SOIL units inside it, excluding the
declared non-soil ones (`hwsd_nonsoil_mapping_units_excluded` and
`hwsd_nonsoil_pixel_fraction` in the provenance record what was dropped). A cell
with **no** soil pixel at all still fails, and so does a unit that claims
`ISSOIL = 1` but carries unusable data.

### Critical: a sentinel must be outside the DATA's range, not just its legend

`derive_landsurface_params.py` pads its GLC_FCS30 mosaic with `LC_PAD_SENTINEL`
so a staging gap can be told from in-tile nodata. The tiles are **uint8 with no
declared nodata** (`nodatavals == (None,)`), so *any* value in 0-255 can appear
as raw fill: the previous sentinel 255 was "absent from the legend" and absent
from the Rio Pelotas tiles, yet 9,277 pixels of the Saar window carry it. The
sentinel is now **300** with the mosaic read as int16 — outside the product's
dtype, so it is unreachable by construction.

Separately, `rasterio.merge` leaves the destination's **last row/column
unwritten** when the requested bounds are not an exact multiple of the source
resolution. That is a rounding artifact, not a staging gap, and no sentinel
choice fixes it; the merge window is now padded by two source pixels so the
artifact lands outside the model grid.

### Critical: `run_wflow.py` must honour `dir_input` / `dir_output`

Wflow.jl resolves `input.path_static` / `input.path_forcing` relative to the
top-level `dir_input` (itself relative to the TOML's own directory), and writes
every output into `dir_output`. `run_wflow.py`'s preflight used to join
`path_static` straight onto the TOML's directory, so it refused to run any TOML
in the standard upstream layout — including **Deltares' own shipped Moselle
example**: `Static maps file not found: <toml_dir>/staticmaps-moselle.nc`. Both
the preflight and the output-file scan now resolve through `dir_input` /
`dir_output`, and the shipped example reproduces bit-exactly.

### Running a basin outside China — checklist

| Input | Non-China choice |
|---|---|
| DEM | leave `--dem_path` unset (auto → `KISSPATH_DATA/MERIT_DEM`) |
| Flow network | `fetch_merit_hydro_tiles.py` → `--merit_hydro_dir <cache>` |
| Forcing | `--forcing mswx` (s0) and `--source mswx` (s2); CMFD is China-only |
| Soil | HWSD via `lookup_hwsd` — already global |
| Obs | GRDC-Caravan; **`streamflow` is mm/day**, multiply by area to get m³/s |

MSWX annual files are gzip-chunked one global slab per timestep, so each
(variable, year) costs a full-year decompression regardless of how few cells are
wanted. `convert_forcing_to_wflow.py` therefore reads only `P` and `Tair` for
MSWX (all that Hargreaves PET needs) — ~3.5× faster than the 7-variable read.
Budget ~10–15 min per basin-year anyway, and cache the conversion per year.

### Critical: `reducer = "maximum"` is not the outlet

The CSV column used to be a domain-wide maximum of `river_water__volume_flow_rate`.
That equals outlet discharge only by accident — any larger neighbouring channel
inside the window, or a tributary flood peak, silently reports a different cell.
Pass `--outlet_lat/--outlet_lon` to `generate_wflow_toml.py` to emit a
`coordinate.x/coordinate.y` column that samples the gauge cell explicitly.

### Chaohe (Partial Test, 2026-03-21)

| Metric | Value |
|--------|-------|
| Basin | Chaohe @ Zhangjiaofen (~8,783 km2) |
| Period | 2005-2006 |
| Resolution | 0.25 deg (27 cells, 5x7 grid) |
| wflow mean Q | ~6.7 m3/s |
| Status | partial_replacement (placeholder soil params) |

---

## Overview

This knowledge infrastructure enables autonomous simulation of distributed hydrology AND sediment transport using Deltares' wflow model on any basin worldwide. wflow fills two gaps in HydroCraft: (1) **sediment/erosion modeling** (no other HydroCraft model provides spatially distributed erosion) and (2) **alternative hydrology** (modern Julia-based model with different soil physics than VIC for model intercomparison).

**What wflow does**: Distributed hydrological model with two sub-models:

- **wflow_sbm** (hydrology): Soil Budget Model with topography-driven flow. Simulates interception (Gash), snow (degree-day), infiltration (Brooks-Corey), soil water (multi-layer with exponential Ksat decay), ET (Penman-Monteith), and routing (kinematic wave or local inertial).
- **wflow_sediment** (erosion & transport): Post-processor using SBM hydrology output. Computes splash erosion (EUROSEM/ANSWERS), overland flow erosion (USLE C/K factors), in-stream transport (5 formulas: Bagnold, Engelund-Hansen, Kodatie, Yang, Molinas-Wu), and deposition (Einstein settling).

**Key difference from VIC**: wflow uses Julia (fast, multi-threaded), TOML configuration (structured), NetCDF I/O, built-in routing, and built-in sediment transport. VIC uses C, flat text config, ASCII I/O, external routing, and no sediment.

---

## Installation

### Julia + Wflow.jl

```
Julia binary:    model/julia-1.10.7/bin/julia  (to be installed)
Julia env:       models/wflow/knowledge_infrastructure/julia/
Runner script:   models/wflow/knowledge_infrastructure/julia/wflow_runner.jl
```

Install Julia:
```bash
cd KISSPATH_BINARIES
wget https://julialang-s3.julialang.org/bin/linux/x64/1.10/julia-1.10.7-linux-x86_64.tar.gz
tar xzf julia-1.10.7-linux-x86_64.tar.gz
```

Install Wflow.jl:
```bash
model/julia-1.10.7/bin/julia -e 'using Pkg; Pkg.add("Wflow")'
```

### HydroMT-wflow (Python, optional)

```bash
source python_env/bin/activate
pip install hydromt_wflow
```

### Python dependencies (all in HydroCraft venv)

```
xarray, netCDF4, numpy, pandas, geopandas, shapely, matplotlib, pyyaml
```

---

## Pipeline (10 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | `setup_wflow_config` | Basin, period, resolution, routing, sediment |
| 1 | Model building | `build_data_catalog`, `run_hydromt_build` | DEM -> staticmaps.nc (soil, veg, rivers) |
| 2 | Forcing | `convert_forcing_to_wflow`, `calculate_pet` | CMFD/MSWX -> wflow NetCDF (P, T, PET) |
| 3 | Parameters | `generate_wflow_toml`, `adjust_parameters` | TOML config + calibration scale/offset |
| 4 | Execution | `run_wflow` | Julia subprocess, JIT compilation, output validation |
| 5 | Postprocess | `extract_discharge`, `extract_spatial_output`, `compare_with_vic` | Q timeseries, spatial maps, VIC comparison |
| 6 | Sediment setup | `build_sediment_model`, `derive_usle_k`, `derive_usle_c` | USLE parameters, grain classes, transport formula |
| 7 | Sediment run | `run_wflow_sediment` | Julia subprocess for sediment model |
| 8 | Sediment post | `analyze_sediment` | Erosion map, sediment yield, grain distribution |
| 9 | Coupling | `wflow_to_cama`, `wflow_recharge_to_modflow` | CaMa-Flood, MODFLOW integration |
| 10 | Reservoir | `lookup_dams`, `configure_reservoirs` | GRanD dams -> wflow reservoir module |

### Parallelism

Stages 0-1 are sequential. Stages 2 and 3 depend on 1. Stage 4 depends on 2+3. Stage 5 depends on 4. Stages 6-8 depend on 4 (sediment uses SBM output). Stage 9 depends on 5. Stage 10 depends on 1 (needs staticmaps.nc) and runs before stage 4.

---

## Tools Reference

| Tool | Stage | Script Path | Lines | Purpose |
|------|-------|-------------|------:|---------|
| `setup_wflow_config` | s0 | `tools/s0_config/setup_wflow_config.py` | 150 | Generate wflow_config.yaml |
| `build_data_catalog` | s1 | `tools/s1_hydromt/build_data_catalog.py` | 160 | HydroMT catalog -> HydroCraft data |
| `run_hydromt_build` | s1 | `tools/s1_hydromt/run_hydromt_build.py` | 250 | Build staticmaps.nc |
| `fetch_merit_hydro_tiles` | s1 | `tools/s1_hydromt/fetch_merit_hydro_tiles.py` | 160 | Stage MERIT-Hydro dir/upa/**elv** tiles for a bbox (resumable) — pass `--kinds dir,upa,elv` |
| `convert_forcing_to_wflow` | s2 | `tools/s2_forcing/convert_forcing_to_wflow.py` | 320 | CMFD/MSWX/VIC -> wflow forcing.nc |
| `calculate_pet` | s2 | `tools/s2_forcing/calculate_pet.py` | 220 | Hargreaves or Penman-Monteith PET |
| `generate_wflow_toml` | s3 | `tools/s3_parameters/generate_wflow_toml.py` | 230 | wflow v1.0+ TOML generator |
| `adjust_parameters` | s3 | `tools/s3_parameters/adjust_parameters.py` | 280 | Scale/offset calibration |
| `run_wflow` | s4 | `tools/s4_execution/run_wflow.py` | 230 | Julia subprocess execution |
| `extract_discharge` | s5 | `tools/s5_postprocess/extract_discharge.py` | 240 | Q timeseries from output NC |
| `extract_spatial_output` | s5 | `tools/s5_postprocess/extract_spatial_output.py` | 160 | Runoff/ET/SM maps |
| `compare_with_vic` | s5 | `tools/s5_postprocess/compare_with_vic.py` | 250 | NSE, PBIAS, KGE comparison |
| `build_sediment_model` | s6 | `tools/s6_sediment/build_sediment_model.py` | 270 | USLE params, grain classes |
| `derive_usle_k` | s6 | `tools/s6_sediment/derive_usle_k.py` | 604 | USLE K from HWSD soil texture (Wischmeier-Smith 1978) |
| `derive_usle_c` | s6 | `tools/s6_sediment/derive_usle_c.py` | 574 | USLE C from AVHRR land cover lookup |
| `run_wflow_sediment` | s7 | `tools/s6_sediment/run_wflow_sediment.py` | 80 | Sediment model execution |
| `analyze_sediment` | s8 | `tools/s8_sediment_post/analyze_sediment.py` | 220 | Erosion analysis |
| `wflow_to_cama` | s9 | `tools/s9_coupling/wflow_to_cama.py` | 170 | wflow -> CaMa-Flood runoff |
| `wflow_recharge_to_modflow` | s9 | `tools/s9_coupling/wflow_recharge_to_modflow.py` | 110 | wflow -> MODFLOW recharge |
| `lookup_dams` | s10 | `tools/s10_reservoir/lookup_dams.py` | 280 | Find dams in basin from GRanD |
| `configure_reservoirs` | s10 | `tools/s10_reservoir/configure_reservoirs.py` | 380 | Add reservoir module to wflow TOML + staticmaps |
| `run_wflow_full_pipeline` | all | `tools/run_wflow_full_pipeline.py` | 220 | End-to-end pipeline |

**Total**: 20 tools + 1 pipeline wrapper + 1 Julia runner = ~6,688 lines

### Skill Documents

| Stage | Document | Key Content |
|-------|----------|-------------|
| s0 | `docs/s0_configuration_skill.md` | Model variant, routing, resolution |
| s1 | `docs/s1_hydromt_setup_skill.md` | HydroMT vs manual build, data catalog |
| s2 | `docs/s2_forcing_skill.md` | Unit conversion table, PET methods |
| s3 | `docs/s3_parameters_skill.md` | TOML format, calibration params, cross-model units |
| s4 | `docs/s4_execution_skill.md` | Julia JIT, memory, warm-start |
| s5 | `docs/s5_output_skill.md` | Discharge extraction, water balance, VIC comparison |
| s6-s8 | `docs/s6_s8_sediment_skill.md` | USLE factors, transport formulas, grain classes |
| s9 | `docs/s9_coupling_skill.md` | CaMa-Flood, MODFLOW, double-counting traps |
| s10 | `docs/s10_reservoir_skill.md` | Reservoir module, GRanD integration, operating rules |

---

## Critical Domain Knowledge

These non-obvious facts cause **silent failures** if violated. Each has a corresponding diagnostic triplet.

### 1. Precipitation must be mm/timestep, NOT mm/s (dt_w001)

wflow expects precipitation in mm per timestep. For daily runs: mm/day. CMFD gives mm/3hr, MSWX gives mm/3hr. If unconverted mm/s is used, runoff is 86400x too high. Model runs without error.

### 2. Temperature must be Celsius, NOT Kelvin (dt_w002)

CMFD/MSWX provide Kelvin. Subtract 273.15. If Kelvin is used directly, PET is wrong, snow never accumulates properly, and the model produces results with no error message.

### 3. wflow v1.0 TOML is DIFFERENT from pre-v1.0 (dt_w006, dt_w022)

The v1.0 release (Dec 2024) changed the TOML format to use CSDMS standard names. Most online examples use the OLD format. Always use `generate_wflow_toml.py` which produces v1.0+ format.

### 4. Julia JIT delay is NORMAL (dt_w009)

First run takes 30-60 seconds before any output appears. This is Julia compiling code, not an error. Do NOT kill the process.

### 5. Double-counting routing with CaMa-Flood (dt_w025)

wflow already routes internally. If routed discharge (q_river) is sent to CaMa-Flood, flow is routed twice. Use UNROUTED runoff variable instead.

### 6. KsatVer units differ across models (dt_w026)

wflow: mm/day. VIC: mm/s. MODFLOW: m/day. Using VIC Ksat directly makes soil 86400x too permeable.

### 7. Grain size fractions must sum to 1.0 (dt_w019)

Five grain classes in wflow_sediment (clay, silt, sand, small/large aggregates) must sum to 100% per cell for mass conservation. Build tool validates this.

### 8. GRanD capacity is MCM, NOT m^3 (dt_w031)

GRanD CAP_MCM is in million cubic meters. wflow maxstorage is in m^3. If MCM values are used directly as m^3, the reservoir appears 1e6 too small and overflows immediately, releasing all inflow uncontrolled. Always multiply by 1e6, or use `lookup_dams.py` which converts automatically.

### 9. Reservoirs must be placed ON river cells (dt_w032)

wflow only activates reservoirs at cells where both `wflow_reservoirlocs > 0` AND `wflow_river = 1`. If the reservoir falls on a non-river cell (common on coarse grids), it is silently ignored. Use `configure_reservoirs.py` which snaps to the nearest river cell.

### 10. Y-axis in staticmaps.nc MUST be DESCENDING (north first) (dt_w034)

wflow expects the y-axis (latitude) in staticmaps.nc to be in DESCENDING order (northernmost cell first). If y is ascending (as `np.arange(min_lat, max_lat)` produces), the LDD flow directions are inverted, causing "cycles detected in flow graph" errors. Always create y as `np.arange(max_lat, min_lat, -step)`. This affects non-China basins where DEM tools may produce ascending grids.

### 11. Mask variables must use NaN for inactive cells, NOT integer 0 (dt_w035)

Variables `wflow_subcatch`, `wflow_ldd`, and `wflow_river` must use float64 with NaN for inactive cells. Using int32 with 0 causes wflow to treat ALL cells as active (0 is a valid subcatchment ID), triggering BoundsError when processing LDD=0 cells. Always use `np.float64` and set inactive cells to `np.nan`.

### 8. LDD must be cycle-free (priority-flood required) (dt_w027)

Naive D8 flow direction on coarse grids (0.25 deg) creates CYCLES in flat areas. wflow will crash with "One or more cycles detected in flow graph." The fix is to use priority-flood from the outlet: process cells from lowest elevation first, each drains to its lowest already-processed neighbor. This guarantees a tree structure with no cycles. Use topological sort (not elevation sort) for flow accumulation after priority-flood.

### 9. VIC forcing file naming pattern needs custom parsing (dt_w028)

HydroCraft VIC forcing files use pattern `{basin}_{res}deg_{lat}_{lon}` (e.g., `bengbu_0.25deg_31.1250_115.6250`). The `convert_forcing_to_wflow.py` tool's default pattern matching does not handle this. Parse with `parts = fname.split("_"); lat = float(parts[2]); lon = float(parts[3])`.

### 10. Inactive cells must be NaN, not 0 (dt_w029)

wflow uses NaN (not 0, not -9999) to mark inactive cells in staticmaps.nc. If zeros are used, wflow treats them as active cells with zero parameter values, producing wrong results without error.

### 11. All 11 state variables are mandatory even for cold start (dt_w030)

The TOML must list all 11 state variables under `[state.variables]` even when `cold_start__flag = true`. Missing any causes a runtime error.

### 12. PET must be provided or configured (dt_w003)

wflow_sbm needs PET as forcing input. If PET is missing, all precipitation becomes runoff (zero ET). Use `calculate_pet.py` to compute from temperature/radiation.

---

## Comparison with VIC

| Feature | VIC 5.1.0 | wflow v1.0.2 |
|---------|-----------|--------------|
| Language | C | Julia |
| Config | Flat text | TOML (structured) |
| I/O | ASCII per cell | NetCDF |
| Soil | 3-layer energy/water balance | Multi-layer SBM (exponential Ksat) |
| Snow | Energy balance | Degree-day (HBV) |
| Routing | External (Lohmann/CaMa) | Built-in (kinematic/local inertial) |
| Sediment | None | USLE + 5 transport formulas |
| Glacier | None (needs OGGM) | Built-in degree-day |
| Parallelism | Serial | Multi-threaded (Julia) |
| Setup | 18 scripts | HydroMT (1 command) or manual |

---

## Coupling Points

| # | Source | Target | Variable | Tool |
|---|--------|--------|----------|------|
| 1 | wflow | CaMa-Flood | Unrouted runoff | `wflow_to_cama` |
| 2 | VIC | wflow | Forcing (shared CMFD/MSWX) | `convert_forcing_to_wflow` |
| 3 | wflow | MODFLOW | GW recharge (m/day) | `wflow_recharge_to_modflow` |
| 4 | wflow_sed | SWAT+ | Sediment loading | (manual) |
| 5 | wflow | VIC | Discharge comparison | `compare_with_vic` |
| 6 | OGGM | wflow | Glacier mass balance | (manual) |

---

## Calibration Parameters (Priority Order)

| Parameter | Unit | Range | Sensitivity | Controls |
|-----------|------|-------|-------------|----------|
| KsatVer | mm/day | 10-10000 | HIGH | Infiltration |
| f | 1/mm | 0.0005-0.005 | HIGH | Baseflow partitioning |
| SoilThickness | mm | 500-5000 | HIGH | Water storage |
| RootingDepth | mm | 100-2000 | MEDIUM | ET depth |
| N_River | s/m^(1/3) | 0.02-0.1 | MEDIUM | Flow timing |
| PathFrac | - | 0-0.3 | MEDIUM | Direct runoff |
| InfiltCapSoil | mm/day | 50-500 | MEDIUM | Surface runoff |

---

## Diagnostic Triplets Summary

26 triplets covering 6 failure domains. See `diagnostics/triplets.yaml` for full details.

| ID | Severity | Domain | Summary |
|----|----------|--------|---------|
| dt_w001 | **silent** | unit_conversion | Precip in mm/s instead of mm/day |
| dt_w002 | **silent** | unit_conversion | Temperature in Kelvin instead of Celsius |
| dt_w003 | **silent** | unit_conversion | PET missing or zero |
| dt_w004 | **silent** | unit_conversion | Snow in tropics (Kelvin not converted) |
| dt_w005 | **silent** | unit_conversion | USLE K in wrong unit system |
| dt_w006 | fatal | runtime | Wflow version mismatch with TOML |
| dt_w007 | fatal | runtime | OutOfMemoryError (domain too large) |
| dt_w008 | fatal | runtime | DimensionMismatch (grid alignment) |
| dt_w009 | degraded | runtime | Julia JIT delay (normal, not error) |
| dt_w010 | fatal | runtime | Variable not found in staticmaps |
| dt_w011 | fatal | parameter_format | Invalid TOML syntax |
| dt_w012 | **silent** | parameter_format | scale=0 makes parameter uniform |
| dt_w013 | **silent** | parameter_format | River network all zeros |
| dt_w014 | fatal | parameter_format | Flow direction boundary error |
| dt_w015 | **silent** | silent_error | Discharge magnitude off (placeholder geometry) |
| dt_w016 | **silent** | silent_error | Glacier fraction all zeros |
| dt_w017 | **silent** | silent_error | f too low (flat hydrograph) |
| dt_w018 | **silent** | silent_error | C factor zero (no erosion) |
| dt_w019 | **silent** | silent_error | Grain fractions don't sum to 1.0 |
| dt_w020 | **silent** | silent_error | wflow vs VIC differ by 3x (expected) |
| dt_w021 | fatal | environment | Wflow package not found |
| dt_w022 | fatal | environment | TOML v1.0 vs pre-v1.0 mismatch |
| dt_w023 | fatal | environment | NetCDF library conflict |
| dt_w024 | degraded | dependency_mismatch | HydroMT version mismatch |
| dt_w025 | **silent** | dependency_mismatch | Double-counting routing |
| dt_w026 | **silent** | dependency_mismatch | Ksat unit mismatch across models |

**Silent error count**: 14/26 (54%) — higher than cross-model average (37%) due to Julia ecosystem and cross-model unit traps.

---

## Quick Start

```bash
# 1. Generate config
python tools/s0_config/setup_wflow_config.py \
  --basin_name chaohe --lat 40.77 --lon 116.85 \
  --start_year 2000 --end_year 2010 --forcing cmfd \
  --shapefile data/shp/chaohe_shp/chaohe.shp \
  --output outputs/chaohe_wflow/wflow_config.yaml

# 2. Build model (manual mode)
python tools/s1_hydromt/run_hydromt_build.py \
  --config outputs/chaohe_wflow/wflow_config.yaml \
  --shapefile data/shp/chaohe_shp/chaohe.shp

# 3. Convert forcing
python tools/s2_forcing/convert_forcing_to_wflow.py \
  --forcing_dir outputs/chaohe_2000_2010_025deg/vic_temp/forcing/forcing_final \
  --grid_nc outputs/chaohe_wflow/wflow_project/staticmaps.nc \
  --start_year 2000 --end_year 2010 \
  --output outputs/chaohe_wflow/wflow_project/forcing.nc

# 4. Generate TOML
python tools/s3_parameters/generate_wflow_toml.py \
  --config outputs/chaohe_wflow/wflow_config.yaml \
  --output outputs/chaohe_wflow/wflow_project/wflow_sbm.toml

# 5. Run wflow
python tools/s4_execution/run_wflow.py \
  --toml outputs/chaohe_wflow/wflow_project/wflow_sbm.toml

# 6. Extract discharge
python tools/s5_postprocess/extract_discharge.py \
  --output_nc outputs/chaohe_wflow/wflow_output/output_grid.nc \
  --output outputs/chaohe_wflow/wflow_output/discharge.csv

# 7. Compare with VIC (optional)
python tools/s5_postprocess/compare_with_vic.py \
  --wflow_csv outputs/chaohe_wflow/wflow_output/discharge.csv \
  --vic_routing_file outputs/chaohe_2000_2010_025deg/routing_param/rout_out/ZJF.day \
  --output outputs/chaohe_wflow/comparison.json \
  --plot outputs/chaohe_wflow/comparison.png
```

---

## File Structure

```
models/wflow/knowledge_infrastructure/
  DISSECTION_PLAN.md              # Original dissection plan
  SKILL.md                        # This file (agent entry point)
  knowledge_infrastructure.yaml   # Schema-compliant package definition
  julia/
    wflow_runner.jl               # Julia execution wrapper
  tools/
    s0_config/setup_wflow_config.py
    s1_hydromt/build_data_catalog.py
    s1_hydromt/run_hydromt_build.py
    s2_forcing/convert_forcing_to_wflow.py
    s2_forcing/calculate_pet.py
    s3_parameters/generate_wflow_toml.py
    s3_parameters/adjust_parameters.py
    s4_execution/run_wflow.py
    s5_postprocess/extract_discharge.py
    s5_postprocess/extract_spatial_output.py
    s5_postprocess/compare_with_vic.py
    s6_sediment/build_sediment_model.py
    s6_sediment/derive_usle_k.py
    s6_sediment/derive_usle_c.py
    s6_sediment/run_wflow_sediment.py
    s8_sediment_post/analyze_sediment.py
    s9_coupling/wflow_to_cama.py
    s9_coupling/wflow_recharge_to_modflow.py
    s10_reservoir/lookup_dams.py
    s10_reservoir/configure_reservoirs.py
    run_wflow_full_pipeline.py
  docs/
    s0_configuration_skill.md
    s1_hydromt_setup_skill.md
    s2_forcing_skill.md
    s3_parameters_skill.md
    s4_execution_skill.md
    s5_output_skill.md
    s6_s8_sediment_skill.md
    s9_coupling_skill.md
    s10_reservoir_skill.md
  diagnostics/
    triplets.yaml                 # 29 diagnostic triplets
    error_log.yaml                # Errors from real runs
    episodes.yaml                 # Debugging stories

model/wflow/                      # Model installation directory
  (Julia + Wflow.jl to be installed here)
```
