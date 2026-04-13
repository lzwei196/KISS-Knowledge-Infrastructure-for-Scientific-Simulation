# S7: Output Analysis and Export

## Purpose

Extract, analyze, and export GemPy model results for downstream use —
including block models to CSV, mesh surfaces to VTK/OBJ, cross-section
visualization, and validation against known geology.

## Inputs

| Input              | Format          | Source                       |
|--------------------|-----------------|------------------------------|
| Computed model     | GeoModel        | S6 output                    |
| .gempy file        | binary          | Saved model file             |

## Outputs

| Output              | Format    | Description                        |
|---------------------|-----------|------------------------------------|
| block_model.csv     | CSV       | X, Y, Z, formation_id per cell    |
| scalar_field.csv    | CSV       | X, Y, Z, scalar_value per cell    |
| meshes/             | CSV       | vertices + triangles per surface   |
| summary.json        | JSON      | Model statistics                   |
| cross_section.png   | PNG       | 2D visualization                   |
| 3d_model.vtk        | VTK       | 3D export for ParaView/PyVista    |

## Procedure

### Step 1: Use the output parser tool

```bash
python ki/tools/parse_gempy_output.py \
    --model-file results/model.gempy \
    --extract all \
    --output-dir parsed_output/
```

### Step 2: Visualize cross-sections (Python)

```python
import gempy_viewer as gpv

# 2D cross-section
gpv.plot_2d(model, section_names=["NS_section"])

# 2D block model map
gpv.plot_2d(model, show_data=True, show_boundaries=True)
```

### Step 3: 3D visualization

```python
# Interactive 3D view
gpv.plot_3d(model, show_surfaces=True, show_data=True)

# Export to VTK for ParaView
gpv.plot_3d(model, image=False, plotter_type="background")
```

### Step 4: Compare with known geology

For validation, compare model predictions at borehole locations:

```python
import numpy as np

# Known formation at specific points
known_points = np.array([
    [500, 500, -100],  # Should be "Sandstone"
    [500, 500, -500],  # Should be "Shale"
])
predictions = gp.compute_model_at(model, at=known_points)
# Compare predicted formation IDs with expected
```

### Step 5: Volume calculation

```python
import numpy as np

block = model.solutions.raw_arrays.block
grid = model.grid.values

# Cell volume (for regular grid)
dx = (extent[1] - extent[0]) / resolution[0]
dy = (extent[3] - extent[2]) / resolution[1]
dz = (extent[5] - extent[4]) / resolution[2]
cell_vol = dx * dy * dz

unique_ids, counts = np.unique(block, return_counts=True)
for uid, count in zip(unique_ids, counts):
    vol = count * cell_vol
    print(f"Formation {uid}: {vol:.0f} m^3 ({count} cells)")
```

## Verification

- [ ] Block model CSV has correct XYZ coordinates and formation IDs
- [ ] Scalar field values are finite (no NaN/Inf)
- [ ] Mesh surfaces are watertight (no holes or self-intersections)
- [ ] Cross-sections show geologically sensible structure
- [ ] Formation volumes sum to total model volume
- [ ] Borehole predictions match known stratigraphy

## Traps

| Trap    | Description                                            | Severity |
|---------|--------------------------------------------------------|----------|
| dt_015  | Mesh has holes or self-intersections near faults       | degraded |
| dt_011  | Wrong structural ordering visible in cross-section     | silent   |

## Example

Full output pipeline:

```bash
# Parse model to CSV/JSON
python ki/tools/parse_gempy_output.py \
    --model-file results/test_model.gempy \
    --extract block mesh summary \
    --output-dir parsed/ \
    --output parse_result.json

# View results
cat parse_result.json
```

Expected output:
```json
{
  "status": "success",
  "block": {
    "status": "success",
    "n_points": 125000,
    "n_formations": 4,
    "formation_cell_counts": {"1": 31250, "2": 31250, "3": 31250, "4": 31250}
  },
  "mesh": {
    "status": "success",
    "n_surfaces": 3,
    "meshes": [
      {"surface": "surface_000", "n_vertices": 1024, "n_triangles": 2000},
      {"surface": "surface_001", "n_vertices": 980, "n_triangles": 1900},
      {"surface": "surface_002", "n_vertices": 1100, "n_triangles": 2150}
    ]
  },
  "summary": {
    "status": "success",
    "project_name": "test_model",
    "n_groups": 2,
    "grid": {"n_points": 125000}
  }
}
```
