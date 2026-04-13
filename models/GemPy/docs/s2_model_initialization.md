# S2: Model Initialization

## Purpose

Create a GemPy GeoModel object with the correct spatial extent, grid type,
resolution, and imported data. This is the foundation for all subsequent
modeling stages.

## Inputs

| Input              | Format | Source                           |
|--------------------|--------|----------------------------------|
| surface_points.csv | CSV    | S1 output                        |
| orientations.csv   | CSV    | S1 output                        |
| Model extent       | list   | [xmin, xmax, ymin, ymax, zmin, zmax] in meters |
| Grid type          | string | "octree" or "dense"              |
| Resolution/Refine  | int/list | refinement (1-8) or [nx,ny,nz] |

## Outputs

| Output     | Type      | Description                         |
|------------|-----------|-------------------------------------|
| GeoModel   | in-memory | GemPy model with data and grid      |

## Procedure

1. **Determine extent** from data:
   - Extent should enclose all surface points with a margin (~10% buffer).
   - Z-axis: z_min < deepest point, z_max > shallowest point.
   - **CRITICAL**: z_min MUST be less than z_max (TRAP dt_005).

2. **Choose grid type**:
   - **OCTREE** (recommended): Adaptive resolution, efficient for most models.
     Set `refinement=4` for testing, `refinement=6` for production,
     `refinement=8` for high-detail models.
   - **DENSE**: Regular grid, predictable resolution. Good for small models.
     Set `resolution=[nx, ny, nz]` — total cells = nx * ny * nz.
     Keep under 10M cells to avoid memory issues (TRAP dt_014).

3. **Create model via API**:
   ```python
   import gempy as gp

   importer = gp.data.ImporterHelper(
       path_to_surface_points="gempy_input/surface_points.csv",
       path_to_orientations="gempy_input/orientations.csv"
   )

   model = gp.create_geomodel(
       project_name="my_model",
       extent=[0, 2000, 0, 2000, -1000, 0],
       refinement=6,
       importer_helper=importer
   )
   ```

4. **Verify data loaded correctly**:
   ```python
   print(model.structural_frame)
   # Check number of surface points and orientations loaded
   ```

## Verification

- [ ] Model created without errors
- [ ] Correct number of surface points loaded (matches CSV row count)
- [ ] Correct number of orientations loaded
- [ ] Extent covers all data points
- [ ] Grid type matches intent (OCTREE vs DENSE)
- [ ] z_min < z_max in extent

## Traps

| Trap    | Description                                         | Severity |
|---------|-----------------------------------------------------|----------|
| dt_005  | Z-axis inverted (z_min > z_max) — empty/crash       | fatal    |
| dt_014  | Dense grid too large (>10M cells) — out of memory   | fatal    |
| dt_001  | Extent in km while data in m — huge empty model      | silent   |

## Example

```python
import gempy as gp

# From CSV files
importer = gp.data.ImporterHelper(
    path_to_surface_points="gempy_input/surface_points.csv",
    path_to_orientations="gempy_input/orientations.csv"
)
model = gp.create_geomodel(
    project_name="Perth_Basin",
    extent=[337000, 400000, 6440000, 6500000, -3200, 200],
    refinement=6,
    importer_helper=importer
)
print(f"Grid points: {model.grid.values.shape[0]}")
print(f"Structural groups: {len(model.structural_frame.structural_groups)}")
```
