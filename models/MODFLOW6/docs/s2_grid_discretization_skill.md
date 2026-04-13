# Grid & Spatial Discretization — Skill Document

> **Stage ID**: s2_grid_discretization
> **Pipeline order**: 2 of 9
> **Depends on**: s1_installation

## Purpose

Define the 3D finite-difference grid that MODFLOW 6 uses to solve the groundwater flow equation. This determines the spatial resolution and extent of the model. The grid must cover the basin, align with aquifer geometry, and mask out cells outside the model domain. A poorly designed grid causes convergence problems, excessive runtime, or inaccurate results.

## Prerequisites

Before starting this stage, verify:

- [ ] mf6 and FloPy are installed (S1 complete)
- [ ] Basin boundary shapefile exists (from HydroCraft delineation or user-provided)
- [ ] DEM is available for land surface elevation (optional but recommended)
- [ ] Aquifer layer structure is known (number of layers, approximate thicknesses)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| shapefile_path | file | HydroCraft S0 / user | Basin boundary .shp |
| dem_path | file | HydroCraft data | DEM raster for TOP elevation |
| cell_size | number | user decision | Grid cell size in meters (100-5000 typical) |
| nlay | number | user/geology | Number of vertical layers (1-10 typical) |
| layer_bottoms | config | user/geology | Bottom elevation of each layer |
| length_units | string | user | "meters" or "feet" |

## Procedure

### Step 1: Determine Grid Extent and Cell Size

Choose cell size based on basin area and modeling objectives:

| Basin Area | Recommended Cell Size | Approximate Grid |
|------------|----------------------|-------------------|
| < 100 km2 | 100-500 m | 200-2000 cells/layer |
| 100-10,000 km2 | 500-2000 m | 2500-40,000 cells/layer |
| > 10,000 km2 | 1000-5000 m | 1000-10,000 cells/layer |

**Rule**: Grid aspect ratio should not exceed 10:1 (DELR/DELC). Adjacent cells should not differ in size by more than 50%.

### Step 2: Create Grid from Basin

Run the grid creation tool:

```bash
python tools/s2/create_grid_from_basin.py
```

Set input variables in the script:
- `SHAPEFILE_PATH`: path to basin .shp
- `CELL_SIZE`: grid cell size in meters
- `NLAY`: number of layers
- `LAYER_BOTTOMS`: list of bottom elevations relative to surface (negative values)
- `DEM_PATH`: optional DEM raster

**Expected result**: JSON with nlay, nrow, ncol, and IDOMAIN mask.

**If this fails**: Check shapefile CRS (must be projected, not geographic for meter-based cell size). See dt_mf6_005.

### Step 3: Build DIS Package

Run the DIS package builder:

```bash
python tools/s2/build_dis_package.py
```

This creates the MODFLOW 6 DIS (Structured Discretization) package with:
- `NLAY`, `NROW`, `NCOL`: grid dimensions
- `DELR`: row width (cell size in x-direction), array of length NCOL
- `DELC`: column width (cell size in y-direction), array of length NROW
- `TOP`: land surface elevation, 2D array [NROW, NCOL]
- `BOTM`: layer bottom elevations, 3D array [NLAY, NROW, NCOL]
- `IDOMAIN`: active/inactive mask, 3D array [NLAY, NROW, NCOL]
  - 1 = active (solve flow equation)
  - 0 = inactive (excluded from model)
  - -1 = pass-through (vertical connection only)

**Expected result**: DIS package attached to GWF model.

### Step 4: Verify Grid

Check that the grid is correct:

```python
import flopy
sim = flopy.mf6.MFSimulation.load(sim_ws="workspace")
gwf = sim.get_model()
print(f"Grid: {gwf.dis.nlay.data} layers, {gwf.dis.nrow.data} rows, {gwf.dis.ncol.data} cols")
print(f"Active cells: {(gwf.dis.idomain.array > 0).sum()}")
print(f"TOP range: {gwf.dis.top.array.min():.1f} to {gwf.dis.top.array.max():.1f}")
```

**Expected result**: Dimensions match expected values. Active cell count is reasonable for basin area.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| DIS package | `workspace/gwf.dis` | File exists, NLAY/NROW/NCOL correct |
| Grid config | returned JSON | nrow*ncol*cell_size^2 approximately equals basin area |

## Validation Checks

1. **Layer ordering**: BOTM elevations decrease with layer number (deeper layers have lower bottoms)
   - Command: Check `BOTM[k] < BOTM[k-1]` for all k
   - Expected: All layer bottoms are lower than the layer above
   - If unexpected: See dt_mf6_005

2. **TOP > BOTM[0]**: Land surface is above first layer bottom everywhere
   - Expected: TOP > BOTM[0] for all active cells
   - If unexpected: Thin or zero-thickness cells will cause numerical problems

3. **IDOMAIN coverage**: Active cells cover the basin
   - Expected: Active cell count * cell_area is close to basin area
   - If unexpected: Shapefile intersection may be wrong

4. **Cell aspect ratio**: DELR and DELC values do not differ by more than 10x
   - Expected: max(DELR)/min(DELC) < 10
   - If unexpected: Refine grid or use variable spacing

## Common Pitfalls

> **PITFALL**: Using geographic coordinates (degrees) for cell size
> If the shapefile is in WGS84 (lat/lon), cell size in "meters" will be nonsensical. MODFLOW expects length units (meters or feet), not degrees.
> **Do this instead**: Reproject the shapefile to a projected CRS (e.g., UTM) or compute DELR/DELC from degree spacing at the basin latitude.
> See diagnostic triplet dt_mf6_005.

> **PITFALL**: Forgetting IDOMAIN for irregularly shaped basins
> If IDOMAIN is all 1s, MODFLOW will compute flow in cells outside the basin. These cells have no physical meaning and can cause convergence issues.
> **Do this instead**: Always set IDOMAIN=0 for cells outside the basin boundary.
> See diagnostic triplet dt_mf6_014.

> **PITFALL**: Zero-thickness layers
> If TOP equals BOTM[0] for any cell, that cell has zero thickness. MODFLOW will issue a warning but may produce NaN heads.
> **Do this instead**: Ensure minimum layer thickness of 1 m.

---

*This skill document is part of the modflow6-knowledge-infrastructure package.*
*Stage 2 of 9 | Tools used: create_grid_from_basin, build_dis_package | Related triplets: dt_mf6_005, dt_mf6_014*
