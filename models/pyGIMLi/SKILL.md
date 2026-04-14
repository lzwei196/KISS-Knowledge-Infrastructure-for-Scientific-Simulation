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

# pyGIMLi Knowledge Infrastructure — SKILL.md

**Package**: hydrocraft-pygimli-geophysics v1.0.0
**Model**: pyGIMLi (Python Library for Geophysical Inversion and Modelling)
**Version**: 1.5+
**Domain**: Geophysics — Electrical Resistivity Tomography (ERT), Seismic Refraction (SRT), Electromagnetics (EM), Induced Polarization (IP)
**Authors**: Carsten Rücker, Thomas Günther, Florian Wagner
**License**: Apache 2.0
**Stats**: 4 tools | 5 skill documents | 18 diagnostic triplets | ~71,000 lines Python

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/DTB/SKILL.md` for depth-to-bedrock data.


## 1. Overview

pyGIMLi is an open-source multi-method geophysical modelling and inversion library
built on a C++ core (`libgimli`) with Python bindings. It provides:

- **Mesh generation**: 2D/3D unstructured meshes via Triangle/Tetgen
- **Forward modelling**: FEM/FVM-based PDE solvers for ERT, SRT, EM, gravity
- **Inversion**: Gauss-Newton with Tikhonov regularization, model/data transforms
- **Joint inversion**: Structurally-coupled multi-method inversion
- **Visualization**: Matplotlib (2D) and PyVista (3D) backends

**Canonical import**:
```python
import pygimli as pg
```

**Key paper**: Rücker et al. (2017), "pyGIMLi: An open-source library for modelling
and inversion in geophysics", Computers & Geosciences, 109:106-123.

---

## 2. Installation

### Recommended (conda)
```bash
conda install -c gimli -c conda-forge pygimli
```

### From PyPI
```bash
pip install pygimli
```

### From source (development)
```bash
git clone https://github.com/gimli-org/gimli.git
cd gimli
pip install -e .
```

The C++ core (`pgcore`) is distributed as a pre-built binary wheel.
Building from source requires CMake >= 3.15, Boost, SuiteSparse, Triangle, TetGen.

### Verify installation
```python
import pygimli as pg
print(pg.__version__)
pg.test()  # run test suite
```

### Dependencies
| Package   | Purpose                          | Required |
|-----------|----------------------------------|----------|
| numpy     | Array operations                 | Yes      |
| scipy     | Sparse linear algebra            | Yes      |
| matplotlib| 2D visualization                 | Yes      |
| pgcore    | C++ core bindings                | Yes      |
| pyvista   | 3D visualization                 | No       |
| tetgen    | 3D mesh generation               | No       |
| meshio    | Mesh format I/O                  | No       |

---

## 3. Pipeline Stages

A typical pyGIMLi workflow follows these stages:

| Stage | Name                  | Description                                      | Tool                     |
|-------|-----------------------|--------------------------------------------------|--------------------------|
| s0    | Data Preparation      | Load/convert field data to pyGIMLi format        | `convert_data_to_gimli.py` |
| s1    | Mesh Generation       | Create FEM mesh from electrode/sensor geometry   | (pg.meshtools API)       |
| s2    | Parameter Setup       | Define starting model, regions, constraints      | `convert_parameters.py`  |
| s3    | Forward/Inversion     | Run forward modelling or inversion               | `run_pygimli.py`         |
| s4    | Output Analysis       | Parse results, compute metrics, export CSV/VTK   | `parse_gimli_output.py`  |

### Stage s0: Data Preparation
- Convert field data (Res2DInv, ABEM, Syscal, SEG-2) to pyGIMLi DataContainer
- Validate electrode positions, check for negative values
- Apply error estimation if not provided

### Stage s1: Mesh Generation
- Build PLC (Piecewise Linear Complex) from sensor positions
- Generate unstructured mesh with quality constraints
- Add boundary regions for numerical stability

### Stage s2: Parameter Setup
- Define petrophysical model regions
- Set starting model (homogeneous or layered)
- Configure regularization (smoothness, minimum-length, geostatistical)
- Set model/data transformations (log, logLU, cotLU)

### Stage s3: Forward Modelling / Inversion
- Forward: compute synthetic data from a given model
- Inversion: iterative Gauss-Newton with line search
- Monitor chi-squared, relative RMS, model roughness

### Stage s4: Output Analysis
- Extract model parameters per cell
- Export to VTK for 3D visualization
- Compute coverage/sensitivity
- Compare observed vs. predicted data

---

## 4. Supported Geophysical Methods

### 4.1 Electrical Resistivity Tomography (ERT)
- **Manager**: `pg.physics.ert.ERTManager`
- **Forward operator**: `ERTModelling` (FEM with singularity removal)
- **Data tokens**: `rhoa` (apparent resistivity, Ω·m), `u` (voltage, V), `i` (current, A)
- **Model parameter**: Resistivity (Ω·m), inverted in log-space
- **Data transform**: `TransLogLU` (log with bounds)
- **Schemes**: Wenner, Schlumberger, Dipole-Dipole, Gradient, custom

### 4.2 Seismic Refraction Tomography (SRT)
- **Manager**: `pg.physics.traveltime.TravelTimeManager`
- **Forward operator**: `TravelTimeDijkstraModelling` (shortest-path ray tracing)
- **Data tokens**: `t` (travel time, s), `va` (apparent velocity, m/s)
- **Model parameter**: Slowness (s/m), displayed as velocity (m/s)
- **Schemes**: Hammer source, multi-channel receivers

### 4.3 Spectral Induced Polarization (SIP)
- **Manager**: `pg.physics.SIP.SpectrumManager`
- **Data tokens**: `ipa` (apparent phase, mrad), `rhoa` (Ω·m)
- **Model**: Cole-Cole parameters (ρ₀, m, τ, c)

### 4.4 Electromagnetics (EM)
- **Classes**: `FDEM`, `TDEM`, `VMDTimeDomainModelling`
- **Data**: Apparent conductivity (S/m), in-phase/quadrature components
- **Model**: Layered conductivity (S/m)

### 4.5 Vertical Electrical Sounding (VES)
- **Manager**: `pg.physics.ves.VESManager`
- **Model**: 1D layered resistivity (Ω·m) with thicknesses (m)

---

## 5. Unit Trap Table

These are the most common unit-related errors in pyGIMLi workflows:

| # | Quantity             | Expected Unit  | Common Mistake        | Effect                               | Severity |
|---|----------------------|----------------|-----------------------|--------------------------------------|----------|
| 1 | Resistivity          | Ω·m            | kΩ·m (×1000)          | Model values 1000× too high          | Silent   |
| 2 | Apparent resistivity | Ω·m            | Ω (missing ×k factor) | Geometric factor not applied         | Silent   |
| 3 | Travel time          | s (seconds)    | ms (milliseconds)     | Velocity 1000× too high              | Silent   |
| 4 | Electrode spacing    | m (metres)     | cm or ft               | Mesh scale wrong, depth wrong        | Silent   |
| 5 | IP phase             | mrad           | rad or degrees         | Phase 1000× too high or ×17.45       | Silent   |
| 6 | Coordinates          | m (local)      | lat/lon (degrees)      | Mesh generation fails or nonsense    | Fatal    |
| 7 | Error estimate       | fraction (0-1) | percent (0-100)        | Overfit or underfit, chi² wrong      | Degraded |
| 8 | EM frequency         | Hz             | kHz                    | Wrong skin depth                     | Silent   |
| 9 | Depth/elevation      | m (positive down or ASL) | Mixed sign convention | Inverted model upside-down     | Silent   |
|10 | Conductivity (EM)    | S/m            | mS/m                   | 1000× error in apparent conductivity | Silent   |

---

## 6. Data File Formats

### Input Formats
| Format      | Extension        | Method | Description                        |
|-------------|------------------|--------|------------------------------------|
| BERT/GIMLI  | `.dat`, `.ohm`   | ERT    | Native: header + ABMN columns     |
| Res2DInv    | `.dat`           | ERT    | General array format               |
| ABEM        | `.ohm`           | ERT    | Terrameter LS/SAS export           |
| Syscal      | `.txt`, `.csv`   | ERT    | Iris Instruments Syscal Pro        |
| SEG-2       | `.sg2`, `.dat`   | SRT    | Seismograph records                |
| GIMLI       | `.sgt`, `.gtt`   | SRT    | Native travel time format          |
| PLC         | `.poly`          | Mesh   | Piecewise linear complex           |
| Gmsh        | `.msh`           | Mesh   | Gmsh format (v2 and v4)           |
| VTK         | `.vtk`           | Mesh   | Visualization Toolkit format       |
| HDF5        | `.hdf5`          | Mesh   | HDF5 mesh and data                 |
| Binary mesh | `.bms`           | Mesh   | pyGIMLi native binary mesh         |

### Output Formats
- **Model results**: NumPy arrays → CSV, VTK, HDF5
- **Mesh + model**: `.bms` (binary), `.vtk` (VTK), `.msh` (Gmsh)
- **Figures**: Matplotlib PNG/PDF/SVG
- **Jacobian**: Sparse matrix in CSR format

---

## 7. Tools Reference

| Tool                        | Lines | Stage | Purpose                                    |
|-----------------------------|-------|-------|--------------------------------------------|
| `convert_data_to_gimli.py`  | 280   | s0    | Field data → pyGIMLi DataContainer format  |
| `convert_parameters.py`     | 250   | s2    | Petrophysical params → region config       |
| `run_pygimli.py`            | 230   | s3    | Execute forward modelling or inversion     |
| `parse_gimli_output.py`     | 260   | s4    | Extract results to CSV, compute metrics    |

---

## 8. Critical Domain Knowledge

### 8.1 Geometric Factor (ERT)
The geometric factor `k` converts measured resistance (V/I in Ω) to apparent
resistivity (ρₐ in Ω·m). If electrodes are in non-standard positions (topography,
boreholes), analytical `k` is invalid — use numerical `k` via `createGeometricFactors()`.
Failure to do so produces systematically biased apparent resistivities.

### 8.2 Singularity Removal (ERT)
The FEM solution has a singularity at current injection electrodes. pyGIMLi uses
singularity removal (`sr=True` by default in ERTManager) to subtract the analytical
primary potential. Disabling this on coarse meshes produces electrode-proximity
artifacts that look like real anomalies.

### 8.3 Slowness vs. Velocity (SRT)
pyGIMLi inverts for **slowness** (s/m), not velocity (m/s). The inversion operates
in slowness space because the travel time forward problem is linear in slowness.
Results displayed as velocity are the reciprocal: `v = 1/slowness`. Applying
log-transform to velocity instead of slowness breaks the linear forward operator.

### 8.4 Data Transformations
- ERT: `TransLogLU` on data (apparent resistivity is always positive)
- SRT: `TransLin` on data (travel times are already well-behaved)
- Wrong transform → inversion diverges or produces artifacts

### 8.5 Regularization Strength (Lambda)
Lambda controls the trade-off between data fit and model smoothness.
- Too high → over-smoothed model, misses anomalies
- Too low → rough model with artifacts, overfitting noise
- Default: lambda=20, reduce by factor 2-5 per iteration
- Target: chi² ≈ 1 (data fit matches noise level)

### 8.6 Error Estimation
If field data lacks error estimates, use `estimateError()`:
- ERT: `estimateError(data, relativeError=0.03, absoluteUError=5e-5)`
  - 3% relative + 50 µV absolute is typical for modern instruments
- SRT: absolute error of 0.001 s (1 ms) is typical for hammer sources
- Under-estimated error → overfitting (artifacts); over-estimated → under-fitting

### 8.7 Mesh Quality
- Minimum angle > 20° for triangles (quality parameter q=34 in Triangle)
- Maximum area constraint prevents over-refinement
- Boundary cells should extend 2-5× the investigation depth
- Too few cells → resolution loss; too many → slow computation, memory issues

### 8.8 Coverage / Sensitivity
Model cells with low coverage (cumulative sensitivity) are poorly constrained.
Displaying them at full opacity is misleading — always mask or fade low-coverage
regions using `pg.show(mesh, model, coverage=sens/sens.max())`.

### 8.9 Sign Convention (IP)
IP phase can be reported as positive or negative depending on convention.
pyGIMLi expects **negative** phase values (phase lag). If data has positive
phases, negate them before inversion. Mixing conventions produces nonsensical
Cole-Cole parameters.

---

## 9. Validation Results

### Synthetic ERT Test
- **Setup**: 2D Wenner array, 41 electrodes at 1 m spacing
- **True model**: Two anomalous blocks (100 Ω·m and 1000 Ω·m) in 500 Ω·m background
- **Noise**: 3% Gaussian + 50 µV absolute
- **Result**: Chi² = 1.02, anomalies recovered within 15% of true values
- **Iterations**: 5 (lambda: 20 → 2.5)

### Synthetic SRT Test
- **Setup**: 24 geophones at 2 m spacing, 5 shot points
- **True model**: 3-layer (500, 1500, 3000 m/s)
- **Noise**: 1 ms absolute
- **Result**: Layer boundaries within 10%, velocities within 5%

---

## 10. Calibration / Tuning Parameters

| Priority | Parameter              | Typical Range     | Effect                          |
|----------|------------------------|-------------------|---------------------------------|
| 1        | lambda (regularization)| 1–100             | Smoothness vs. data fit         |
| 2        | relativeError          | 0.01–0.10         | Data weighting                  |
| 3        | absoluteError          | method-dependent  | Noise floor                     |
| 4        | maxIter                | 5–20              | Convergence limit               |
| 5        | zWeight                | 0.2–1.0           | Vertical vs. horizontal smooth  |
| 6        | quality (mesh)         | 30–34             | Minimum triangle angle          |
| 7        | paraMaxCellSize        | site-dependent    | Max cell area in para domain    |
| 8        | paraDX                 | 0.3–1.0           | Horizontal cell refinement      |
| 9        | paraDepth              | 0.3–0.5 × spread | Investigation depth             |
| 10       | robustData             | True/False        | L1 vs. L2 data misfit           |

---

## 11. Common Workflows

### ERT 2D Inversion (Minimal)
```python
import pygimli as pg
from pygimli.physics import ert

