---
name: oggm
description: >-
  OGGM 1.6.x flowline glacier framework. Covers Mountain glacier mass balance, volume,
  area, length and geometry evolution at glacier-to-global…; Climatic surface mass balance
  via monthly temperature-index model; Ice thickness / bed-topography inversion
  (shallow-ice, mass conservation, Glen's flow law); 1.5D flowline ice dynamics
  (shallow-ice approximation). Use when the task involves running, configuring,
  calibrating or interpreting OGGM.
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

### Climate data

**Input Source**: OGGM handles climate data internally via its built-in CRU/ERA5/W5E5 downloaders.
- `process_climate_baseline.py` — Processes historical climate baseline for mass balance calibration
- `process_cmip6_projections.py` — Processes CMIP6 projections for future glacier simulations
- `process_custom_climate.py` — Processes custom climate data (e.g., CMFD/MSWX via ki_tools_common)
- `calibrate_mass_balance.py` — Calibrates mass balance model against geodetic observations

**Data Validation Reference**: See `data_ki/CMIP6/SKILL.md` for CMIP6 projection documentation.
See `data_ki/RGI/SKILL.md` for Randolph Glacier Inventory documentation.

---

# OGGM (Open Global Glacier Model) — HydroCraft Knowledge Infrastructure

## What is OGGM?

The **Open Global Glacier Model (OGGM)** is a modular, open-source framework for simulating the past and future evolution of glaciers worldwide. Developed at the University of Innsbruck (Austria), OGGM uses the Randolph Glacier Inventory (RGI) as its glacier inventory backbone, performs flowline-based glacier dynamics using the shallow-ice approximation, and computes surface mass balance from temperature and precipitation data. OGGM can simulate individual glaciers or entire regions (up to all ~220,000 glaciers globally).

OGGM is the de facto standard for large-scale glacier projections under climate change and has been used in IPCC AR6 assessments. For HydroCraft, OGGM provides the glacier dynamics component needed to model cryospheric contributions to river discharge in glacierized basins (e.g., Yarlung Tsangpo, Heihe upper basin, Central Asian rivers).

**Key capabilities:**
- Glacier-by-glacier dynamics simulation using 1D flowline models
- Mass balance computation calibrated against geodetic observations (Hugonnet et al. 2021)
- Future projections under CMIP6 scenarios (SSP126/245/370/585)
- Hydrological output: melt, liquid precipitation, refreezing, runoff
- Global coverage: all 19 RGI regions, pre-processed data available
- Python API with entity-based and global workflow tasks

## Installation

OGGM requires a specific Python environment. **Use conda, not pip**, for reliable installation:

```bash
# Create a separate conda environment (recommended)
conda create -n oggm_env python=3.11 numpy=1.26
conda activate oggm_env

# Install OGGM with all dependencies
conda install -c conda-forge oggm

# Or via pip (less reliable for GDAL/GEOS dependencies)
pip install oggm
```

**Critical version constraints:**
- Python >= 3.9, < 3.12 (3.12 breaks some OGGM dependencies)
- numpy < 2.0 (OGGM and salem are not yet numpy 2.0 compatible)
- GDAL/GEOS: installed via conda to avoid compilation issues

**Disk space requirements:**
- OGGM code + dependencies: ~2 GB
- Climate data (W5E5): ~4-8 GB (downloaded on first use, cached)
- RGI outlines: ~50-500 MB per region
- Glacier directories: 5-50 MB per glacier (varies with preprocessing level)
- For a basin with 500 glaciers at prepro level 5: ~10-25 GB

**For HydroCraft integration**, OGGM can run in the project's existing Python environment if dependencies are satisfied, or in a separate conda environment called from the pipeline via subprocess.

## Key Concepts

### Glacier Directories (GDirs)

The fundamental data structure in OGGM. Each glacier gets its own directory containing:
- `outlines.tar.gz` — Glacier boundary polygon from RGI
- `dem.tif` — Digital elevation model clipped to glacier extent + border
- `gridded_data.nc` — Gridded glacier data (ice thickness, velocity)
- `model_flowlines.pkl` — Glacier flowlines for dynamics simulation
- `inversion_flowlines.pkl` — Flowlines with inverted bed thickness
- `climate_historical.nc` — Climate time series at glacier location
- `climate_info.pkl` — Calibration parameters (mu_star, pcf, tbias)
- `model_diagnostics.nc` — Simulation output (volume, area, length)
- `run_output_hydro.nc` — Hydrological output (melt, precip, runoff)

GDirs are created by `workflow.init_glacier_directories()` and progressively enriched by each processing task.

### Preprocessing Levels (L0-L5)

OGGM supports pre-processed glacier directories at 6 levels, downloadable from the Bremen server:

| Level | Contents | Typical Size per Glacier |
|-------|----------|------------------------|
| L0 | Raw RGI outlines only | <1 MB |
| L1 | DEM + outlines | 2-5 MB |
| L2 | + Climate data (W5E5) | 3-8 MB |
| L3 | + Flowlines + catchments | 5-15 MB |
| L4 | + Ice thickness inversion | 8-20 MB |
| L5 | + Dynamic spinup (run-ready) | 10-50 MB |

**Recommendation:** Use L5 for production runs (everything pre-computed, just run simulation). Use L3 if you need custom climate data or calibration. Use L1 only for full custom processing.

### Entity Tasks vs. Global Tasks

OGGM tasks come in two types:
- **Entity tasks** operate on a single glacier (e.g., `tasks.compute_centerlines`). Applied via `workflow.execute_entity_task()`.
- **Global tasks** operate on all glaciers (e.g., `workflow.calibrate_inversion_from_consensus`). Called directly.

### RGI (Randolph Glacier Inventory)

The global glacier inventory used by OGGM:
- **RGI v6.0** (2017): 216,502 glaciers, 19 first-order regions — default, well-tested
- **RGI v7.0** (2023): Updated outlines, better coverage — partial OGGM support

RGI regions relevant to HydroCraft basins:
- **Region 13**: Central Asia (Tien Shan, Pamir, Karakoram)
- **Region 14**: South Asia West (Hindu Kush, Western Himalaya)
- **Region 15**: South Asia East (Eastern Himalaya, Yarlung Tsangpo glaciers)
- **Region 10**: North Asia (includes Altai, relevant for Heihe headwaters)

## Pipeline Overview

The OGGM pipeline has 6 stages, designed to integrate with HydroCraft's VIC workflow:

```
Stage 1: Glacier Inventory
  Basin shapefile -> RGI spatial intersection -> glacier list
  Tools: find_glaciers_in_basin, download_rgi_region, validate_glacier_selection

Stage 2: Preprocessing
  Initialize OGGM -> Create GDirs (or download pre-processed)
  Tools: configure_oggm, init_glacier_directories, validate_preprocessing

Stage 3: Climate Input
  Process baseline climate (W5E5/CRU) and/or CMIP6 projections
  Tools: process_climate_baseline, process_custom_climate, process_cmip6_projections

Stage 4: Calibration
  Calibrate mass balance against Hugonnet 2021 geodetic observations
  Tools: calibrate_mass_balance, validate_calibration

Stage 5: Simulation
  Run glacier dynamics (historical and/or projections)
  Tools: run_glacier_simulation, run_glacier_projections, compile_glacier_output

Stage 6: VIC Coupling
  Convert OGGM output to VIC grid, analyze glacier contribution
  Tools: oggm_to_vic_runoff, glacier_contribution_analysis, plot_glacier_hydro
```

## Critical Domain Knowledge

### 1. Hydrological Year Mismatch (SILENT ERROR)

OGGM uses a hydrological year starting **October 1** (Northern Hemisphere) or **April 1** (Southern Hemisphere). VIC uses a **calendar year** (January 1 - December 31). When coupling OGGM monthly outputs with VIC:

- OGGM "month 1" of hydrological year 2010 = **October 2009**
- VIC "month 1" of calendar year 2010 = **January 2010**
- A naive month-by-month merge shifts glacier melt by 3 months

**Solution:** Always convert OGGM output to calendar dates before merging with VIC. OGGM stores actual dates in the time dimension of its NetCDF output — use those, not month indices.

### 2. Double-Counting Trap (SILENT ERROR)

VIC simulates snow accumulation and melt on ALL grid cells, including those covered by glaciers. OGGM also computes melt on glacier surfaces. If you simply add OGGM melt to VIC discharge, melt from glacier areas is counted twice.

**Solutions (choose one):**
- **A. Mask VIC glacier cells** — Set VIC glacier cells to bare rock/ice (no snow accumulation), let OGGM handle all ice/snow processes. Cleanest but requires modifying VIC input.
- **B. Subtract VIC snowmelt** — From OGGM's total melt output, subtract VIC's snowmelt on glacier cells. `net_glacier_melt = OGGM_melt - VIC_snowmelt_on_glacier_cells`.
- **C. Post-hoc correction** — Apply a correction factor based on glacier fraction. Approximate but fast for small glacier fractions (<5%).

For glacier fractions < 1%, the double-counting error is negligible. For fractions > 10%, it must be explicitly handled.

### 3. Glacier Fraction Decision Threshold

Before running OGGM, compute the glacier fraction of the basin:

| Fraction | Action |
|----------|--------|
| < 0.1% | Skip OGGM entirely — glaciers are negligible |
| 0.1% - 1% | Optional — glaciers contribute minimally to discharge |
| 1% - 10% | Recommended — glaciers affect late-summer discharge |
| > 10% | Required — glaciers are a major discharge component |

### 4. Peak Water

Glacierized basins under warming exhibit "peak water" — initially increasing runoff (warmer temperatures melt more ice) followed by declining runoff (less ice available to melt). The peak water year depends on:
- Current glacier volume (larger glaciers = later peak)
- Warming rate (faster warming = earlier peak)
- Basin hypsometry (higher glaciers = later peak)

Peak water has major implications for water resource planning. OGGM projections can identify the peak water timing under different SSP scenarios.

### 5. Pre-Processed Directories

For most basins, **use pre-processed glacier directories** from the Bremen server rather than running the full preprocessing pipeline. This saves:
- DEM download and processing (minutes per glacier)
- Centerline computation (can fail for complex glacier shapes)
- Bed inversion (computationally expensive)
- Total: hours of computation for basins with hundreds of glaciers

Pre-processed L5 directories are fully run-ready — just initialize, (optionally) add custom climate, calibrate, and run.

### 6. RGI v6 vs v7

- **RGI v6.0** (2017): Default in OGGM, extensively validated, recommended
- **RGI v7.0** (2023): Updated outlines, new glaciers added, some outlines improved. OGGM support is partial — some pre-processed data may not be available for v7.

Use v6 unless you have a specific reason for v7 (e.g., known v6 errors in your study area).

### 7. Storage and Performance

| Basin Size | Est. Glaciers | Disk Space | Runtime (L5) | Runtime (L1) |
|-----------|--------------|-----------|-------------|-------------|
| Heihe Upper (~9000 km2) | ~50-200 | 0.5-4 GB | 5-15 min | 30-90 min |
| Yarlung Tsangpo (~200000 km2) | ~5000-15000 | 25-150 GB | 1-6 hrs | 12-48 hrs |
| Central Asia (Region 13) | ~27000 | 50-250 GB | 4-12 hrs | 24-96 hrs |

## Quick-Start Workflow

```python
import oggm
from oggm import cfg, utils, workflow, tasks

# 1. Configure
cfg.initialize()
cfg.PATHS['working_dir'] = '/path/to/working_dir'

# 2. Get RGI IDs (from find_glaciers_in_basin output)
rgi_ids = ['RGI60-15.00001', 'RGI60-15.00002', ...]

# 3. Initialize GDirs from pre-processed L5
base_url = 'https://cluster.klima.uni-innsbruck.at/~oggm/gdirs/oggm_v1.6/'
gdirs = workflow.init_glacier_directories(
    rgi_ids,
    from_prepro_level=5,
    prepro_border=80,
    prepro_base_url=base_url
)

# 4. Run historical simulation with hydro output
workflow.execute_entity_task(
    tasks.run_with_hydro, gdirs,
    run_task=tasks.run_from_climate_data,
    min_ys=2000, max_ys=2020,
    store_monthly_hydro=True
)

# 5. Compile output
ds = utils.compile_run_output(gdirs)
# ds has: volume, area, length per glacier per year
```

## VIC Coupling Modes

### Mode A: Post-VIC Injection (Recommended)

1. Run VIC normally for the full basin
2. Run OGGM for glaciers in the basin
3. At the routing stage, add OGGM glacier melt to VIC runoff at glacier cells
4. Route combined flow through Lohmann or CaMa-Flood

**Pros:** Simplest, no VIC modification needed, works with existing routing
**Cons:** Double-counting must be handled, VIC and OGGM use different climate

### Mode B: Forcing Augmentation

1. Modify VIC vegetation/soil parameters for glacier cells (bare ice/rock)
2. Run VIC — glacier cells produce snowmelt but no vegetation ET
3. Run OGGM — provides ice melt (the component VIC cannot simulate)
4. Add OGGM ice melt to VIC glacier cell output

**Pros:** Cleaner physical separation (VIC=snow, OGGM=ice), less double-counting
**Cons:** Requires modifying VIC input, more complex setup

### Mode C: Two-Way Dynamic Coupling (Research-Grade)

1. VIC provides energy balance at glacier surface to OGGM
2. OGGM provides glacier geometry changes back to VIC (changing glacier extent)
3. Fully dynamic with annual or sub-annual coupling timestep

**Pros:** Most physically realistic
**Cons:** Very complex, not operational, research-level implementation

**For HydroCraft, Mode A is recommended.** It works with the existing VIC + routing pipeline and requires only adding OGGM output at the routing stage.

## Priority Basins for HydroCraft

### Yarlung Tsangpo (雅鲁藏布江)
- **Glacier fraction:** ~10% of basin area (20,000+ km2 of glaciers)
- **RGI region:** 15 (South Asia East)
- **Significance:** High glacier contribution to discharge (15-25% annually, 40-60% late summer)
- **HydroCraft status:** VIC+CaMa calibrated (NSE=0.90), ready for OGGM coupling
- **Peak water:** Projected 2030-2060 depending on SSP

### Heihe Upper (黑河上游)
- **Glacier fraction:** ~5% of basin area
- **RGI region:** 13 (Central Asia) / 10 (North Asia)
- **Significance:** Arid basin, glacier melt critical for summer baseflow
- **HydroCraft status:** VIC+CaMa simulated, uncalibrated
- **Peak water:** Potentially already passed or imminent

### Central Asian Rivers (Syr Darya, Amu Darya)
- **Glacier fraction:** ~15-30% in headwater basins
- **RGI region:** 13 (Central Asia)
- **Significance:** Heavily glacierized headwaters, downstream agriculture dependent on glacier melt
- **Peak water:** Critical for regional water security, projected 2040-2080

## File Structure

```
models/OGGM/knowledge_infrastructure/
  knowledge_infrastructure.yaml   # Main KI definition
  SKILL.md                        # This file
  tools/
    s1_glacier_inventory/
      find_glaciers_in_basin.py
      download_rgi_region.py
      validate_glacier_selection.py
    s2_preprocessing/
      configure_oggm.py
      init_glacier_directories.py
      validate_preprocessing.py
    s3_climate_input/
      process_climate_baseline.py
      process_custom_climate.py
      process_cmip6_projections.py
    s4_calibration/
      calibrate_mass_balance.py
      validate_calibration.py
    s5_simulation/
      run_glacier_simulation.py
      run_glacier_projections.py
      compile_glacier_output.py
    s6_vic_coupling/
      oggm_to_vic_runoff.py
      glacier_contribution_analysis.py
      plot_glacier_hydro.py
  docs/
    s1_glacier_inventory_skill.md
    s2_preprocessing_skill.md
    s3_climate_input_skill.md
    s4_calibration_skill.md
    s5_simulation_skill.md
    s6_vic_coupling_skill.md
    model_couplings.yaml
  diagnostics/
    triplets.yaml
  workflow/
    workflow.md
```

## Common Errors and Solutions

| Error | Cause | Solution |
|-------|-------|---------|
| `HTTPError 404` on GDir download | RGI ID not in pre-processed archive | Check RGI ID format; try different prepro_level |
| `RuntimeError: Glacier is a nominal glacier` | RGI outline is a point, not polygon | Exclude this glacier (it's too small or data-deficient) |
| `ValueError: CFL condition violated` | FluxBasedModel unstable | Switch to SemiImplicitModel |
| Zero glaciers found in basin | CRS mismatch or wrong RGI region | Verify CRS alignment; check RGI region auto-detection |
| `MemoryError` processing many glaciers | Too many GDirs loaded simultaneously | Process in batches of 100-500 |
| mu_star at bounds (0 or 1000) | Climate data mismatch or surge glacier | Check climate data units; exclude problematic glaciers |
| Negative ice thickness | Bed inversion numerical issue | Increase border; use pre-processed L4+ |
| `FileNotFoundError: DEM not found` | SRTM void above 60N | Set dem_source='COPDEM' for high-latitude glaciers |
