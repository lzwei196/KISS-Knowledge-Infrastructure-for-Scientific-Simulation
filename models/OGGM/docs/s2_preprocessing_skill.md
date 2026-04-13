# Stage 2: Glacier Preprocessing (Glacier Directories)

## Purpose

Initialize OGGM Glacier Directories (GDirs) — the self-contained data structure where each glacier stores its DEM, outlines, flowlines, bed geometry, and derived products. This stage transforms a list of RGI IDs into run-ready glacier model units. Preprocessing is computationally expensive if done from scratch (DEM download, centerline computation, bed inversion) but can be bypassed by downloading pre-processed directories from the OGGM Bremen server.

## Prerequisites

- **Validated glacier list** from Stage 1 (CSV with RGI IDs)
- **OGGM installed** with `oggm.cfg.initialize()` callable
- **Disk space** — 5-50 MB per glacier depending on preprocessing level. For a basin with 500 glaciers, budget 2.5-25 GB.
- **Internet connection** — Required for downloading pre-processed directories or DEM tiles (first use only)
- **Working directory** — A writable directory for OGGM to store all glacier data

## Inputs

| Input | Type | Required | Description |
|-------|------|----------|-------------|
| `working_dir` | directory | Yes | Root directory for OGGM glacier data |
| `rgi_ids` | list/CSV | Yes | List of RGI IDs or path to glacier CSV |
| `prepro_level` | int | No | Preprocessing level 1-5 (default 5) |
| `prepro_border` | int | No | Border pixels: 80 (default) or 160 |
| `from_prepro` | bool | No | Use pre-processed directories (default true) |
| `border` | int | No | DEM border for from-scratch processing (default 80) |
| `dem_source` | string | No | DEM: 'COPDEM', 'SRTM', 'NASADEM', 'AW3D30' |
| `multiprocessing` | bool | No | Enable parallel processing (default true) |

## Procedure

### Step 1: Configure OGGM

Run `configure_oggm.py` to set up the OGGM environment:

```python
import oggm
from oggm import cfg
cfg.initialize()
cfg.PATHS['working_dir'] = working_dir
cfg.PARAMS['border'] = 80
cfg.PARAMS['use_multiprocessing'] = True
cfg.PARAMS['dl_verify'] = True
```

Key configuration parameters:
- **border**: Pixels of DEM surrounding the glacier outline. 80 is default (sufficient for most glaciers). Use 160 for glaciers expected to advance significantly (e.g., under LIA conditions for spinup).
- **use_multiprocessing**: True for batch processing, False for debugging (easier error tracing).
- **dl_verify**: True to verify download checksums. Set False behind corporate proxies that modify downloads.

### Step 2: Initialize Glacier Directories

**Option A: From Pre-Processed Directories (Recommended)**

```python
from oggm import workflow
base_url = 'https://cluster.klima.uni-innsbruck.at/~oggm/gdirs/oggm_v1.6/'
gdirs = workflow.init_glacier_directories(
    rgi_ids,
    from_prepro_level=5,  # L5 = fully run-ready
    prepro_border=80,
    prepro_base_url=base_url
)
```

This downloads pre-computed glacier directories from the Bremen server. Each GDir is a ~10-50 MB tar archive that gets extracted into the working directory. L5 includes everything needed for simulation: DEM, flowlines, inversion, climate, and dynamic spinup.

**Option B: From Scratch**

```python
gdirs = workflow.init_glacier_directories(rgi_ids)

# Process each glacier
workflow.execute_entity_task(tasks.define_glacier_region, gdirs)
workflow.execute_entity_task(tasks.glacier_masks, gdirs)
workflow.execute_entity_task(tasks.compute_centerlines, gdirs)
workflow.execute_entity_task(tasks.initialize_flowlines, gdirs)
workflow.execute_entity_task(tasks.compute_downstream_line, gdirs)
workflow.execute_entity_task(tasks.compute_downstream_bedshape, gdirs)
workflow.execute_entity_task(tasks.catchment_area, gdirs)
workflow.execute_entity_task(tasks.catchment_intersections, gdirs)
workflow.execute_entity_task(tasks.catchment_width_geom, gdirs)
workflow.execute_entity_task(tasks.catchment_width_correction, gdirs)
```

This sequence: downloads DEM, clips to glacier extent, computes glacier masks, finds centerlines (the flow paths), converts to flowlines, and computes catchment properties. Each step can fail for individual glaciers (see Common Pitfalls).

### Step 3: DEM Source Selection

OGGM supports multiple DEM sources:

