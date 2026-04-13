# S1: Mesh Preparation (fort.14)

## Purpose

Generate or prepare the unstructured triangular finite element mesh that defines the computational domain for ADCIRC. The mesh (fort.14) contains node coordinates, element connectivity, bathymetric depths, and boundary definitions. Mesh quality directly controls solution accuracy, computational cost, and numerical stability.

## Inputs

| Input | Source | Format | Description |
|-------|--------|--------|-------------|
| Bathymetry DEM | GEBCO, ETOPO, local surveys | netCDF/GeoTIFF | Gridded elevation data (positive up) |
| Coastline | GSHHS, OpenStreetMap | Shapefile | High-resolution shoreline for boundary definition |
| Domain extent | User-defined | lat/lon box | SW and NE corner coordinates |
| Resolution targets | User-defined | meters | Min (nearshore) and max (offshore) element sizes |

## Outputs

| Output | File | Format | Description |
|--------|------|--------|-------------|
| Grid file | `fort.14` | ASCII | Nodes, elements, open/land boundaries |
| Mesh quality report | — | screen | Element quality metrics (aspect ratio, angle) |

## Procedure

1. **Define domain**: Choose lat/lon bounding box covering the area of interest with sufficient offshore extent for boundary placement.

2. **Acquire bathymetry**: Download GEBCO 2023 (15 arc-second global) or higher-resolution local surveys. Verify datum (GEBCO uses MSL, ADCIRC uses geoid).

3. **Generate mesh** using one of:
   - **OceanMesh2D** (MATLAB/Python): Automated ocean mesh generation with coastline-following and bathymetry-guided refinement
   - **SMS** (Surface-water Modeling System): Commercial GUI-based mesh editor
   - **convert_bathymetry_to_fort14.py** (this KI): Simple structured mesh from DEM for testing

4. **Assign bathymetry**: Interpolate DEM values to mesh nodes.
   - **CRITICAL**: ADCIRC depth convention is **positive below geoid** (dt_001)
   - DEM elevation (positive up) must be negated: `DP = -elevation`
   - Verify: ocean nodes should have DP > 0, land nodes DP < 0

5. **Define boundaries**:
   - **Open boundaries** (IBTYPE 0): Along offshore edges where tidal/surge forcing enters
   - **Land boundaries** (IBTYPE 0/10): Coastline, no-flow or no-slip
   - **Weir boundaries** (IBTYPE 3-5): Levees, barriers, dams
   - Nodes must be ordered **counter-clockwise** around the domain (dt_018)

6. **Quality checks**:
   - Minimum angle > 15° (ideally > 30°)
   - Aspect ratio < 10:1
   - No degenerate or overlapping elements
   - Smooth bathymetry transitions (no abrupt depth jumps between adjacent nodes)

## Verification

```bash
# Check node/element counts
head -2 fort.14

# Verify depth convention (should see positive values for ocean)
awk 'NR>2 && NR<=12 {print $1, $4}' fort.14

# Count boundary segments
grep -c "^[0-9]* 0$" fort.14  # IBTYPE=0 segments
```

## Traps

| Trap | ID | Symptom |
|------|----|---------|
| Depth sign inverted | dt_001 | Land is underwater, ocean is dry |
| Boundary nodes not CCW | dt_018 | Silent wrong boundary condition application |
| Too-coarse mesh | — | Misses important bathymetric features (channels, barriers) |
| Disconnected elements | dt_020 | Domain decomposition crash in parallel mode |

## Example

```bash
# Generate test mesh from GEBCO
python ki/tools/convert_bathymetry_to_fort14.py \
    --dem gebco_2023_sub.nc \
    --domain_sw 28.0,-95.0 --domain_ne 30.5,-93.0 \
    --min_resolution 1000 --max_resolution 20000 \
    --output_fort14 fort.14 --output_fort13 fort.13

# Verify
head -5 fort.14
# GULF_COAST_MESH
# 45678  23456
# 1   -94.9500000000   28.0500000000   15.2340000000
```
