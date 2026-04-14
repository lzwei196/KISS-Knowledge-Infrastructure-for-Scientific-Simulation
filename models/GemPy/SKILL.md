> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model.
>
>
> Before starting, run: `python preflight_check.py` (in this KI directory)
> to verify that the model binary/package and required data are available.
>
> **DEBUGGING PROTOCOL** — When something goes wrong, follow this order:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Read official docs** — The model's own documentation for expected formats/units
> 3. **Find working examples** — Check `outputs/` or the model's shipped test data
> 4. **Fix the tool** — With knowledge of what "correct" looks like
>
> Do NOT write custom debug scripts. The answers are in the docs and examples.

# GemPy Knowledge Infrastructure — SKILL.md

| Field             | Value                                              |
|-------------------|----------------------------------------------------|
| Package           | hydrocraft-gempy-geological                        |
| Version           | 1.0.0                                              |
| Target model      | GemPy v3 (2024.1) — 3D Implicit Geological Modeler|
| Domain            | 3D structural geology, geophysics                  |
| Language          | Python 3.10–3.12                                   |
| License           | EUPL-1.2                                           |
| Repository        | https://github.com/cgre-aachen/gempy               |
| Validation status | Phase 2 — KI authored, build pending               |

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/DTB/SKILL.md` for depth-to-bedrock data.


## 1. Overview

GemPy is an open-source Python library for constructing **3D implicit geological
models**. It uses potential-field interpolation (universal co-kriging) to create
continuous scalar fields from which geological surfaces, fault networks, and
unconformities are extracted. GemPy represents geology implicitly — each
formation boundary is an iso-surface of a scalar field, enabling arbitrary
topology without explicit surface meshing during interpolation.

### Core Capabilities

- **Implicit surface modeling** via potential-field interpolation (kriging)
- **Fault networks** with configurable fault–fault and fault–formation relations
- **Unconformities** (erosion, onlap) via structural group stacking
- **Octree refinement** for variable-resolution grids (efficient computation)
- **Dual contouring / marching cubes** for mesh extraction
- **Geophysics integration** — forward gravity/magnetics from 3D geology
- **Probabilistic modeling** via PyTorch backend (automatic differentiation)
- **Serialization** to `.gempy` binary format (zlib-compressed)

### Architecture (v3)

GemPy v3 is split into four packages:

| Package          | Role                          |
|------------------|-------------------------------|
| `gempy`          | High-level API, data classes  |
| `gempy_engine`   | Computation (NumPy/PyTorch)   |
| `gempy_viewer`   | Visualization (matplotlib/PyVista) |
| `gempy_plugins`  | Extensions (topology, etc.)   |

---

## 2. Installation

### Quick Install (pip)

```bash
python -m venv venv && source venv/bin/activate
pip install "gempy[base]"       # core + viewer + pandas
pip install "gempy[opt]"        # + plugins, pooch, scipy, scikit-image
```

### From Source

```bash
git clone https://github.com/cgre-aachen/gempy.git
cd gempy
pip install -e ".[base]"
```

### Dependencies

| Package          | Version Constraint         | Role                    |
|------------------|----------------------------|-------------------------|
| gempy_engine     | >=2026.0.1dev0,<2026.1.0   | Interpolation backend   |
| gempy_viewer     | ~2025.1.4                  | 2D/3D visualization     |
| pandas           | >=2.2.0,<3.0.0             | CSV I/O                 |
| numpy            | (via gempy_engine)         | Array operations        |
| pydantic         | (via gempy_engine)         | Data validation         |
| pooch            | optional                   | Example data download   |
| scipy            | optional                   | Scientific computing    |
| scikit-image     | optional                   | Mesh post-processing    |

### Smoke Test

```python
import gempy as gp
model = gp.create_geomodel(
    project_name="test",
    extent=[0, 1000, 0, 1000, 0, 1000],
    resolution=[10, 10, 10],
    refinement=4
)
print(model)  # Should print GeoModel summary
```

---

## 3. Pipeline Architecture

```
┌─────────────────┐
│ S1: Input Data   │  CSV surface points + orientations
│   Preparation    │  (X, Y, Z, formation, G_x, G_y, G_z)
└────────┬────────┘
         │