| Source | Coverage | Resolution | Notes |
|--------|----------|-----------|-------|
| SRTM | 60S-60N | 90m | Default. Has voids above 60N and in steep terrain |
| COPDEM (Copernicus) | Global | 30m/90m | Best global coverage, recommended for high latitudes |
| NASADEM | 60S-60N | 30m | Improved SRTM with void-filling |
| AW3D30 (ALOS) | Global | 30m | Good but requires registration |
| RAMP | Antarctic | 200m | Only for Antarctic glaciers |
| DEM3 | Iceland | 30m | Iceland-specific |

**For glaciers above 60N** (Arctic, Svalbard, Scandinavia, Alaska): Use COPDEM or AW3D30. SRTM has no coverage and will cause DEM download failures (dt_004).

### Step 4: Bed Inversion

If processing from scratch (or using prepro_level < 4), run ice thickness inversion:

```python
from oggm import tasks
workflow.execute_entity_task(tasks.prepare_for_inversion, gdirs)
workflow.calibrate_inversion_from_consensus(gdirs)
workflow.execute_entity_task(tasks.mass_conservation_inversion, gdirs)
workflow.execute_entity_task(tasks.filter_inversion_output, gdirs)
```

The bed inversion estimates ice thickness from surface slope using the shallow-ice approximation, calibrated against consensus ice thickness estimates (Farinotti et al. 2019). Negative thickness values indicate numerical issues — typically from DEM artifacts or very thin glacier margins.

### Step 5: Validate Preprocessing

Run `validate_preprocessing.py` to check all GDirs:

1. **Flowlines exist** — `model_flowlines.pkl` must be present
2. **Volume > 0** — Zero volume means inversion failed
3. **DEM coverage** — DEM must fully cover glacier extent + border
4. **No NaN arrays** — Critical arrays (thickness, width, surface height) must be clean
5. **Statistics** — Report total glaciers, valid count, failed count, total volume

## Expected Outputs

| Output | Location | Description |
|--------|----------|-------------|
| Glacier directories | `{working_dir}/per_glacier/` | One subdirectory per glacier |
| `model_flowlines.pkl` | Per GDir | Flowline geometry and properties |
| `inversion_flowlines.pkl` | Per GDir | Flowlines with inverted bed thickness |
| `dem.tif` | Per GDir | Clipped DEM |
| `outlines.tar.gz` | Per GDir | Glacier boundary polygon |
| `gridded_data.nc` | Per GDir | Gridded glacier data |

## Validation Checks

1. **All RGI IDs processed** — Compare requested vs. actual GDir count
2. **No empty GDirs** — Each GDir must have minimum required files
3. **Positive volume** — All glaciers must have estimated volume > 0
4. **Flowline quality** — At least one flowline per glacier; main flowline starts at highest point
5. **DEM quality** — No NaN pixels within glacier outline

## Common Pitfalls

### Centerline Computation Failure (dt_005)
Glaciers with unusual shapes (very wide, kidney-shaped, detached ice patches) can cause the centerline algorithm to fail. OGGM will log a warning and skip the glacier. Check the failed list and consider excluding these glaciers or using a simpler geometry method.

### Negative Ice Thickness (dt_006)
Bed inversion can produce negative thickness values at glacier margins or in areas with DEM artifacts. The filter_inversion_output task clips negative values to zero, but this may result in unrealistic bed geometry. For important glaciers, inspect the bed profile manually.

### Disk Space Exhaustion (dt_007)
Processing 1000+ glaciers from scratch generates 5-50 GB of data. Monitor disk space during processing. Pre-processed L5 directories are more space-efficient because they use compressed formats.

### SRTM Voids Above 60N (dt_004)
SRTM has no data above 60 degrees north latitude. Glaciers in Svalbard (RGI-07), Scandinavia (RGI-08), Russian Arctic (RGI-09), and parts of Alaska (RGI-01) will fail DEM download if SRTM is the configured source. Set `dem_source='COPDEM'` for these regions.

### Bremen Server Unreachable
The OGGM pre-processed directory server at cluster.klima.uni-innsbruck.at may be temporarily down for maintenance. The tool implements retry logic (3 attempts with exponential backoff). If all retries fail, fall back to from-scratch processing.

### Border Too Small
If border is too small (e.g., 10 pixels), the glacier's flowline may extend beyond the DEM edge during simulation (especially during spinup when the glacier was larger). Use border=80 (default) or border=160 for spinup scenarios.

## Tools Reference

| Tool | Script | Purpose |
|------|--------|---------|
| `configure_oggm` | `tools/s2_preprocessing/configure_oggm.py` | Initialize OGGM configuration |
| `init_glacier_directories` | `tools/s2_preprocessing/init_glacier_directories.py` | Create/download GDirs |
| `validate_preprocessing` | `tools/s2_preprocessing/validate_preprocessing.py` | Validate GDir integrity |
