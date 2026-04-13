# OGGM Workflow for HydroCraft Integration

## Overview

This workflow integrates OGGM glacier dynamics with HydroCraft's VIC hydrological model for glacierized basin simulation. The workflow has 6 stages that produce glacier melt runoff as additional input to VIC's routing stage.

## Prerequisites

Before starting the OGGM workflow:
1. **VIC simulation completed** — Stages 1-7 of the HydroCraft VIC workflow (grid, soil, veg, forcing, VIC run)
2. **Basin shapefile available** — From delineation or user-provided
3. **OGGM installed** — In conda environment or project venv (Python <3.12, numpy <2.0)
4. **Disk space** — 10-50 GB depending on number of glaciers

## Stage Dependencies

```
Stage 1: Glacier Inventory ──────────────────────────────┐
    (needs: basin shapefile)                               │
                                                           v
Stage 2: Preprocessing ──────────────────────────────────┐
    (needs: Stage 1 glacier list)                          │
                                                           v
Stage 3: Climate Input ──────────────────────────────────┐
    (needs: Stage 2 GDirs)                                 │
                                                           v
Stage 4: Calibration ────────────────────────────────────┐
    (needs: Stage 3 climate data)                          │
                                                           v
Stage 5: Simulation ─────────────────────────────────────┐
    (needs: Stage 4 calibrated params)                     │
                                                           v
Stage 6: VIC Coupling ───────────────────────────────────┘
    (needs: Stage 5 OGGM output + VIC output)
```

Stages 1-5 are sequential. Stage 6 also requires completed VIC simulation (independent of OGGM stages 1-5).

## Detailed Steps

### Step 0: Assess Glacier Need

Before running OGGM, determine if glacier modeling is warranted:

```bash
# Quick check: is the basin in a glacierized region?
# Regions with significant glaciers:
# - Tibetan Plateau / Himalaya (lat 25-40, lon 70-105)
# - Central Asia (lat 35-50, lon 60-90)
# - European Alps (lat 43-48, lon 5-16)
# - Andes (lat -55 to 10, lon -75 to -65)
# - Alaska/Western Canada (lat 55-70, lon -165 to -120)
# - Arctic (lat >65)
```

If the basin is clearly non-glacierized (e.g., Huai River, Pearl River), skip OGGM entirely.

### Step 1: Glacier Inventory

```bash
# 1a. Download RGI region (if not cached)
python models/OGGM/knowledge_infrastructure/tools/s1_glacier_inventory/download_rgi_region.py \
  --lat <basin_lat> --lon <basin_lon> \
  --output_dir data/rgi/RGIV62

# 1b. Find glaciers in basin
python models/OGGM/knowledge_infrastructure/tools/s1_glacier_inventory/find_glaciers_in_basin.py \
  --basin_shp data/shp/<basin>_shp/<basin>_boundary.shp \
  --min_area_km2 0.01 \
  --output outputs/<run>/oggm/glaciers_in_basin.csv

# 1c. Validate selection
python models/OGGM/knowledge_infrastructure/tools/s1_glacier_inventory/validate_glacier_selection.py \
  --glacier_csv outputs/<run>/oggm/glaciers_in_basin.csv \
  --basin_area_km2 <area>
```

**Decision point:** If glacier_fraction < 0.1%, skip remaining OGGM stages.

### Step 2: Preprocessing

```bash
# 2a. Configure OGGM
python models/OGGM/knowledge_infrastructure/tools/s2_preprocessing/configure_oggm.py \
  --working_dir outputs/<run>/oggm/working_dir \
  --border 80 --multiprocessing true

# 2b. Initialize glacier directories (from pre-processed L5)
python models/OGGM/knowledge_infrastructure/tools/s2_preprocessing/init_glacier_directories.py \
  --rgi_ids outputs/<run>/oggm/glaciers_in_basin.csv \
  --working_dir outputs/<run>/oggm/working_dir \
  --prepro_level 5

# 2c. Validate
python models/OGGM/knowledge_infrastructure/tools/s2_preprocessing/validate_preprocessing.py \
  --working_dir outputs/<run>/oggm/working_dir
```

**Expected runtime:** 5-30 minutes depending on number of glaciers and internet speed.

### Step 3: Climate Input

```bash
# 3a. Process baseline climate (W5E5 default)
python models/OGGM/knowledge_infrastructure/tools/s3_climate_input/process_climate_baseline.py \
  --working_dir outputs/<run>/oggm/working_dir \
  --source W5E5

# 3b. (Optional) Custom climate from CMFD/MSWX
python models/OGGM/knowledge_infrastructure/tools/s3_climate_input/process_custom_climate.py \
  --working_dir outputs/<run>/oggm/working_dir \
  --climate_dir data/forcing/Data_forcing_03hr_010deg \
  --format CMFD --start_year 2000 --end_year 2018

# 3c. (Optional) CMIP6 projections
python models/OGGM/knowledge_infrastructure/tools/s3_climate_input/process_cmip6_projections.py \
  --working_dir outputs/<run>/oggm/working_dir \
  --gcm BCC-CSM2-MR --ssp ssp245 \
  --start_year 2020 --end_year 2100
```

