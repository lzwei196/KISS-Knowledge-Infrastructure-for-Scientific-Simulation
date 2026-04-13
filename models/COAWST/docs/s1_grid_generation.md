# S1: Grid Generation

## Purpose
Create the ROMS computational grid NetCDF file containing bathymetry, land/sea masks, coordinate metrics, Coriolis parameter, and grid angles. This grid is the foundation for all COAWST components — ocean (ROMS), waves (SWAN), and atmosphere (WRF) all depend on it for coupling.

## Inputs
| Input               | Format     | Source                    | Notes                           |
|---------------------|------------|---------------------------|---------------------------------|
| Bathymetry          | NetCDF     | GEBCO, ETOPO, SRTM30+    | Must cover domain + buffer      |
| Coastline (opt.)    | Shapefile  | GSHHS                    | For mask refinement             |
| Domain bounds       | Parameters | User                      | lon/lat range, resolution       |
| Smoothing parameter | Parameter  | User                      | rx0 max (typ. 0.2–0.4)         |
| Minimum depth       | Parameter  | User                      | Typically 5–10 m                |

## Outputs
| Output           | Format  | Key Variables                                        |
|------------------|---------|------------------------------------------------------|
| ROMS grid file   | NetCDF  | lon_rho, lat_rho, h, mask_rho, pm, pn, f, angle     |
|                  |         | lon_u, lat_u, mask_u (u-point staggering)            |
|                  |         | lon_v, lat_v, mask_v (v-point staggering)            |
|                  |         | lon_psi, lat_psi, mask_psi (psi-point staggering)    |

## Procedure

1. **Select domain**: Choose lon/lat bounds that include a buffer zone (typically 1° beyond region of interest) to accommodate open boundary sponge layers.

2. **Download bathymetry**: Obtain GEBCO_2023 or ETOPO2022 at highest available resolution. Ensure full coverage of domain.

3. **Run grid generator**:
   ```bash
   python3 ki/tools/convert_grid.py \
     --bathymetry gebco_2023.nc --bathy-format gebco \
     --lon-range -77 -69 --lat-range 35 43 \
     --resolution 0.01 --output sandy_grid.nc \
     --smooth-factor 0.2 --min-depth 5.0
   ```

4. **Verify grid**: Check that output contains all required variables and dimensions match expectations.

## Verification
- Open grid in ncview/Panoply and verify bathymetry looks correct
- Check `h` values are **positive** (depth below MSL)
- Verify `mask_rho`: 1 = water, 0 = land — coastline should match reality
- Check rx0 (Beckmann-Haidvogel number): `|Δh| / (h₁ + h₂)` should be < 0.2 everywhere
- Verify `pm` and `pn` are reasonable (should be ~1/(grid spacing in meters))
- Check `f` (Coriolis) matches latitude range

## Traps

**dt_007: Bathymetry sign convention.**
GEBCO and ETOPO use **negative values for ocean depths**. ROMS requires `h > 0` (positive down from MSL). If you forget to negate, the entire grid will be "above water" and ROMS will crash immediately or produce nonsense. The `convert_grid.py` tool handles this automatically for gebco/etopo formats.

**dt_009: Arakawa C-grid staggering.**
Boundary condition files must match the correct stagger point. If ρ-grid is Lm+2 × Mm+2, then u-grid is (Lm+1) × (Mm+2) and v-grid is (Lm+2) × (Mm+1). Providing boundary data on the wrong stagger creates subtle errors at domain edges.

**Grid too coarse for features.**
If grid resolution is larger than key bathymetric features (channels, headlands), the model will miss important dynamics. Rule of thumb: ≥5 grid cells across any feature you want to resolve.

## Example
For Hurricane Sandy (US East Coast):
```bash
# ~1 km resolution grid from GEBCO
python3 ki/tools/convert_grid.py \
  --bathymetry /data/GEBCO_2023.nc --bathy-format gebco \
  --lon-range -77.0 -69.0 --lat-range 35.0 43.0 \
  --resolution 0.01 --output Sandy_roms_grid.nc \
  --smooth-factor 0.2 --min-depth 5.0
# Expected: ~800×800 grid, depths 5–5000 m
```
