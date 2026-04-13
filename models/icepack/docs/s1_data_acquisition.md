# Stage 1: Data Acquisition and Forcing Conversion

## Purpose

Fetch observed velocity, ice thickness, bed elevation, and surface elevation data
from remote sensing archives (NSIDC, BedMachine, MEaSUREs), convert units to
icepack's internal system (MPa, meters, years), and prepare raster files for
interpolation onto the FEM mesh.

## Inputs

| Input | Source | Format | Native Unit |
|-------|--------|--------|-------------|
| Ice velocity (vx, vy) | MEaSUREs NSIDC-0754 (Antarctica) / NSIDC-0478 (Greenland) | GeoTIFF/NetCDF | m/yr |
| Ice thickness | BedMachine NSIDC-0756 (Antarctica) / IDBMG4 (Greenland) | NetCDF | m |
| Bed elevation | BedMachine | NetCDF | m |
| Surface elevation | BedMachine | NetCDF | m |
| Glacier outline | icepack glacier-meshes repo | GeoJSON | — |
| RGI outlines | NSIDC-0770 (RGI v7.0) | Shapefile | — |

## Outputs

| Output | Format | icepack Unit | Description |
|--------|--------|-------------|-------------|
| vx_myr.tif | GeoTIFF | m/yr | x-component velocity |
| vy_myr.tif | GeoTIFF | m/yr | y-component velocity |
| thickness_m.tif | GeoTIFF | m | Ice thickness (≥ min_thickness) |
| bed_m.tif | GeoTIFF | m | Bed elevation |
| surface_m.tif | GeoTIFF | m | Surface elevation (hydrostatic-consistent) |

## Procedure

1. **Fetch data** using `icepack.datasets`:
   ```python
   velocity_file = icepack.datasets.fetch_measures_antarctica()
   thickness_file = icepack.datasets.fetch_bedmachine_antarctica()
   outline_file = icepack.datasets.fetch_outline("larsen-2019")
   ```

2. **Open rasters** with rasterio or xarray:
   ```python
   import rasterio
   vx_dataset = rasterio.open(velocity_file)  # if multi-band
   ```

3. **Convert velocity units** if necessary:
   - MEaSUREs: already in m/yr (no conversion needed for Antarctic)
   - If in m/s: multiply by 3.15576×10⁷ (seconds per year)
   - If in m/day: multiply by 365.25

4. **Validate thickness**: enforce minimum thickness (default 10 m) to avoid
   solver singularities. Set zero-thickness areas to NaN.

5. **Compute surface elevation** from thickness + bed:
   ```python
   s = max(h + b, (1 - ρ_ice/ρ_water) * h)
   ```
   This ensures floating ice satisfies hydrostatic balance.

6. **Check coordinate reference system**: icepack requires projected coordinates
   (meters), not geographic (lat/lon). Antarctic data typically uses EPSG:3031
   (Antarctic Polar Stereographic).

## Verification

- [ ] Velocity magnitude range: 0–4000 m/yr (typical for Antarctic ice streams)
- [ ] Thickness > 0 everywhere on active mesh
- [ ] Surface ≥ (1 − ρ_i/ρ_w) × thickness (flotation criterion)
- [ ] CRS is projected (units = meters), not geographic
- [ ] No NaN values inside glacier boundary
- [ ] Raster extent covers the glacier outline

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Velocity in m/s not m/yr | Velocities ~10⁻⁸ range, solver stalls | × 3.15576e7 |
| Missing EarthData login | Download fails silently | Run `earthaccess.login()` first |
| Geographic CRS (lat/lon) | Mesh coordinates wrong scale | Reproject to polar stereographic |
| Zero thickness on mesh | Division by zero in solver | Set min_thickness = 10 m |
| Data gaps inside domain | NaN → solver failure | Fill/interpolate before meshing |

## Example

```python
import icepack.datasets

# Fetch data (requires NASA EarthData account)
velocity = icepack.datasets.fetch_measures_antarctica()
bedmachine = icepack.datasets.fetch_bedmachine_antarctica()
outline = icepack.datasets.fetch_outline("pine-island")

# Open and inspect
import rasterio
vx = rasterio.open(velocity)
print(f"Velocity CRS: {vx.crs}, Resolution: {vx.res}")
```