### Step 4: Calibration

```bash
# 4a. Calibrate mass balance
python models/OGGM/knowledge_infrastructure/tools/s4_calibration/calibrate_mass_balance.py \
  --working_dir outputs/<run>/oggm/working_dir

# 4b. Validate calibration
python models/OGGM/knowledge_infrastructure/tools/s4_calibration/validate_calibration.py \
  --working_dir outputs/<run>/oggm/working_dir \
  --tolerance_mm_yr 50
```

### Step 5: Simulation

```bash
# 5a. Historical simulation
python models/OGGM/knowledge_infrastructure/tools/s5_simulation/run_glacier_simulation.py \
  --working_dir outputs/<run>/oggm/working_dir \
  --start_year 2000 --end_year 2020 \
  --use_spinup true

# 5b. (Optional) Future projections
python models/OGGM/knowledge_infrastructure/tools/s5_simulation/run_glacier_projections.py \
  --working_dir outputs/<run>/oggm/working_dir \
  --gcm BCC-CSM2-MR --ssp ssp245 \
  --start_year 2020 --end_year 2100

# 5c. Compile output
python models/OGGM/knowledge_infrastructure/tools/s5_simulation/compile_glacier_output.py \
  --working_dir outputs/<run>/oggm/working_dir \
  --output_dir outputs/<run>/oggm/compiled
```

### Step 6: VIC Coupling

```bash
# 6a. Convert OGGM output to VIC grid
python models/OGGM/knowledge_infrastructure/tools/s6_vic_coupling/oggm_to_vic_runoff.py \
  --oggm_output outputs/<run>/oggm/compiled/compiled_output.nc \
  --vic_grid_nc outputs/<run>/vic_temp/grid/basin_grid.nc \
  --glacier_csv outputs/<run>/oggm/glaciers_in_basin.csv \
  --output_dir outputs/<run>/oggm/vic_coupling

# 6b. Contribution analysis
python models/OGGM/knowledge_infrastructure/tools/s6_vic_coupling/glacier_contribution_analysis.py \
  --oggm_runoff outputs/<run>/oggm/vic_coupling/glacier_runoff_vic_grid.nc \
  --vic_discharge outputs/<run>/routing_param/rout_out/station.day \
  --basin_area_km2 <area> \
  --output outputs/<run>/oggm/glacier_contribution.json

# 6c. Visualization
python models/OGGM/knowledge_infrastructure/tools/s6_vic_coupling/plot_glacier_hydro.py \
  --oggm_output outputs/<run>/oggm/compiled/compiled_output.nc \
  --basin_shp data/shp/<basin>_shp/<basin>_boundary.shp \
  --output_dir outputs/<run>/oggm/plots
```

## Expected Runtimes

| Step | Typical | Max | Notes |
|------|---------|-----|-------|
| S1: Inventory | 10-30s | 2 min | Spatial join is fast |
| S2: Preprocessing (L5) | 5-30 min | 2 hrs | Download-limited |
| S2: Preprocessing (L1) | 30 min-6 hrs | 48 hrs | CPU-intensive |
| S3: Climate | 2-10 min | 30 min | Download + processing |
| S4: Calibration | 1-10 min | 30 min | Optimization per glacier |
| S5: Simulation | 5-60 min | 6 hrs | Depends on glaciers and period |
| S6: Coupling | 1-5 min | 15 min | Conversion and plotting |
| **Total (L5 path)** | **15-90 min** | **~10 hrs** | |

## After OGGM Completes

The glacier contribution has been added to the basin hydrology. Report to the user:
1. Number of glaciers found and total glacier area
2. Glacier fraction of basin area
3. Mean annual glacier contribution to discharge (%)
4. Seasonal pattern (summer peak contribution)
5. Peak water year (if projections were run)
6. Visualization paths

Then continue with standard HydroCraft post-processing (calibration, additional routing, etc.).

## Troubleshooting Quick Reference

| Issue | First Check | Solution |
|-------|------------|---------|
| 0 glaciers found | CRS of basin shapefile | Reproject to EPSG:4326 |
| Download fails | Internet / server status | Retry or use local RGI |
| DEM error | Glacier latitude | Use COPDEM for >60N |
| Calibration fails | Climate data period | Ensure 2000-2020 overlap |
| Simulation slow | Model type | Switch to SemiImplicit |
| Wrong seasonal pattern | Month indexing | Use actual dates, not indices |
| Discharge too high | Double-counting | Subtract VIC snowmelt on glacier cells |
| Memory error | Too many glaciers | Process in batches of 100-500 |
