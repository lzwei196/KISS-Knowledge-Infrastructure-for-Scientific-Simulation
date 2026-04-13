# Skill: Grid Setup (Stage 1)

## Purpose

Create a Landlab model grid that defines the spatial domain for landscape
evolution simulation. The grid determines cell size, topology, boundary
conditions, and available field storage locations. Getting grid setup wrong
(wrong spacing units, wrong boundary conditions) silently corrupts every
downstream calculation.

## Inputs

| Input | Format | Units | Source |
|-------|--------|-------|--------|
| Grid shape | tuple (nrows, ncols) | dimensionless | User choice |
| Grid spacing | float or (dx, dy) | meters | DEM resolution or user choice |
| Boundary condition preset | string | — | User choice |
| Initial topography | array or file | meters | DEM, synthetic, or flat |

## Outputs

| Output | Format | Location | Description |
|--------|--------|----------|-------------|
| `RasterModelGrid` object | Python object | memory | Grid with topology and boundary info |
| `topographic__elevation` | float array | at_node | Initial land surface elevation (m) |
| Grid boundary status | int array | at_node | NodeStatus codes for each node |

## Procedure

1. **Choose grid type**: `RasterModelGrid` for rectangular DEMs (most common).
   Use `HexModelGrid` for isotropic diffusion studies. Use `VoronoiDelaunayGrid`
   for irregular domains.

2. **Set spacing in METERS**:
   ```python
   from landlab import RasterModelGrid
   mg = RasterModelGrid((100, 200), xy_spacing=30.0)  # 30m DEM
   ```
   TRAP: If your DEM is in geographic coordinates (degrees), you must reproject
   to a metric CRS first. Passing degrees as spacing produces slopes ~100,000×
   too large (dt_004).

3. **Add initial topography**:
   ```python
   z = mg.add_zeros("topographic__elevation", at="node")
   # For synthetic: add random noise + regional slope
   z += np.random.rand(mg.number_of_nodes) * 0.1
   z += mg.node_y * 0.001  # gentle slope toward south
   ```

4. **Set boundary conditions**:
   ```python
   # South open, others closed (common for 1D-like drainage)
   mg.set_closed_boundaries_at_grid_edges(
       right_is_closed=True,
       top_is_closed=True,
       left_is_closed=True,
       bottom_is_closed=False
   )
   ```
   TRAP: If ALL edges are closed, FlowAccumulator produces zero drainage area
   everywhere (dt_011). There must be at least one open (fixed-value) boundary
   node for water/sediment to exit.

5. **Verify the grid**:
   ```python
   print(f"Nodes: {mg.number_of_nodes}")
   print(f"Core nodes: {mg.number_of_core_nodes}")
   print(f"Open boundary nodes: {np.sum(mg.status_at_node == mg.BC_NODE_IS_FIXED_VALUE)}")
   assert np.sum(mg.status_at_node == mg.BC_NODE_IS_FIXED_VALUE) > 0, "No open boundary!"
   ```

## Verification

- Grid has expected shape: `mg.shape == (nrows, ncols)`
- At least one open boundary node exists
- Spacing is in meters (not degrees, not km)
- Elevation field is attached and has correct length

## Traps

| Trap | Symptom | Fix | Triplet |
|------|---------|-----|---------|
| Spacing in degrees | Slopes = ~10⁵, extreme erosion | Reproject DEM to UTM | dt_004 |
| All boundaries closed | drainage_area = 0 everywhere | Open at least one edge | dt_011 |
| DEM nodata not masked | Flow routes into nodata cells | Mask nodata, set BC_CLOSED | dt_010 |
| Elevation in feet | Slopes 3× too large | Multiply by 0.3048 | dt_007 |

## Example

```python
import numpy as np
from landlab import RasterModelGrid

# 50×50 grid at 100m spacing
mg = RasterModelGrid((50, 50), xy_spacing=100.0)
z = mg.add_zeros("topographic__elevation", at="node")
z += np.random.rand(mg.number_of_nodes) * 1.0
z += mg.node_x * 0.01  # slope toward x=0

# Open west edge only
mg.set_closed_boundaries_at_grid_edges(
    right_is_closed=True, top_is_closed=True,
    left_is_closed=False, bottom_is_closed=True
)
print(f"Grid: {mg.shape}, dx={mg.dx}m, open BCs: "
      f"{np.sum(mg.status_at_node == mg.BC_NODE_IS_FIXED_VALUE)}")
```
