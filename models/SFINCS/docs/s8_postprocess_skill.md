# S8: Post-Processing — Skill Document

## Purpose

Extract flood results from SFINCS NetCDF output, compute flood statistics, generate GeoTIFF rasters and publication-quality flood maps.

## Prerequisites

- sfincs_map.nc from s7_execution
- grid_info.json for georeferencing
- Optional: sfincs_his.nc for time series at observation points

## Inputs

| Input | Type | Required |
|-------|------|----------|
| sfincs_map.nc | NetCDF | Yes |
| sfincs_his.nc | NetCDF | Optional |
| grid_info.json | JSON | Recommended |
| Basin shapefile | .shp | Optional (for map overlay) |

## Procedure

1. **Extract results**: `extract_sfincs_results.py --map_nc <nc> --grid_info <json> --output_dir <dir>`
   - Reads maximum water depth from sfincs_map.nc
   - Computes flood extent (threshold: 5cm minimum)
   - Classifies depth into 4 classes: 0-0.3m, 0.3-1m, 1-3m, >3m
   - Computes flood volume, flooded area, depth statistics
   - Exports GeoTIFF (flood_max_depth.tif, flood_extent.tif)

2. **Generate flood map**: `plot_sfincs_flood_map.py --flood_depth <tif_or_npy> --grid_info <json> --title <title> --output <png>`
   - 7-class depth colormap (yellow to navy)
   - Basin boundary overlay
   - Statistics annotation
   - Publication quality (200 DPI)

3. **Flood depth classification** (standard hazard categories):

| Class | Depth | Hazard | Impact |
|-------|-------|--------|--------|
| Very shallow | <0.1m | Low | Ankle depth, road ponding |
| Shallow | 0.1-0.3m | Moderate | Knee depth, vehicle stalling |
| Moderate | 0.3-1.0m | High | Waist-chest, building damage begins |
| Deep | 1.0-3.0m | Very high | Above head, structural damage |
| Extreme | >3.0m | Severe | Building collapse risk |

4. **Validation against other sources**:
   - Compare flood extent with CaMa-Flood 1-arcmin downscaled output
   - Compare with satellite imagery (Sentinel-1 SAR) if available
   - Critical Success Index (CSI) = TP / (TP + FP + FN)
   - Target CSI > 0.5 for a good match

## Expected Outputs

| Output | Path | Verification |
|--------|------|-------------|
| flood_stats.json | `{output_dir}/flood_stats.json` | Contains area, depth, volume |
| flood_max_depth.tif | `{output_dir}/flood_max_depth.tif` | Georeferenced depth raster |
| flood_extent.tif | `{output_dir}/flood_extent.tif` | Binary flood/no-flood raster |
| flood_max_depth.npy | `{output_dir}/flood_max_depth.npy` | NumPy array for plotting |
| flood_map.png | User-specified | Publication-quality map |
| timeseries.csv | `{output_dir}/timeseries.csv` | If obs points defined |

## Validation Checks

1. Flooded area is reasonable for the event magnitude
2. Maximum depth < 20m (if > 20m, check forcing units — dt_001)
3. Flood extent does not extend beyond basin boundary (if it does, check outflow mask — dt_007)
4. Total flood volume is consistent with precipitation input minus infiltration

## Common Pitfalls

- Output all zeros: mask had no active cells (dt_019) or no forcing was applied
- Max depth unrealistically high: precipitation units wrong (dt_001)
- Flood at domain edges: outflow boundary cells not set (dt_007)
- GeoTIFF displaced: grid origin mismatch (dt_006)
