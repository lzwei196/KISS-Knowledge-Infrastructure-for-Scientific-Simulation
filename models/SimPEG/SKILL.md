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

# SimPEG Knowledge Infrastructure

| Field          | Value                                                       |
|----------------|-------------------------------------------------------------|
| **Package**    | SimPEG KI v1.0                                              |
| **Model**      | SimPEG (Simulation and Parameter Estimation in Geophysics)  |
| **Domain**     | Geophysics (forward modeling and inversion)                 |
| **Language**   | Python (>=3.11)                                             |
| **Authors**    | Cockett, Kang, Heagy, Pidlisecky, Oldenburg                |
| **License**    | MIT                                                         |
| **Repository** | https://github.com/simpeg/simpeg                            |
| **Tools**      | 4 scripts, ~1200 lines                                      |
| **Skill docs** | 5 markdown documents                                        |
| **Triplets**   | 18 diagnostic entries                                       |

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/DTB/SKILL.md` for depth-to-bedrock data.


## 1. Overview

SimPEG is an open-source Python framework for **simulation and gradient-based parameter
estimation** in geophysical applications.  It provides a modular architecture where meshes,
forward simulations, data misfits, regularization, optimization, and inversion directives
are composable objects.

### Supported Geophysical Methods

| Method                        | Module                                      | Dimension  |
|-------------------------------|---------------------------------------------|------------|
| Gravity                       | `simpeg.potential_fields.gravity`            | 1D/2D/3D   |
| Magnetics                     | `simpeg.potential_fields.magnetics`          | 1D/2D/3D   |
| DC Resistivity                | `simpeg.electromagnetics.static.resistivity`| 1D/2D/3D   |
| Induced Polarization (IP)     | `simpeg.electromagnetics.static.induced_polarization` | 1D/2D/3D |
| Spectral IP (SIP)             | `simpeg.electromagnetics.static.spectral_induced_polarization` | 1D/2D/3D |
| Self-Potential (SP)           | `simpeg.electromagnetics.static.self_potential` | 2D/3D |
| Frequency-Domain EM (FDEM)    | `simpeg.electromagnetics.frequency_domain`  | 1D/3D      |
| Time-Domain EM (TDEM)         | `simpeg.electromagnetics.time_domain`       | 1D/3D      |
| Natural Source EM / MT        | `simpeg.electromagnetics.natural_source`    | 1D/3D      |
| VRM                           | `simpeg.electromagnetics.viscous_remanent_magnetization` | 3D |
| Seismic Ray Tomography        | `simpeg.seismic.straight_ray_tomography`    | 2D         |
| Richards Equation (flow)      | `simpeg.flow.richards`                      | 1D/2D/3D   |

### Key Differences from Other Geophysics Codes

- **Inverse-first design**: every simulation exposes `Jvec`, `Jtvec` for gradient-based inversion.
- **Mesh-agnostic**: works with `discretize` TensorMesh, TreeMesh, CylindricalMesh, SimplexMesh.
- **Composable maps**: chain parameter transformations (log, exponential, injection, tile, etc.).
- **Dask support**: distributed forward and sensitivity computations for large-scale 3D problems.

---

## 2. Installation

### Quick Install (pip)

```bash
python -m venv venv && source venv/bin/activate
pip install simpeg
# or with all optional dependencies:
pip install "simpeg[dask,choclo,plotting,sklearn,pandas]"
```

### Developer Install

```bash
git clone https://github.com/simpeg/simpeg.git
cd simpeg
pip install -e ".[tests,docs,style]"
```

### Core Dependencies

| Package      | Version   | Purpose                         |
|--------------|-----------|----------------------------------|
| numpy        | >= 1.22   | Array operations                 |
| scipy        | >= 1.12   | Sparse matrices, linear algebra  |
| discretize   | >= 0.12   | Mesh generation and operators    |
| pymatsolver  | >= 0.3    | Linear solver wrapper            |
| geoana       | >= 0.8.1  | Analytical geophysical functions |
| libdlf       | any       | Hankel/digital-linear-filter     |
| matplotlib   | any       | Plotting                        |

### Verify Installation

```python
import simpeg
print(simpeg.__version__)
from simpeg import simulation, maps, data_misfit, inversion
print("Core modules loaded OK")
```

---

## 3. Pipeline Stages

| Stage | Name                | Tool                        | Description                                         |
|-------|---------------------|-----------------------------|-----------------------------------------------------|
| S1    | Mesh & Survey Setup | `tools/build_mesh.py`       | Create discretize mesh + survey geometry             |
| S2    | Model & Parameters  | `tools/initialize_model.py` | Build starting model, define maps and properties     |
| S3    | Forward Modeling    | (API)                       | Run forward simulation to predict data               |
| S4    | Data Preparation    | (API)                       | Load/create observed data, assign uncertainties      |
| S5    | Inversion Setup     | `tools/run_simpeg.py`       | Combine misfit + regularization + optimization       |
| S6    | Inversion Execution | `tools/run_simpeg.py`       | Run `BaseInversion.run(m0)`                          |
| S7    | Output Parsing      | `tools/parse_results.py`    | Extract recovered model, predicted data, metrics     |
| S8    | Visualization       | `tools/parse_results.py`    | Plot model slices, data comparison, convergence      |
| S9    | Validation          | (manual)                    | Compare to analytical solutions or known models      |

---

## 4. Tools Reference

| #  | Script                    | Lines | Purpose                                            |
|----|---------------------------|-------|----------------------------------------------------|
| T1 | `tools/build_mesh.py`     | ~330  | Mesh generation and survey geometry builder         |
| T2 | `tools/initialize_model.py`| ~300 | Physical property model initializer with unit maps  |
| T3 | `tools/run_simpeg.py`     | ~320  | Forward + inversion execution wrapper               |
| T4 | `tools/parse_results.py`  | ~280  | Output parser: model to CSV, convergence metrics    |

All tools follow the **validate → process → validate** pattern:
1. `validate_inputs()` — check files exist, types correct, units sane
2. `process()` — main computation
3. `validate_outputs()` — verify results are physically reasonable
4. Output: JSON on stdout with `{"status": "success"|"error", ...}`

---

## 5. Unit Trap Table — Critical Domain Knowledge

These are **silent failures** — the model runs but produces wrong results.

| ID     | Trap                                  | Wrong                      | Correct                  | Effect                              |
|--------|---------------------------------------|----------------------------|--------------------------|-------------------------------------|
| dt_001 | Gravity density units                 | g/cm^3 directly            | kg/m^3 or g/cc→SI via map| Factor-of-1000 anomaly error        |
| dt_002 | Magnetic susceptibility vs SI         | CGS susceptibility         | SI susceptibility (×4π)  | Amplitude off by 4π ≈ 12.57        |
| dt_003 | DC resistivity vs conductivity        | Resistivity (Ω·m)          | Conductivity (S/m)       | Inverted model is reciprocal        |
| dt_004 | FDEM frequency vs angular frequency   | ω (rad/s)                  | f (Hz)                   | Phase/amplitude completely wrong    |
| dt_005 | Topography elevation datum            | Depth below surface        | Elevation (m above ref)  | Air cells miscategorized            |
| dt_006 | Receiver component mismatch           | Survey measures Bz         | Simulation returns Hx    | Silently wrong data predicted       |
| dt_007 | nC (nanoTesla) vs T for magnetics     | Data in Tesla              | Data in nanoTesla        | Misfit 10^9 too large              |
| dt_008 | Regularization alpha ratios           | Default alpha_s=alpha_x    | Tune for cell-size ratio | Over-smooth or blocky model         |
| dt_009 | InjectActiveCells background value    | 0.0 for conductivity       | ln(σ) or actual σ_air    | Singular system or air artifacts    |
| dt_010 | Data uncertainty floor too small      | noise_floor=0              | >1-5% of |d|             | Overfit noise, model artifacts      |
| dt_011 | Mesh cell count vs memory             | 1M cells, dense J          | Use TreeMesh or Dask     | OOM crash at sensitivity stage      |
| dt_012 | TileMap index mismatch                | Wrong local-to-global map  | Match tile cell indices   | Corrupted global sensitivity       |

---

## 6. Skill Knowledge by Stage

### S1 — Mesh & Survey Setup

The mesh discretizes the Earth volume.  Survey defines source and receiver locations.

**Mesh types** (from `discretize`):
- `TensorMesh` — regular grid, fast, memory-heavy for 3D
- `TreeMesh` (OcTree) — adaptive refinement near data, recommended for 3D
- `CylindricalMesh` — axially symmetric problems (boreholes, TEM loops)
- `SimplexMesh` — unstructured tetrahedral, complex geometry

**Common pitfall**: Mesh must extend far enough beyond the survey footprint
(≥2–3× target depth) to avoid boundary effects.  Padding cells should
grow geometrically (factor 1.3–1.5).

### S2 — Model & Physical Properties

The model vector `m` is mapped to physical properties via `simpeg.maps`:

```python
# Example: log-conductivity model with active cells
model_map = maps.ExpMap(nP=n_active) * maps.InjectActiveCells(mesh, active_ind, np.log(1e-8))
simulation.sigma_map = model_map
```

**Key maps and when to use them:**
| Map               | Use case                               |
|--------------------|----------------------------------------|
| `IdentityMap`      | Model IS the physical property          |
| `ExpMap`           | Model in log-space, property positive  |
| `LogMap`           | Property in log-space                  |
| `ReciprocalMap`    | Resistivity ↔ conductivity             |
| `InjectActiveCells`| Exclude air/inactive cells             |
| `TileMap`          | Map local tile model to global mesh    |
| `ChiMap`           | Susceptibility → permeability          |
| `Wires`            | Split model vector for multiple props  |

### S3 — Forward Modeling

Every simulation has `sim.dpred(m)` → predicted data vector and
`sim.fields(m)` → full field solution on the mesh.

**Performance considerations:**
- Gravity/magnetics: integral formulation, no PDE solve, but dense J matrix
- DC/EM: PDE-based, sparse systems, factorization dominates cost
- Use `store_sensitivities="forward_only"` to avoid storing full J

### S4 — Data Preparation

```python
data_obj = data.Data(survey, dobs=observed_data,
                     relative_error=0.05,   # 5% of |d|
                     noise_floor=1e-3)       # absolute floor
