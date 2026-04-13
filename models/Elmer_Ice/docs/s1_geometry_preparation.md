# S1: Geometry Preparation

## Purpose

Prepare bedrock topography, ice surface elevation, and ice thickness data
for Elmer/Ice mesh construction and initial conditions. This is the foundation
of any ice dynamics simulation — errors here propagate through all downstream stages.

## Inputs

| Input | Source | Format | Units |
|-------|--------|--------|-------|
| Bed topography | BedMachine v5, BEDMAP2 | NetCDF / GeoTIFF | meters above sea level |
| Surface elevation | ArcticDEM, REMA, CryoSat-2 | NetCDF / GeoTIFF | meters above sea level |
| Ice thickness | BedMachine v5, radar surveys | NetCDF / GeoTIFF | meters |
| Ice mask | BedMachine, MEaSUREs | NetCDF | binary (0/1) |

## Outputs

| Output | Format | Units | Description |
|--------|--------|-------|-------------|
| `zb_nodes.dat` | ASCII (node_id value) | m | Bed elevation at each mesh node |
| `zs_nodes.dat` | ASCII (node_id value) | m | Surface elevation at each mesh node |
| `h_nodes.dat` | ASCII (node_id value) | m | Ice thickness at each mesh node |
| `depth_nodes.dat` | ASCII (node_id value) | m | Depth below surface at each node |

## Procedure

1. **Obtain DEMs**: Download BedMachine v5 from NSIDC for Greenland/Antarctica,
   or use local radar surveys for mountain glaciers.

2. **Reproject to meters**: Elmer requires all coordinates in meters.
   Use a polar stereographic projection (EPSG:3413 for Greenland, EPSG:3031 for Antarctica).
   ```bash
   gdalwarp -t_srs EPSG:3413 -r bilinear bed.tif bed_proj.tif
   ```

3. **Clip to domain**: Extract the region of interest.
   ```bash
   gdalwarp -te xmin ymin xmax ymax bed_proj.tif bed_clipped.tif
   ```

4. **Run convert_geometry.py**:
   ```bash
   python convert_geometry.py --bed bed.nc --surface surface.nc \
       --thickness thickness.nc --mesh_dir ./rectangle \
       --output_dir ./geometry --variable_bed bed
   ```

5. **Verify consistency**: H = Zs - Zb everywhere. Check that H >= 0.

## Verification

- `h_nodes.dat` should have no negative values
- `zs_nodes.dat` values should be consistent with `zb_nodes.dat + h_nodes.dat`
- Coordinate magnitudes should be in meters (thousands to millions), not km
- For Greenland: typical bed -500 to 3000 m, surface 0 to 3200 m, H 0 to 3400 m
- For alpine glaciers: bed 1500-4000 m, H 50-500 m

## Traps

| Trap | Effect | Prevention |
|------|--------|-----------|
| **Coordinates in km** (dt_008) | Gravity term 1000x wrong | Check mesh.nodes max values > 1000 |
| **Mixed projections** | Geometry artifacts | Use single CRS throughout |
| **NaN in bed DEM** | Holes in mesh | Fill NaN before interpolation |
| **Ice thickness < 0** | Non-physical solution | Clamp H to max(0, Zs-Zb) |

## Example

```bash
# Synthetic test case (no external data needed)
python convert_geometry.py --synthetic ismip --mesh_dir ./rectangle \
    --output_dir ./geometry

# Real Greenland data
python convert_geometry.py --bed BedMachineGreenland-v5.nc \
    --surface ArcticDEM_mosaic.nc --mesh_dir ./greenland_mesh \
    --output_dir ./geometry --variable_bed bed --variable_surface surface
```
