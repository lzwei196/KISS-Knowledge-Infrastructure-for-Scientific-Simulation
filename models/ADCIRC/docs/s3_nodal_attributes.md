# S3: Nodal Attributes (fort.13)

## Purpose

Define spatially varying physical parameters across the mesh domain. Without fort.13, ADCIRC uses uniform values from fort.15. Nodal attributes allow realistic spatial variation in bottom friction, surface roughness, and other properties critical for accurate storm surge and tidal simulation.

## Inputs

| Input | Source | Format | Description |
|-------|--------|--------|-------------|
| Land cover | NLCD, GlobCover | GeoTIFF/netCDF | Land use classification |
| Bathymetry | fort.14 | ADCIRC mesh | Depth at each node for classification |
| Soil/substrate | HWSD, local surveys | Shapefile/raster | Seabed type for friction |
| Levee database | USACE NLD | Shapefile | Levee crest elevations |

## Outputs

| Output | File | Format | Description |
|--------|------|--------|-------------|
| Nodal attributes | `fort.13` | ASCII | Per-node parameter values |

## Procedure

### 1. Choose Attributes

Common nodal attributes:

| Attribute Name | Values/Node | Unit | Description |
|---------------|-------------|------|-------------|
| `mannings_n_at_sea_floor` | 1 | s/m^(1/3) | Manning's friction coefficient |
| `primitive_weighting_in_continuity_equation` | 1 | — | TAU0 spatial variation |
| `quadratic_friction_coefficient_at_sea_floor` | 1 | — | Quadratic Cf |
| `surface_directional_effective_roughness_length` | 12 | m | Directional z0 (wind sheltering) |
| `surface_canopy_coefficient` | 1 | — | Wind reduction under canopy |
| `elemental_slope_limiter` | 1 | — | Controls local slope limiting |
| `sea_surface_height_above_geoid` | 1 | m | Geoid-to-MSL offset |

### 2. Assign Manning's n by Land Cover

| Land Type | Manning's n | Notes |
|-----------|------------|-------|
| Deep ocean (>200m) | 0.020 | Smooth seabed |
| Continental shelf (10-200m) | 0.022-0.025 | Sandy/muddy bottom |
| Shallow coastal (2-10m) | 0.030-0.040 | Mixed substrate |
| Marsh/wetland | 0.080-0.120 | Dense vegetation |
| Forest | 0.100-0.160 | Trees and undergrowth |
| Urban/developed | 0.050-0.080 | Buildings and pavement |
| Bare land | 0.025-0.035 | Open terrain |

### 3. Write fort.13

```
ADCIRC_MESH                          ! Grid name (must match fort.14)
23456                                ! Number of nodes
2                                    ! Number of attributes
mannings_n_at_sea_floor              ! Attribute 1 name
s/m^(1/3)                           ! Units
1                                    ! Values per node
0.025000                             ! Default value
mannings_n_at_sea_floor              ! Attribute name again
1245                                 ! Number of non-default nodes
    1   0.080000                     ! Node 1: marsh
    2   0.035000                     ! Node 2: shallow coastal
    ...
surface_canopy_coefficient           ! Attribute 2 name
1                                    ! Units (dimensionless)
1                                    ! Values per node
1.000000                             ! Default (no canopy reduction)
surface_canopy_coefficient
567
    100  0.500000                    ! Node 100: 50% wind reduction under canopy
    ...
```

### 4. Set NWP in fort.15

Fort.15 must list the attribute names used:
```
2                                    ! NWP (number of nodal attribute names)
mannings_n_at_sea_floor
surface_canopy_coefficient
```

## Verification

```bash
# Check attribute count matches fort.15 NWP
grep -c "^mannings_n" fort.13

# Verify Manning's n range (should be 0.01-0.20)
python3 -c "
vals = []
with open('fort.13') as f:
    for line in f:
        parts = line.strip().split()
        if len(parts) == 2:
            try:
                n = float(parts[1])
                if 0.001 < n < 1.0:
                    vals.append(n)
            except: pass
if vals:
    import numpy as np
    a = np.array(vals)
    print(f'Manning n: min={a.min():.4f}, max={a.max():.4f}, mean={a.mean():.4f}')
"
```

## Traps

| Trap | ID | Symptom |
|------|----|---------|
| Manning's n out of range | dt_014 | Excessive/no friction; unrealistic velocities |
| Grid name mismatch with fort.14 | — | ADCIRC ignores fort.13 silently |
| NWP mismatch with fort.13 | — | Attributes not applied, uses defaults |
| Wrong attribute name spelling | — | Silent fallback to default values |

## Example

```bash
# Generate fort.13 from DEM-based depth classification
python ki/tools/convert_bathymetry_to_fort14.py \
    --dem gebco.nc \
    --domain_sw 28.0,-95.0 --domain_ne 30.5,-93.0 \
    --output_fort14 fort.14 --output_fort13 fort.13

# Verify
head -6 fort.13
# ADCIRC_MESH
# 23456
# 1
# mannings_n_at_sea_floor
# s/m^(1/3)
# 1
```
