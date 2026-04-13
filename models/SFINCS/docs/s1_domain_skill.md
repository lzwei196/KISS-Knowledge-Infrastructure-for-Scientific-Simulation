# S1: Domain Setup — Skill Document

## Purpose

Define the SFINCS computational grid from a basin shapefile or bounding box. This stage determines the spatial extent, resolution, and coordinate reference system for the entire simulation. All subsequent stages depend on the grid definition.

## Prerequisites

- Basin boundary shapefile (from HydroCraft delineation) OR bounding box coordinates
- Knowledge of flood domain size (determines resolution choice)
- Python venv activated

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| Basin shapefile | .shp | Basin delineation (Step 0) or `data/shp/` | Yes (or bbox) |
| Bounding box | string | User-provided xmin,ymin,xmax,ymax (WGS84) | Yes (or shp) |
| Resolution | number | User choice (meters) | No (default: 100m) |
| EPSG code | number | Auto-detect UTM | No |
| Buffer | number | Buffer around basin (meters) | No (default: 500m) |

## Procedure

1. **Choose resolution based on domain size**:
   - Domain < 1 km: dx = 10-25m (urban flood)
   - Domain 1-10 km: dx = 25-50m (village/small town)
   - Domain 10-50 km: dx = 50-100m (river reach)
   - Domain > 50 km: dx = 100-200m (large floodplain)
   - NEVER use dx < 10m unless you need street-level resolution AND have high-res DEM

2. **Run tool**: `setup_sfincs_domain.py --shp_path <shp> --resolution <dx> --output_dir <dir>`
   - If no shapefile: `--bbox "116.0,40.0,117.5,41.5"`

3. **Check grid_info.json**:
   - `total_cells` < 2,000,000 (manageable runtime)
   - `epsg` is a UTM zone (326xx or 327xx), NOT 4326
   - `dt_recommended` is > 0.5s (if < 0.5, resolution is too fine)

4. **If total_cells > 2,000,000**: Increase resolution or reduce domain extent
   If running on CPU with 4 cores, aim for < 500,000 active cells.

## Expected Outputs

| Output | Path | Verification |
|--------|------|-------------|
| grid_info.json | `{output_dir}/grid_info.json` | Contains mmax, nmax, dx, dy, epsg, total_cells |
| grid_snippet.inp | `{output_dir}/grid_snippet.inp` | Valid sfincs.inp grid parameters |

## Validation Checks

1. `mmax > 0` and `nmax > 0`
2. `epsg` is a projected CRS (not 4326). If dt_005 occurs, re-run with explicit `--epsg`.
3. `total_cells` is reasonable for the domain size
4. `dt_recommended > 0.5s`

## Common Pitfalls

- **dt_005**: Using EPSG:4326 (geographic) with metric dx/dy. Tool auto-detects UTM, but verify.
- **dt_011**: Resolution too fine for domain. 10m on a 100km domain = 100 million cells = days of runtime.
- Buffer too small: flooding may reach domain edge and bounce back. Use at least 500m.
