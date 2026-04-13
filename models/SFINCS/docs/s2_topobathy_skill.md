# S2: Topography & Bathymetry — Skill Document

## Purpose

Build SFINCS topography (sfincs.dep), active cell mask (sfincs.msk), and index (sfincs.ind) files from a DEM. The quality of flood simulation depends critically on DEM accuracy and vertical datum consistency.

## Prerequisites

- grid_info.json from s1_domain (mmax, nmax, dx, dy, x0, y0, epsg)
- DEM raster covering the domain:
  - China: `data/dem/china_dem_90m/china_dem_90m.tif` (90m, EGM96)
  - Global: Copernicus GLO-30 (30m, EGM2008) — auto-downloaded by hydrobasin
  - Coastal: GEBCO bathymetry (for underwater topography)

## Inputs

| Input | Type | Source | Required |
|-------|------|--------|----------|
| grid_info.json | JSON | s1_domain | Yes |
| DEM raster | GeoTIFF | Auto-detect or user-specified | Auto |
| Basin shapefile | .shp | Delineation | Optional (for masking) |

## Procedure

1. **Run tool**: `build_sfincs_topobathy.py --grid_info <json> --shp_path <shp> --output_dir <dir>`
   - DEM auto-selects: China DEM for locations in China, otherwise requires user DEM or Copernicus.

2. **Check topobathy_summary.json**:
   - `active_cells > 0` — if zero, CRS mismatch (dt_019)
   - `elevation_min` and `elevation_max` are reasonable for the domain
   - `outflow_cells > 0` — edge cells allow water to exit (dt_007)

3. **Verify vertical datum**:
   - China DEM 90m: EGM96 geoid heights
   - Copernicus GLO-30: EGM2008 (difference from EGM96: < 1m typically)
   - CaMa-Flood sfcelv: relative to geoid (consistent with China DEM)
   - If using tidal BC (coastal): verify datum matches DEM (dt_004)

4. **For coastal domains**: Merge DEM topography with GEBCO bathymetry below sea level.
   The current tool uses land DEM only. For coastal applications, pre-merge using:
   ```python
   merged = np.where(dem > 0, dem, gebco)  # Use GEBCO for underwater areas
   ```

## Expected Outputs

| Output | Path | Size | Verification |
|--------|------|------|-------------|
| sfincs.dep | `{output_dir}/sfincs.dep` | nmax * mmax * 4 bytes | Elevation range correct |
| sfincs.msk | `{output_dir}/sfincs.msk` | nmax * mmax * 1 byte | Active cells > 0 |
| sfincs.ind | `{output_dir}/sfincs.ind` | nmax * mmax * 4 bytes | Sequential indices |
| topobathy_summary.json | `{output_dir}/topobathy_summary.json` | - | Statistics |

## Validation Checks

1. File sizes match: dep = nmax * mmax * 4, msk = nmax * mmax * 1, ind = nmax * mmax * 4
2. Active cells > 0 (mask values > 0)
3. Edge active cells have mask=2 (outflow), not mask=3
4. Elevation range is physically reasonable (not all -9999)
5. No extreme elevation spikes (check max-min < 10000m)

## Common Pitfalls

- **dt_004**: Vertical datum mismatch (EGM96 vs WGS84 ellipsoid = 20-40m offset). For coastal modeling, this is CRITICAL.
- **dt_006**: Grid origin displacement after reprojection. Tool reads from grid_info.json (single source of truth).
- **dt_007**: All edge cells set to mask=3. Tool auto-detects edges and sets to mask=2.
- **dt_019**: Mask all zeros — shapefile CRS does not match grid EPSG.
- **dt_008**: Subgrid ratio > 30x causes artifacts. Keep computational:subgrid ratio at 5-20x.