┌────────▼────────┐
│ S2: GeoModel     │  create_geomodel() with extent, resolution
│   Initialization │  ImporterHelper for CSV column mapping
└────────┬────────┘
         │
┌────────▼────────┐
│ S3: Structural   │  map_stack_to_surfaces()
│   Organization   │  Define series, groups, fault relations
└────────┬────────┘
         │
┌────────▼────────┐
│ S4: Grid         │  OCTREE / DENSE / CUSTOM / TOPOGRAPHY
│   Configuration  │  set_active_grid(), set_section_grid()
└────────┬────────┘
         │
┌────────▼────────┐
│ S5: Fault        │  set_is_fault(), set_fault_relation()
│   Configuration  │  Finite fault support (prototype)
└────────┬────────┘
         │
┌────────▼────────┐
│ S6: Interpolation│  compute_model(engine_config)
│   Computation    │  Backend: NumPy (default) or PyTorch
└────────┬────────┘
         │
┌────────▼────────┐
│ S7: Solution     │  scalar_field, block model, meshes
│   Extraction     │  Marching cubes / dual contouring
└────────┬────────┘
         │
┌────────▼────────┐
│ S8: Validation   │  Cross-section plots, 3D visualization
│   & Visualization│  Geophysics forward modeling (gravity)
└────────┬────────┘
         │