data = ert.load("field_data.dat")
mgr = ert.ERTManager(data)
model = mgr.invert(lam=20, verbose=True)
mgr.showResult()
```

### SRT 2D Inversion (Minimal)
```python
import pygimli as pg
from pygimli.physics import traveltime as tt

data = tt.load("picks.sgt")
mgr = tt.TravelTimeManager(data)
model = mgr.invert(lam=50, verbose=True)
mgr.showResult()
```

### Forward Modelling (ERT)
```python
import pygimli as pg
from pygimli.physics import ert

scheme = ert.createData(nElecs=41, schemeName='wa')
mesh = pg.meshtools.createParaMesh2DGrid(scheme.sensors())
data = ert.simulate(mesh, res=100, scheme=scheme, noiseLevel=0.03)
```

---

## 12. File Structure

```
ki/
├── SKILL.md                          # This file
├── knowledge_infrastructure.yaml     # Package schema
├── tools/
│   ├── convert_data_to_gimli.py      # s0: Field data → pyGIMLi format
│   ├── convert_parameters.py         # s2: Petrophysical parameter setup
│   ├── run_pygimli.py                # s3: Execute modelling/inversion
│   └── parse_gimli_output.py         # s4: Results → CSV/metrics
├── docs/
│   ├── s0_data_preparation.md        # Data loading and conversion
│   ├── s1_mesh_generation.md         # Mesh creation guide
│   ├── s2_parameter_setup.md         # Model parameterization
│   ├── s3_forward_inversion.md       # Running forward/inverse problems
│   └── s4_output_analysis.md         # Result extraction and QC
├── diagnostics/
│   └── triplets.yaml                 # 18 symptom→diagnosis→remedy
└── workflow/
    └── workflow.md                   # Auto-generated pipeline
