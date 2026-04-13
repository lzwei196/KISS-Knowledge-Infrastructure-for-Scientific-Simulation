# Stage 1: Bathymetry Preparation

## Purpose

Prepare bottom topography data for the SWAN computational grid. SWAN requires a regular grid of water depth values (positive downward) in a simple ASCII `.bot` format. This stage converts raw bathymetry from GEBCO, survey data, or other sources into the correct format, resolution, and sign convention.

## Inputs

| Input | Format | Source | Units |
|-------|--------|--------|-------|
| Bathymetry data | NetCDF (GEBCO), ASCII grid, CSV | GEBCO, nautical charts, surveys | m (various conventions) |
| SWAN grid definition | From .swn CGRID command | User-defined | m or degrees |

### SWAN Grid Parameters (from CGRID command)

```
CGRID [xpc] [ypc] [alpc] [xlenc] [ylenc] [mxc] [myc] ...
```

- `xpc`, `ypc`: grid origin coordinates
- `xlenc`, `ylenc`: grid extent
- `mxc`, `myc`: number of cells in x, y
- Grid spacing: `dx = xlenc/mxc`, `dy = ylenc/myc`

### Bathymetry Grid Parameters (from INPGRID command)

```
INPGRID BOTTOM [xpinp] [ypinp] [alpinp] [mxinp] [myinp] [dxinp] [dyinp]
```

The bottom grid can differ from the computational grid. SWAN interpolates internally.

## Outputs

| Output | Format | Location | Description |
|--------|--------|----------|-------------|
| `bathymetry.bot` | ASCII grid | Input directory | Depth values, space-separated |

### .bot File Format

Simple space-separated grid, one row per y-grid line:
```
2.0000  2.0000  2.0000  ...
```

For 1D cases (my=0), a single row suffices.

## Procedure

1. **Obtain source bathymetry**
   - GEBCO: Global, 15 arc-second resolution
   - Local survey: Higher resolution but limited extent

2. **Check sign convention**
   - GEBCO: elevation (positive up, negative = water depth)
   - SWAN needs: depth positive DOWN
   - Conversion: `swan_depth = -gebco_elevation`

3. **Interpolate to SWAN grid**
   - Use bilinear or nearest-neighbor interpolation
   - Handle NaN/land values (set to negative or 0 for dry cells)

4. **Write .bot file**
   ```python
   from ki.tools.convert_bathymetry import convert_bathymetry

   grid = {'xpc': 0, 'ypc': 0, 'dx': 10, 'dy': 10, 'mx': 100, 'my': 50}
   depth_data = {'depth': depth_array, 'lon': lon_array, 'lat': lat_array}
   result = convert_bathymetry(depth_data, grid, 'bathymetry.bot',
                                unit_conversion='elevation_to_depth')
   ```

5. **Verify**
   - Check depth range matches expected values for the area
   - Check grid dimensions match INPGRID specification
   - Visualize with pcolor/imshow

## Verification

- [ ] File exists and is non-empty
- [ ] Number of values = (mx+1) × max(my,1)
- [ ] All depths are positive (for water areas)
- [ ] Depth range is physically reasonable for the domain
- [ ] No unexpected NaN or exception values

```python
import numpy as np
data = np.loadtxt('bathymetry.bot')
print(f"Shape: {data.shape}")
print(f"Depth range: {data.min():.1f} to {data.max():.1f} m")
assert data.min() >= 0, "Negative depths — wrong sign convention!"
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| **Sign convention** | Negative depths in .bot | GEBCO uses elevation (positive up); multiply by -1 |
| **Wrong units** | Depths in fathoms (1 fathom = 1.83 m) | Multiply by 1.8288 |
| **Grid mismatch** | SWAN error: "Bottom grid does not cover" | Check INPGRID extents cover CGRID |
| **Resolution mismatch** | Spurious shoaling/refraction | Bottom grid too coarse for wave features |
| **Land values** | NaN or extreme negative in .bot | Replace with small positive depth or 0 |

## Example

For the 1D flume test cases in the PySWaN repository:
```
# 2.bot — simple uniform depth of 2m
2
  2
```

This corresponds to INPGRID with mx=1, depth values at two x-locations.
