# Watershed Delineation — Skill Document

> **Stage ID**: s1_watershed_delineation
> **Pipeline order**: 1 of 9
> **Depends on**: none

## Purpose

Watershed delineation is the spatial foundation of every SWAT+ model. It defines the watershed boundary, subbasin divisions, and stream network from a DEM. All subsequent steps (HRU definition, weather station assignment, routing) depend on the spatial framework created here. Skipping or misconfiguring this stage invalidates the entire model.

SWAT+ does not require ArcGIS — delineation can be done with QSWAT+ (QGIS plugin), WhiteboxTools (CLI/Python), or pysheds. The result is a set of shapefiles and connectivity files that SWAT+ reads as text input.

## Prerequisites

Before starting this stage, verify:

- [ ] DEM raster exists covering the target basin plus a buffer (at least 10 km beyond expected watershed boundary)
- [ ] DEM is in a projected coordinate system with units in meters (e.g., UTM). Geographic coordinates (lat/lon in degrees) cause wrong slope and area calculations.
- [ ] Outlet coordinates (lat/lon) are known and located on the target river (not a tributary or larger river)
- [ ] Python environment with WhiteboxTools, geopandas, rasterio, and pyproj installed

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| DEM raster | file | SRTM, ASTER, Copernicus GLO-30, local survey | Digital elevation model (GeoTIFF) |
| Outlet lat/lon | value | User or gauging station coordinates | Basin outlet location in decimal degrees |
| Stream threshold | value | User choice or default 25 km2 | Minimum upstream area to define a stream |
| Output directory | directory | User choice | Where to write output files |

## Procedure

Follow these steps in exact order. Do not skip, reorder, or improvise.

### Step 1: Clip and project the DEM

Clip the DEM to the basin extent plus a generous buffer (2-5 degrees beyond the expected watershed boundary). Reproject to an appropriate UTM zone if the DEM is in geographic coordinates.

```bash
python tools/s1/delineate_watershed.py
```

Set `dem_path`, `outlet_lat`, `outlet_lon`, `stream_threshold`, `output_dir` in the script configuration before running.

**Expected result**: Clipped, projected DEM raster in the output directory.

**If this fails**: Check that the DEM file exists and is a valid raster. Verify the outlet coordinates are within the DEM extent.

### Step 2: Fill pits / breach depressions

The DEM must be hydrologically conditioned — all cells must have a drainage path to the outlet. Use breach depressions (preferred over fill) to maintain realistic channel gradients.

**Expected result**: Pit-filled/breached DEM raster with no flat areas or sinks.

### Step 3: Compute flow direction and accumulation

D8 flow direction assigns each cell to one of 8 neighbors based on steepest descent. Flow accumulation counts upstream cells draining through each cell.

**Expected result**: Flow direction and flow accumulation rasters.

### Step 4: Define stream network

Apply the stream threshold to the flow accumulation raster. Cells with accumulation above the threshold become stream cells.

**Expected result**: Stream network raster and vectorized stream shapefile. Verify stream pattern matches known river network.

### Step 5: Snap outlet and delineate watershed

Snap the outlet point to the nearest high-accumulation stream cell (search radius ~0.15 degrees or ~1 km). Then trace all cells draining to this point to define the watershed boundary.

**Expected result**: Watershed boundary shapefile. Check that the area matches expected basin area within 10%.

**If this fails**: See diagnostic triplet dt_008. The outlet may have snapped to the wrong stream.

### Step 6: Define subbasins

Split the watershed into subbasins at stream junctions. Each subbasin drains to a unique channel reach.

**Expected result**: Subbasin shapefile with unique IDs. Typical: 10-100 subbasins for a medium basin.

### Step 7: Generate SWAT+ connectivity files

Run `define_subbasins` to generate chandeg.con (channel connectivity), rout_unit.con (routing unit connectivity), and related spatial definition files.

```bash
python tools/s1/define_subbasins.py
```

**Expected result**: Connectivity files in TxtInOut format.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Watershed boundary | `{output_dir}/watershed.shp` | Area within 10% of expected; boundary does not extend into neighboring watersheds |
| Subbasin shapefile | `{output_dir}/subbasins.shp` | 10-100 subbasins; total area = watershed area |
| Stream network | `{output_dir}/streams.shp` | Connected network reaching outlet; matches known river channels |
| chandeg.con | `{output_dir}/chandeg.con` | All channels connected to outlet |
| rout_unit.con | `{output_dir}/rout_unit.con` | One routing unit per subbasin |

## Validation Checks

1. **Watershed area**: Compare delineated area to known/published area. If >20% different, the outlet is likely on the wrong stream.
   - Command: `python -c "import geopandas as gpd; g=gpd.read_file('watershed.shp'); print(f'Area: {g.to_crs(epsg=6933).area.sum()/1e6:.0f} km2')"`
   - Expected: Within 10% of published area
   - If unexpected: See diagnostic triplet dt_008

2. **Stream network connectivity**: All streams must connect to the outlet. No orphan stream segments.
   - Visual inspection of stream shapefile overlaid on DEM

3. **Subbasin count**: Should be 10-100 for typical basins. <5 is too coarse, >500 is unnecessarily fine.

## Common Pitfalls

> **PITFALL**: Outlet placed on wrong stream (snaps to larger river at confluence)
> This happens when the outlet coordinates are near a confluence of the target river with a larger river. The snapping algorithm selects the higher-accumulation cell, which may be on the larger river. This delineates the entire upstream mega-basin.
> **Do this instead**: Place the outlet upstream of the confluence, or manually specify the snapped coordinates.
> See diagnostic triplet dt_008 for full details.

> **PITFALL**: DEM in geographic coordinates (degrees instead of meters)
> If the DEM is in lat/lon, slope calculations use degrees as units, producing absurdly small slopes. Area calculations are also wrong.
> **Do this instead**: Reproject to UTM before processing. WhiteboxTools can handle this, but verify the output.

> **PITFALL**: Stream threshold too small for basin size
> A 1 km2 threshold on a 100,000 km2 basin creates thousands of subbasins and extremely slow execution.
> **Do this instead**: Use approximately area/1000 as the threshold (e.g., 100 km2 for a 100,000 km2 basin).

---

*This skill document is part of the SWAT+ knowledge infrastructure.*
*Stage 1 of 9 | Tools used: delineate_watershed, define_subbasins | Related triplets: dt_008*