```

---

## 13. Physical Constants (pygimli.physics.constants)

| Constant | Symbol | Value                  | Unit    |
|----------|--------|------------------------|---------|
| Vacuum permeability  | µ₀ | 4π × 10⁻⁷        | H/m     |
| Vacuum permittivity  | ε₀ | 8.854 × 10⁻¹²    | F/m     |
| Speed of light       | c₀ | 2.998 × 10⁸       | m/s     |
| Gravitational const. | G  | 6.674 × 10⁻¹¹    | m³/kg/s²|
| Gravity acceleration | g  | 9.80665            | m/s²    |

---

## 14. Troubleshooting Quick Reference

| Symptom                        | Likely Cause                    | Fix                              |
|--------------------------------|---------------------------------|----------------------------------|
| Chi² >> 1 after convergence    | Error too small or model wrong  | Increase error estimate          |
| Chi² << 1                      | Error too large, overfitting    | Decrease error estimate          |
| Artifacts near electrodes      | Singularity removal off         | Set `sr=True`                    |
| Inversion diverges             | Wrong data transform            | Check TransLogLU bounds          |
| Model looks inverted           | Depth sign convention           | Check z-axis orientation         |
| Mesh generation fails          | Non-planar or overlapping nodes | Clean electrode positions        |
| Out of memory                  | Mesh too fine                   | Increase maxCellSize             |
| Flat velocity model (SRT)      | Lambda too high                 | Reduce lambda                    |
| Negative resistivity           | Linear transform on res data    | Use TransLog or TransLogLU       |
| Import error for pg.core       | pgcore not installed             | `pip install pgcore`             |

---

*Generated by auto_dissect KI builder. Reference: Rücker et al. (2017), Computers & Geosciences.*
