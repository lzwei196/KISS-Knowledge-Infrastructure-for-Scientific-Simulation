# S0: Grid Generation

## Purpose

Create a ROMS-compatible grid NetCDF file that defines the computational domain,
including bathymetry, coordinate metrics, land/sea masking, and Coriolis parameter.
The grid file is the foundation for all subsequent ROMS operations — every forcing,
initial condition, and boundary file must conform to it.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| Domain extent | lon/lat bounds | West, East, South, North in degrees |
| Resolution | degrees or meters | Grid spacing |
| Bathymetry source | NetCDF (ETOPO1, GEBCO, SRTM15+) | Global or regional depth data |
| Coastline | Optional shapefile | For manual mask refinement |

## Outputs

| Output | Format | Variables |
|--------|--------|-----------|
| `roms_grid.nc` | NetCDF | h, pm, pn, lon_rho, lat_rho, mask_rho, mask_u, mask_v, angle, f |

## Procedure

### Step 1: Define coordinate arrays
Create 1D longitude and latitude arrays at the desired resolution. Use `np.meshgrid`
to generate 2D RHO-point coordinate arrays (lon_rho, lat_rho).

### Step 2: Interpolate bathymetry
Load source bathymetry (e.g., ETOPO1) and bilinearly interpolate onto the ROMS grid.
Ensure the result is positive (depth below sea level). Apply minimum depth clamp
(`hmin`, typically 5–10 m) and maximum depth clamp (`hmax`).

### Step 3: Smooth bathymetry
The r-factor (slope parameter) should satisfy:
```
r = |h(i+1) - h(i)| / (h(i+1) + h(i)) < 0.2
```
Excessive bathymetric gradients cause pressure gradient errors. Apply Shapiro or
Hanning filters iteratively until r < 0.2.

### Step 4: Compute grid metrics
For spherical grids:
```
dx = R * cos(lat) * dlon
dy = R * dlat
pm = 1 / dx   (units: 1/meters)
pn = 1 / dy   (units: 1/meters)
```

**TRAP:** pm and pn are INVERSE spacing (1/meters), NOT meters. Getting this wrong
causes CFL violations or unrealistic diffusion.

### Step 5: Compute Coriolis parameter
```
f = 2 * omega * sin(lat)
```
where omega = 7.2921e-5 rad/s.

### Step 6: Build land/sea mask
- `mask_rho` = 1 for water, 0 for land (at RHO-points)
- `mask_u` = mask_rho[:, :-1] * mask_rho[:, 1:]  (at U-points)
- `mask_v` = mask_rho[:-1, :] * mask_rho[1:, :]  (at V-points)

### Step 7: Write and validate
Write all variables to NetCDF. Run validation checks:
- h > 0 everywhere in water
- pm, pn > 0 everywhere
- mask values are 0 or 1 only
- r-factor < 0.2

## Verification

```bash
# Check grid file structure
ncdump -h roms_grid.nc

# Verify bathymetry range
python -c "
from netCDF4 import Dataset
ds = Dataset('roms_grid.nc')
h = ds.variables['h'][:]
print(f'Depth range: {h.min():.1f} to {h.max():.1f} m')
print(f'Water points: {(ds.variables[\"mask_rho\"][:] == 1).sum()}')
ds.close()
"

# Check r-factor
python -c "
import numpy as np
from netCDF4 import Dataset
ds = Dataset('roms_grid.nc')
h = ds.variables['h'][:]
rx = np.abs(np.diff(h, axis=1)) / (h[:, :-1] + h[:, 1:])
ry = np.abs(np.diff(h, axis=0)) / (h[:-1, :] + h[1:, :])
print(f'Max r-factor (xi): {rx.max():.4f}')
print(f'Max r-factor (eta): {ry.max():.4f}')
ds.close()
"
```

## Traps

| Trap | Description | Consequence |
|------|-------------|-------------|
| Negative bathymetry | h < 0 | Model crash or all land |
| pm/pn in meters | Should be 1/meters | CFL blow-up |
| No bathymetry smoothing | r-factor > 0.2 | Pressure gradient errors |
| Wrong mask convention | 0/1 swapped | Land treated as ocean |
| Grid too coarse near coast | Unresolved features | Poor coastal dynamics |

## Example

```bash
python tools/build_roms_grid.py \
  --bathymetry /data/ETOPO1_Bed_g_gmt4.grd \
  --lon-range -76.0 -70.0 \
  --lat-range 35.0 42.0 \
  --resolution 0.02 \
  --output roms_grid.nc \
  --hmin 5.0 --hmax 5000.0
```