```

**Uncertainty formula**: `std_dev = sqrt(noise_floor^2 + (relative_error * |dobs|)^2)`

### S5 — Inversion Setup

```python
dmis = data_misfit.L2DataMisfit(data=data_obj, simulation=sim)
reg = regularization.WeightedLeastSquares(mesh, active_cells=active_ind)
opt = optimization.InexactGaussNewton(maxIter=20, maxIterCG=30)
inv_prob = inverse_problem.BaseInvProblem(dmis, reg, opt)
```

**Trade-off parameter β**: controls data-fit vs model-smoothness.
Use `directives.BetaEstimate_ByEig` for automatic initial estimate.

### S6 — Inversion Execution

```python
directives_list = [
    directives.BetaEstimate_ByEig(beta0_ratio=1e0),
    directives.TargetMisfit(),
    directives.BetaSchedule(coolingFactor=5, coolingRate=1),
]
inv = inversion.BaseInversion(inv_prob, directiveList=directives_list)
m_recovered = inv.run(m0)
```

### S7 — Output Parsing

Recovered model is a numpy array matching the mesh cells.
Map it back to physical property space:

```python
physical_property = model_map * m_recovered
mesh.plot_slice(physical_property, normal='Y', ind=slice_index)
```

---

## Output Description

SimPEG's `inv.run(m0)` returns the recovered model vector as a numpy array with one value per active mesh cell, representing the inverted physical property (e.g., density in kg/m^3, conductivity in S/m, susceptibility in SI). The predicted data vector is obtained via `sim.dpred(m_recovered)`. Use `model_map * m_recovered` to transform from model space back to physical property space. The `parse_results.py` tool exports: (1) the recovered model as a CSV with columns `x, y, z, property_value`, (2) a convergence log with iteration number, data misfit (phi_d), regularization (phi_m), and trade-off parameter (beta), and (3) optional model-slice plots and observed-vs-predicted data comparisons.

---

## 7. Calibration / Tuning Parameters

| Priority | Parameter                 | Typical Range         | Effect                              |
|----------|---------------------------|-----------------------|-------------------------------------|
| 1        | `beta0_ratio`             | 1e-2 – 1e2           | Initial trade-off aggressiveness    |
| 2        | `coolingFactor`           | 2 – 10               | How fast β decreases per iteration  |
| 3        | `alpha_s / alpha_x,y,z`  | 1e-4 – 1e2           | Smallness vs smoothness weighting   |
| 4        | `maxIter`                 | 10 – 50              | Total inversion iterations          |
| 5        | `maxIterCG`               | 10 – 100             | CG iterations per Gauss-Newton step |
| 6        | `irls_threshold`          | 1e-2 – 1e-4          | IRLS convergence threshold          |
| 7        | `reference_model`         | problem-specific      | Drives model toward known geology   |
| 8        | `upper_bound/lower_bound` | physical constraints  | Prevent non-physical values         |

---

## 8. Diagnostic Triplets Summary

18 triplets organized by failure domain:

| Domain              | Count | IDs                    |
|---------------------|-------|------------------------|
| unit_conversion     | 5     | dt_001 – dt_004, dt_007|
| parameter_format    | 3     | dt_005, dt_006, dt_012 |
| numerical_stability | 3     | dt_009, dt_010, dt_011 |
| convergence         | 3     | dt_013, dt_014, dt_015 |
| silent_error        | 2     | dt_008, dt_016         |
| runtime             | 2     | dt_017, dt_018         |

See `diagnostics/triplets.yaml` for full symptom → diagnosis → remedy chains.

---

## 9. Quick Start — Gravity Inversion Example

```bash
# 1. Create venv and install
python -m venv simpeg_env && source simpeg_env/bin/activate
pip install simpeg discretize matplotlib