┌────────▼────────┐
│ S9: Export &     │  .gempy binary, VTK, CSV, JSON
│   Serialization  │  save_model() / load_model()
└─────────────────┘
```

### Stage Dependencies

| Stage | Depends On | Parallel? |
|-------|-----------|-----------|
| S1    | —         | Yes       |
| S2    | S1        | No        |
| S3    | S2        | No        |
| S4    | S2        | Yes (with S3, S5) |
| S5    | S2        | Yes (with S3, S4) |
| S6    | S3, S4, S5| No        |
| S7    | S6        | No        |
| S8    | S7        | Yes       |
| S9    | S7        | Yes (with S8) |

---

## 4. Input Formats

### Surface Points CSV

| Column     | Type    | Unit/Range              | Description                    |
|------------|---------|-------------------------|--------------------------------|
| X          | float64 | meters (project CRS)    | Easting coordinate             |
| Y          | float64 | meters (project CRS)    | Northing coordinate            |
| Z          | float64 | meters (elevation)      | Vertical position              |
| formation  | string  | —                       | Surface/layer name             |

### Orientations CSV

| Column     | Type    | Unit/Range              | Description                    |
|------------|---------|-------------------------|--------------------------------|
| X          | float64 | meters (project CRS)    | Easting of measurement         |
| Y          | float64 | meters (project CRS)    | Northing of measurement        |
| Z          | float64 | meters (elevation)      | Vertical position              |
| G_x        | float64 | unitless (-1 to 1)      | Gradient X (or use azimuth)    |
| G_y        | float64 | unitless (-1 to 1)      | Gradient Y (or use dip)        |
| G_z        | float64 | unitless (-1 to 1)      | Gradient Z (or use polarity)   |

**Alternative orientation format** (azimuth/dip/polarity):
- `azimuth`: 0–360 degrees, clockwise from North
- `dip`: 0–90 degrees, angle from horizontal
- `polarity`: +1 or -1, normal direction indicator

Conversion: `G_x = sin(dip) * sin(azimuth) * polarity`

### Model Extent

```python
extent = [x_min, x_max, y_min, y_max, z_min, z_max]  # all in meters
```

### Grid Resolution

```python
resolution = [nx, ny, nz]       # number of cells per axis (DENSE)
refinement = 1..8               # octree refinement level (OCTREE)
```

---

## 5. Output Formats

### Solutions Object (in-memory)

| Attribute       | Type            | Description                          |
|-----------------|-----------------|--------------------------------------|
| scalar_field    | ndarray float64 | Continuous potential values at grid   |
| block           | ndarray int32   | Discrete formation IDs at grid       |
| vertices        | list[ndarray]   | Mesh vertices per surface            |
| edges           | list[ndarray]   | Mesh triangles per surface           |
| normals         | list[ndarray]   | Surface normals per surface          |

### Serialization Formats

| Format   | Extension | Tool                     |
|----------|-----------|--------------------------|
| Binary   | .gempy    | save_model/load_model    |
| VTK      | .vtk      | gempy_viewer export      |
| CSV      | .csv      | pandas export            |
| JSON     | .json     | json_geomodel_encoder    |

---

## 6. Unit Trap Table

These are the most common unit-related errors when working with GemPy:

| ID      | Trap                                    | Severity | Effect                              |
|---------|-----------------------------------------|----------|-------------------------------------|
| dt_001  | Coordinates in km instead of m          | silent   | Model 1000x too small, thin layers  |
| dt_002  | Azimuth in radians instead of degrees   | silent   | Orientations point wrong direction   |
| dt_003  | Dip measured from vertical, not horiz.  | silent   | All surfaces inverted               |
| dt_004  | Polarity sign flipped                   | silent   | Layers stacked in reverse order      |
| dt_005  | Extent Z-axis inverted (min > max)      | fatal    | Empty model or crash                |
| dt_006  | Gradient vector not normalized          | degraded | Interpolation bias, asymmetric fit  |
| dt_007  | Nugget too large (>0.1)                 | degraded | Over-smoothed, lost detail          |
| dt_008  | Nugget too small (<1e-8)                | fatal    | Singular matrix, computation fails  |
| dt_009  | Mixing CRS (e.g., WGS84 + UTM)         | silent   | Distorted geometry, wrong scale     |
| dt_010  | Topography elevation units mismatch     | silent   | Surfaces clip through topography    |

---

## 7. Tools Reference

| Tool                       | Script                                  | Purpose                                  |
|----------------------------|-----------------------------------------|------------------------------------------|
| Input Converter            | tools/convert_geological_data.py        | CSV/shapefile → GemPy format             |
| Parameter Builder          | tools/build_structural_params.py        | Build structural frame from config       |
| Execution Wrapper          | tools/run_gempy_model.py                | End-to-end model computation             |
| Output Parser              | tools/parse_gempy_output.py             | Extract results to CSV/JSON              |

---

## 8. Critical Domain Knowledge

### DK-001: Orientation convention
GemPy uses **gradient vectors** (G_x, G_y, G_z) internally, not azimuth/dip.
When using azimuth/dip input, the conversion is:
```
G_x = sin(dip_rad) * sin(azimuth_rad) * polarity
G_y = sin(dip_rad) * cos(azimuth_rad) * polarity
G_z = cos(dip_rad) * polarity
```
The gradient must be a **unit vector** (|G| = 1). Non-unit gradients cause
interpolation bias.

### DK-002: Structural hierarchy matters
The order of structural groups in the StructuralFrame determines erosion
priority. The **youngest** group (lowest index) erodes all older groups
beneath it. Incorrect ordering produces geologically impossible cross-cutting
relationships.

### DK-003: Fault relations are not symmetric
`set_fault_relation()` takes a boolean matrix. Entry `[i,j]` means "fault i
affects group j". The matrix is NOT symmetric — a fault can affect one series
without affecting another.

### DK-004: Octree vs Dense grid
OCTREE is faster but can miss thin layers or narrow fault zones if refinement
is too low. Start with refinement=6; increase to 8 for complex models. DENSE
grid is more reliable but O(n³) in memory.

### DK-005: The nugget effect
The nugget parameter controls Tikhonov regularization. Too small → singular
covariance matrix (computation crash). Too large → surfaces don't honor data
points. Default nugget for surface points is 0.00002; for orientations, 0.01.
Use `optimize_nuggets()` with PyTorch backend for automatic tuning.

### DK-006: Scalar field topology
Each structural group has its own scalar field. Formation boundaries are
iso-surfaces. The scalar field value increases with depth (younger to older
formations). This means the **gradient points downward** for normally stacked
layers.

### DK-007: Data minimum requirements
Each surface requires at least **1 surface point** and the structural group
needs at least **1 orientation**. Faults require at least **2 surface points**
on each side of the fault trace plus orientations perpendicular to the fault
plane.

### DK-008: Coordinate rescaling
GemPy internally rescales coordinates to [0,1]³ for numerical stability. This
means the absolute coordinate values don't matter — only relative positions.
However, if extent is extremely large (>1e6 m), floating-point precision can
still be an issue.

### DK-009: Backend selection matters
NumPy backend is default and CPU-only. PyTorch backend enables GPU acceleration
and automatic differentiation (for probabilistic modeling). Switch via
`GemPyEngineConfig(backend=AvailableBackends.PYTORCH)`.

---

## 9. Diagnostic Triplet Summary

| ID     | Stage | Symptom (short)                         | Severity |
|--------|-------|-----------------------------------------|----------|
| dt_001 | S1    | Model too small / thin layers           | silent   |
| dt_002 | S1    | Orientations wrong direction            | silent   |
| dt_003 | S1    | Surfaces inverted                       | silent   |
| dt_004 | S1    | Layers in reverse order                 | silent   |
| dt_005 | S2    | Empty model / crash                     | fatal    |
| dt_006 | S1    | Interpolation bias                      | degraded |
| dt_007 | S6    | Over-smoothed surfaces                  | degraded |
| dt_008 | S6    | Singular matrix crash                   | fatal    |
| dt_009 | S1    | Distorted geometry                      | silent   |
| dt_010 | S4    | Surfaces clip topography                | silent   |
| dt_011 | S3    | Wrong erosion patterns                  | silent   |
| dt_012 | S5    | Fault doesn't cut expected layers       | silent   |
| dt_013 | S6    | Octree misses thin layers               | degraded |
| dt_014 | S6    | Out-of-memory on large grids            | fatal    |
| dt_015 | S7    | Mesh has holes or self-intersections    | degraded |

See `diagnostics/triplets.yaml` for full symptom→diagnosis→remedy details.

---

## 10. File Structure

```
ki/
├── SKILL.md                              ← this file
├── tools/
│   ├── convert_geological_data.py        ← input data conversion
│   ├── build_structural_params.py        ← structural frame builder
│   ├── run_gempy_model.py                ← model execution wrapper
│   └── parse_gempy_output.py             ← output extraction
├── docs/
│   ├── s1_input_data_preparation.md      ← data prep skill
│   ├── s2_model_initialization.md        ← model setup skill
│   ├── s3_structural_organization.md     ← structural frame skill
│   ├── s4_grid_configuration.md          ← grid setup skill
│   ├── s5_fault_configuration.md         ← fault setup skill
│   ├── s6_computation.md                 ← computation skill
│   └── s7_output_analysis.md             ← analysis skill
└── diagnostics/
    └── triplets.yaml                     ← 15+ diagnostic triplets
```

---

## 11. Quick-Start Example

```python
import gempy as gp

# 1. Create model with extent and CSV data
importer = gp.data.ImporterHelper(
    path_to_surface_points="points.csv",
    path_to_orientations="orientations.csv"
)
model = gp.create_geomodel(
    project_name="test_model",
    extent=[0, 2000, 0, 2000, -1000, 0],
    refinement=6,
    importer_helper=importer
)

# 2. Organize structural frame
gp.map_stack_to_surfaces(
    gempy_model=model,
    mapping_object={
        "Fault_Series": ("Main_Fault",),
        "Strat_Series": ("Sandstone", "Siltstone", "Shale")
    }
)

# 3. Configure faults
gp.set_is_fault(model, ["Fault_Series"])

# 4. Compute
solutions = gp.compute_model(model)

# 5. Access results
block = model.solutions.raw_arrays.block       # formation IDs
scalar = model.solutions.raw_arrays.scalar_field  # continuous field

# 6. Save
gp.save_model(model, path="output/", name="test_model")
```

---

*Generated by HydroCraft Knowledge Dissection Toolkit — 2026-03-26*
