# Stage 2: Bathymetry Preparation

## Purpose

Prepare bottom elevation / water depth data for the Delft3D model domain.
Bathymetry is the single most important geometric input — errors here affect
water level, flow patterns, tidal propagation, and sediment transport.

## Inputs

| Input | Format | Source | Resolution |
|-------|--------|--------|------------|
| GEBCO 2023 | NetCDF (.nc) | gebco.net | ~450 m global |
| ETOPO 2022 | NetCDF (.nc) | NOAA NCEI | ~450 m global |
| Survey data | XYZ / ASCII | Hydrographic surveys | Variable |
| Grid file | _net.nc / .grd | From Stage 1 | Model resolution |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Depth file (structured) | .dep | Grid-aligned depth values |
| Depth samples (unstructured) | .xyz or embedded in _net.nc | XYZ point cloud for interpolation |

## Procedure

1. **Download bathymetry** from GEBCO or ETOPO (subset to domain + buffer)
2. **Check sign convention**:
   - GEBCO: elevation positive UP (ocean depths are negative)
   - Delft3D: depth positive DOWN (by default for bed level in _net.nc)
   - **Negate** GEBCO values: `depth_delft3d = -elevation_gebco`
3. **Interpolate to grid** using nearest-neighbor or linear interpolation
4. **Clip land cells**: set depth to minimum value (e.g., 0.1 m) or mark as dry
5. **Smooth transitions**: avoid abrupt depth jumps between adjacent cells
6. **Merge survey data**: replace global bathymetry with local survey where available

```bash
python ki/tools/convert_bathymetry.py \
  --bathymetry_file GEBCO_2023.nc \
  --grid_file domain_net.nc \
  --output bathymetry.xyz \
  --negate_depth \
  --min_depth 0.1
```

## Verification

- **Range check**: ocean depths typically 0–11,000 m; shelf < 200 m; estuary < 50 m
- **No negative depths** in water areas (after sign conversion)
- **Smooth gradients**: no single-cell spikes (> 3× neighbor depth)
- **Cross-check**: compare depth at known locations (e.g., nautical charts)
- **Volume conservation**: total domain water volume should be reasonable

```python
import netCDF4 as nc
ds = nc.Dataset("domain_net.nc")
z = ds.variables["NetNode_z"][:]
print(f"Depth range: [{z.min():.1f}, {z.max():.1f}] m")
print(f"Mean depth: {z.mean():.1f} m")
print(f"Negative depths (land): {(z < 0).sum()}")
ds.close()
```

## Traps

1. **Sign convention trap (CRITICAL — dt_001)**: GEBCO elevation is positive UP;
   Delft3D depth is positive DOWN. If you forget to negate, the model will treat
   ocean floor as mountains above sea level. The simulation may crash immediately
   (all cells dry) or produce completely wrong flow patterns.

2. **Datum mismatch**: GEBCO uses mean sea level (MSL). If your tidal boundary
   uses a different datum (chart datum, local datum), you need a datum offset.
   A 0.5 m datum error can significantly affect intertidal areas.

3. **Resolution mismatch**: GEBCO at ~450 m cannot resolve narrow channels,
   tidal flats, or harbor basins. Always use local survey data for detailed areas.

4. **Land masking**: Cells with zero or negative depth must be properly marked
   as dry points or given a minimum depth. Unmasked land cells cause volume
   errors and can destabilize the simulation.

## Example

```python
# Quick check of bathymetry after conversion
import numpy as np
data = np.loadtxt("bathymetry.xyz")
x, y, depth = data[:, 0], data[:, 1], data[:, 2]

print(f"Points: {len(depth)}")
print(f"Depth range: [{depth.min():.1f}, {depth.max():.1f}] m")
print(f"Water cells (depth > 0): {(depth > 0).sum()}")
print(f"Land cells (depth <= 0): {(depth <= 0).sum()}")

# Check for sign convention: ocean should have positive depths
if depth.mean() < -10:
    print("WARNING: Mean depth is negative — did you forget --negate_depth?")
```