# 2. Build mesh and survey
python tools/build_mesh.py \
  --method gravity \
  --survey-file survey_locs.csv \
  --nx 40 --ny 40 --nz 20 \
  --padding 6 --pad-factor 1.3 \
  --output mesh_config.json

# 3. Initialize model
python tools/initialize_model.py \
  --mesh-config mesh_config.json \
  --property density \
  --background 0.0 \
  --bounds "-1.0,1.0" \
  --map-type identity \
  --output model_config.json

# 4. Run inversion
python tools/run_simpeg.py \
  --mode inversion \
  --method gravity \
  --mesh-config mesh_config.json \
  --model-config model_config.json \
  --data-file gravity_data.csv \
  --relative-error 0.02 \
  --noise-floor 0.001 \
  --max-iter 30 \
  --output results/

# 5. Parse and plot results
python tools/parse_results.py \
  --results-dir results/ \
  --mesh-config mesh_config.json \
  --output-csv recovered_model.csv \
  --plot convergence,model_slice
```

---

## 10. Coupling Points

SimPEG interfaces with:

| External Package | Purpose                              | Notes                        |
|------------------|--------------------------------------|------------------------------|
| `discretize`     | Mesh generation and operators        | Required, co-developed       |
| `geoana`         | Analytical solutions for validation  | Dipole, sphere, layered      |
| `pymatsolver`    | Linear system solvers                | Wraps Pardiso, Mumps, scipy  |
| `choclo`         | Optimized gravity/magnetic kernels   | Numba-compiled               |
| `dask`           | Distributed computing                | Parallel tiles/frequencies   |

---

## 11. Data Requirements

| Data Type            | Format                  | Units                   | Notes                      |
|----------------------|-------------------------|-------------------------|----------------------------|
| Survey locations     | CSV (x, y, z)           | meters (SI)             | Elevation, not depth       |
| Gravity observations | CSV or numpy array      | mGal (1e-5 m/s^2)      | Free-air or Bouguer        |
| Magnetic observations| CSV or numpy array      | nT (1e-9 T)            | Total field anomaly        |
| DC apparent resist.  | UBC format or CSV       | Ω·m (observed)          | Transmitter-receiver pairs |
| EM data (FDEM)       | CSV (freq, real, imag)  | A/m or V/m              | Per-frequency              |
| EM data (TDEM)       | CSV (time, dB/dt)       | V/m^2 or T/s            | Per-time-gate              |
| Topography           | CSV (x, y, z)           | meters elevation        | Reference datum matters    |

---

## 12. File Structure

```
ki/
├── SKILL.md                          # This file — main entry point
├── tools/
│   ├── build_mesh.py                 # S1: mesh + survey builder
│   ├── initialize_model.py           # S2: model parameter setup
│   ├── run_simpeg.py                 # S5-S6: execution wrapper
│   └── parse_results.py             # S7-S8: output parser + plots
├── docs/
│   ├── s1_mesh_survey_setup.md       # Mesh and survey design
│   ├── s2_model_parameters.md        # Physical properties and maps
│   ├── s3_forward_modeling.md        # Forward simulation details
│   ├── s4_inversion_setup.md         # Inversion configuration
│   └── s5_output_analysis.md         # Parsing, visualization, QC
└── diagnostics/
    └── triplets.yaml                 # 18 symptom→diagnosis→remedy entries
```

---

## 13. References

- Cockett, R., Kang, S., Heagy, L. J., Pidlisecky, A., & Oldenburg, D. W. (2015).
  SimPEG: An open source framework for simulation and gradient based parameter
  estimation in geophysical applications. *Computers & Geosciences*, 85, 166–176.
- https://simpeg.xyz — official documentation and tutorials
- https://discretize.simpeg.xyz — discretize mesh documentation
