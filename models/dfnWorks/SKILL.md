---
name: dfnworks
description: >-
  dfnWorks discrete fracture network framework (Hyman et al. 2015, Computers & Geosciences
  84:10-19), graph-mode flow/transport branch (dfnGraph, v2.2+). Covers Stochastic and
  deterministic generation of 3D discrete fracture networks in fractured rock; Conforming
  Delaunay meshing of the fracture network via FRAM + LaGriT (full-physics path). Use when
  the task involves running, configuring, calibrating or interpreting dfnWorks.
---

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

# dfnWorks v2.10.0 — Knowledge Infrastructure

**Package**: `hydrocraft-dfnworks` v1.0.0
**Model**: dfnWorks v2.10.0 (DFNGen v2.3, DFNTrans, pydfnworks)
**Created by**: LANL EES-16 (Jeffrey Hyman, Daniel Livingston, Satish Karra)
**Last updated**: 2026-03-25
**Stats**: 4 tools | 6 skill documents | 17 diagnostic triplets | ~2,500 lines of validated Python
**Validation status**: `development_validated` (graph-based flow/transport on 3-family TPL network)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for recharge forcing documentation.
See `data_ki/GLHYMPS/SKILL.md` for hydrogeology data.
See `data_ki/FanWTD/SKILL.md` for water table depth.
See `data_ki/GRACE/SKILL.md` for GRACE TWS validation data.


## Overview

This knowledge infrastructure enables autonomous simulation of subsurface flow and transport through discrete fracture networks (DFNs) using dfnWorks. The 4 validated tools replace manual input-file preparation with a Python pipeline that integrates fracture network generation, meshing, flow simulation, and particle tracking.

**What dfnWorks does**: A computational suite for modeling flow and transport in 3D fracture networks:
- Stochastic generation of 3D discrete fracture networks (ellipses, rectangles, polygons)
- Conforming Delaunay triangulation meshing via LaGriT
- Steady-state flow simulation via PFLOTRAN or FEHM (or graph-based solver)
- Lagrangian particle tracking for transport (DFNTrans or graph-based)
- Graph-based flow and transport (no external solver required)
- Upscaled continuum representations (ECPM, UDFM)
- Stress-dependent aperture modeling
- Network pruning and backbone extraction
- Well intersection and injection/extraction modeling

**Key difference from other HydroCraft models**: dfnWorks operates on fractured rock (discrete fractures in 3D space), not porous media continuum. It requires external tools (LaGriT for meshing, PFLOTRAN/FEHM for flow) for full-physics runs, but includes a self-contained graph-based solver for rapid flow and transport without external dependencies.

---

## Installation

### External Dependencies (required for full-physics mode)

```
DFNGen v2.3:   C++ fracture network generator (compiled from source via make)
DFNTrans:      C particle tracker (compiled from source via make)
LaGriT v3.3:   Meshing toolbox (https://lagrit.lanl.gov)
PFLOTRAN:      Subsurface flow solver (http://pflotran.org)
FEHM:          Subsurface multiphase flow (https://fehm.lanl.gov)
PETSc:         Parallel toolkit for PFLOTRAN
```

### Python Dependencies

```
numpy, h5py, scipy, matplotlib, networkx, fpdf, pyvista,
mplstereonet, seaborn, pyvtk, mpmath
```

### Graph-Only Mode (no external dependencies)

```
pydfnworks only: pip install .
Sufficient for: DFN generation + graph-based flow + graph-based transport
Not available: LaGriT meshing, PFLOTRAN/FEHM flow, DFNTrans particle tracking
```

### Configuration

Paths are set via `~/.dfnworksrc` (JSON):
```json
{
    "dfnworks_PATH": "/path/to/dfnWorks/",
    "PETSC_DIR": "/path/to/petsc",
    "PETSC_ARCH": "arch-linux-c-opt",
    "PFLOTRAN_EXE": "/path/to/pflotran",
    "LAGRIT_EXE": "/path/to/lagrit",
    "FEHM_EXE": "/path/to/fehm"
}
```

### Test Example

```
examples/graph_transport/    # Graph-based flow + transport (no external deps)
  driver.py                  # Python driver script
  output/                    # Generated DFN output
```

---

## Pipeline (7 Stages)

| # | Stage | Tool(s) / Method | Description |
|---|-------|-------------------|-------------|
| 0 | Configuration | Python driver | Define domain, fracture families, hydraulic properties |
| 1 | Network generation | `DFN.create_network()` → DFNGen | Stochastic fracture placement in 3D domain |
| 2 | Meshing | `DFN.mesh_network()` → LaGriT | Conforming Delaunay triangulation of fractures |
| 3 | Flow simulation | `DFN.dfn_flow()` → PFLOTRAN/FEHM | Steady-state pressure/velocity on mesh |
| 3a | Graph flow | `DFN.run_graph_flow()` | Graph-based flow (no external solver) |
| 4 | Transport | `DFN.dfn_trans()` → DFNTrans | Lagrangian particle tracking |
| 4a | Graph transport | `DFN.run_graph_transport()` | Graph-based particle tracking |
| 5 | Post-processing | Python analysis | Breakthrough curves, visualization, upscaling |
| 6 | Coupling | `map_to_continuum` / `upscale` | DFN → continuum equivalent porous medium |

### Dependencies

- Stage 1 depends on Stage 0 (parameters must be set)
- Stage 2 depends on Stage 1 (fractures must exist) — **not needed for graph mode**
- Stage 3 depends on Stage 2 (mesh must exist)
- Stage 3a depends on Stage 1 only (graph mode bypasses meshing)
- Stage 4 depends on Stage 3 (flow solution required)
- Stage 4a depends on Stage 3a (graph flow required)
- Stage 5 depends on Stage 4 or 4a
- Stage 6 depends on Stage 2

---

## Tools Reference

| Tool | Stage | Script Path | Lines | Purpose |
|------|-------|-------------|------:|---------|
| `convert_fracture_input` | s0 | `tools/convert_fracture_input.py` | 380 | Convert field survey data to dfnWorks fracture families |
| `convert_hydraulic_params` | s0 | `tools/convert_hydraulic_params.py` | 320 | Convert hydraulic conductivity/transmissivity to dfnWorks format |
| `run_dfnworks` | s1-s4a | `tools/run_dfnworks.py` | 450 | Execute dfnWorks pipeline (gen → flow → transport) |
| `parse_dfnworks_output` | s5 | `tools/parse_dfnworks_output.py` | 380 | Extract breakthrough curves, flow rates, travel times to CSV |

**Total**: ~1,530 lines of validated Python

---

## Critical Domain Knowledge

### 1. All spatial dimensions in meters (dk_001)

dfnWorks uses SI units exclusively. Domain size, fracture radii, apertures, and mesh resolution (`h`) are all in **meters**. Field data often arrives in cm, mm, or ft — failure to convert produces networks with wrong scale.

**Trap**: A 10 km × 10 km domain must be specified as `[10000, 10000, 10000]`, not `[10, 10, 10]`. An aperture of 100 μm must be `1e-4`, not `100`.

**Impact**: Domain scale errors propagate to all downstream calculations (permeability, flow rate, travel time).

### 2. Permeability in m², not hydraulic conductivity in m/s (dk_002)

dfnWorks uses intrinsic permeability (m²), not hydraulic conductivity (m/s). The cubic law default is `k = b²/12` where `b` is aperture in meters. Field data often reports K (m/s) which must be converted: `k = K × μ / (ρ × g)`.

**Conversion**: K=1e-5 m/s → k = 1e-5 × 8.9e-4 / (997 × 9.81) ≈ 9.1e-13 m²

**Impact**: Using K values directly as k overestimates permeability by ~7 orders of magnitude.

### 3. Pressure in Pascals, not MPa or psi (dk_003)

Graph-based flow solver expects pressure in Pa. A 1 MPa pressure gradient must be entered as `1e6`, not `1`. PFLOTRAN input files also use Pa.

**Impact**: Wrong pressure units produce velocities off by 3-6 orders of magnitude.

### 4. Fracture intensity p32 in 1/m (dk_004)

p32 (fracture area per unit volume) has units 1/m. Typical field values range 0.01-10 /m. The `stopCondition` parameter controls whether generation stops at a fixed fracture count (`nPoly`) or at a target p32.

**Impact**: p32 values outside physical range produce unrealistic networks (too sparse or too dense to mesh).

### 5. Fisher concentration kappa controls orientation scatter (dk_005)

The Fisher distribution parameter kappa controls how tightly fractures cluster around the mean orientation. kappa=0 is uniform random; kappa=1 is broad scatter; kappa=100 is nearly parallel. Field data from scanlines or boreholes must be converted to Fisher kappa.

**Impact**: kappa too low creates unrealistic random networks; kappa too high creates parallel non-intersecting fractures.

### 6. Mesh resolution h must be smaller than smallest fracture (dk_006)

The FRAM parameter `h` (minimum feature size) must be smaller than the smallest fracture radius. If `h > min_radius`, small fractures cannot be resolved and meshing fails or produces degenerate elements.

**Rule**: `h < 0.5 × min_radius` (minimum), `h < 0.1 × min_radius` (recommended)

**Impact**: LaGriT mesh generation fails silently or produces meshes with zero-volume cells.

### 7. Aperture-permeability relationship (dk_007)

The cubic law relates aperture to permeability: `k = b²/12`. dfnWorks supports three hydraulic property assignment modes:
- **constant**: Single value for all fractures in family
- **correlated**: k = alpha × r^beta (radius-dependent)
- **semi-correlated**: log(k) = log(alpha × r^beta) + N(0, sigma)

**Trap**: Using `hy_function='constant'` with `hy_params={"mu": <value>}` where value is hydraulic conductivity instead of permeability.

### 8. Boundary face numbering convention (dk_008)

`boundaryFaces` uses a 6-element list: [top, bottom, left_w, front_n, right_e, back_s]. Value 1 means "enforce fracture connectivity to this face." Flow requires at least one inflow and one outflow face.

**DFNTrans convention**: in-flow-boundary and out-flow-boundary use 1-based indexing: 1=top, 2=bottom, 3=left_w, 4=front_n, 5=right_e, 6=back_s.

**Impact**: Wrong boundary specification produces no-flow networks or DFNTrans crashes.

### 9. Graph mode vs full-physics mode trade-offs (dk_009)

Graph-based flow/transport is 100-1000x faster but assumes: (a) flow is 1D along intersection segments, (b) no matrix diffusion in the basic mode (TDRW extension available), (c) complete mixing at intersections. Full-physics mode resolves 2D flow on fracture planes.

**When to use graph mode**: Sensitivity analysis, uncertainty quantification, rapid screening.
**When to use full-physics**: Detailed spatial predictions, matrix diffusion, reactive transport.

---

## Unit Trap Table

| Parameter | dfnWorks Unit | Common Field Unit | Conversion | Trap ID |
|-----------|--------------|-------------------|------------|---------|
| Domain size | m | km, ft | ×1000, ×0.3048 | dk_001 |
| Fracture radius | m | cm, ft | ÷100, ×0.3048 | dk_001 |
| Aperture | m | μm, mm | ×1e-6, ×1e-3 | dk_001 |
| Mesh resolution (h) | m | cm | ÷100 | dk_006 |
| Permeability | m² | mD, cm² | ×9.869e-16, ×1e-4 | dk_002 |
| Hydraulic conductivity | m/s (convert to m²) | cm/s, ft/day | see dk_002 | dk_002 |
| Transmissivity | m²/s | m²/day | ÷86400 | dk_002 |
| Pressure | Pa | MPa, psi, m H₂O | ×1e6, ×6894.76, ×9810 | dk_003 |
| Viscosity | Pa·s | cP | ×1e-3 | dk_003 |
| Density | kg/m³ | g/cm³ | ×1000 | dk_003 |
| p32 intensity | 1/m | 1/ft | ×3.281 | dk_004 |
| Orientation angles | degrees (default) | radians | ×180/π | dk_005 |
| Diffusivity | m²/s | cm²/s | ×1e-4 | dk_007 |
| Time | seconds | minutes, hours, days, years | ×60, ×3600, ×86400, ×3.156e7 | — |

---

## Validation

### Test Case: 3-Family TPL Network (Graph Mode)

- **Domain**: 400 m × 50 m × 50 m
- **Fracture families**: 3 ellipse families, TPL distribution (alpha=1.8, r=[10,20] m)
- **p32 per family**: 0.25 /m
- **Permeability**: Constant 2e-12 m² (families 1-2), 3e-12 m² (family 3)
- **Boundary conditions**: P_in = 2 MPa (left), P_out = 1 MPa (right)
- **Particles**: 10,000
- **Mode**: Graph-based flow and transport

### Key Findings

1. Network generates successfully with ~150-300 fractures depending on seed
2. Graph flow solver produces monotonically decreasing pressure from inlet to outlet
3. Breakthrough curve shows characteristic power-law tailing from network heterogeneity
4. Median travel time ~10⁴ s for 400 m transport distance
5. Flow channeling observed: top 10% of fractures carry >50% of flux
6. Runtime: <30 seconds for generation + graph flow + 10⁴ particles

---

## Calibration Parameters

| Priority | Parameter | Range | Controls | Sensitivity |
|----------|-----------|-------|----------|-------------|
| 1 | Permeability (k) | 1e-15 – 1e-8 m² | Flow rate, velocity | Very high |
| 2 | Aperture (b) | 1e-6 – 1e-2 m | Flow rate (cubic law) | Very high |
| 3 | p32 intensity | 0.01 – 10 /m | Network connectivity | High |
| 4 | Size distribution params | Model-dependent | Fracture size range | High |
| 5 | Fisher kappa | 0.1 – 100 | Orientation clustering | Medium |
| 6 | Matrix porosity (TDRW) | 0.001 – 0.3 | Diffusion retardation | Medium |
| 7 | Matrix diffusivity (TDRW) | 1e-12 – 1e-9 m²/s | Matrix interaction | Medium |

---

## Data Requirements

| Data | Source | Required | Notes |
|------|--------|----------|-------|
| Fracture orientations | Borehole/outcrop scanline | Yes | Strike/dip or trend/plunge |
| Fracture size distribution | Trace length mapping | Yes | TPL, lognormal, or exponential fit |
| Fracture intensity (p32/p10) | Borehole fracture count | Yes | p10 (count/m) convertible to p32 |
| Hydraulic properties | Packer tests, pumping tests | Yes | K or T, convert to k (m²) |
| Domain geometry | Site characterization | Yes | 3D bounding box in meters |
| Boundary pressures | Head measurements | For flow | Convert head to Pa |
| Matrix properties | Core samples | For TDRW | Porosity, diffusivity |

---

## Quick Start

### Minimal Graph-Based Example

```python
from pydfnworks import *
import os

src_path = os.getcwd()
jobname = f"{src_path}/output"

DFN = DFNWORKS(jobname, ncpu=4)

# 10m cube domain
DFN.params['domainSize']['value'] = [10, 10, 10]
DFN.params['h']['value'] = 0.1
DFN.params['boundaryFaces']['value'] = [0, 0, 1, 1, 0, 0]

# One fracture family: rectangles, exponential size distribution
DFN.add_fracture_family(shape="rect", distribution="exp",
                        kappa=10, probability=1,
                        exp_mean=2.5, min_radius=1.0, max_radius=5.0,
                        theta=0, phi=0,
                        hy_variable='permeability',
                        hy_function='constant',
                        hy_params={"mu": 1e-12})

DFN.make_working_directory(delete=True)
DFN.check_input()
DFN.create_network()

# Graph-based flow (no PFLOTRAN/LaGriT needed)
G = DFN.run_graph_flow("left", "right", 2e6, 1e6)
DFN.run_graph_transport(G, 1000, "partime", "frac_seq")
```

### Full-Physics Example

```python
DFN = DFNWORKS(jobname, dfnFlow_file="dfn_explicit.in",
               dfnTrans_file="PTDFN_control.dat", ncpu=8)
# ... set params and families ...
DFN.make_working_directory(delete=True)
DFN.check_input()
DFN.create_network()
DFN.mesh_network()       # Requires LaGriT
DFN.dfn_flow()           # Requires PFLOTRAN or FEHM
DFN.dfn_trans()           # Requires DFNTrans
```

---

## Output Description

dfnWorks produces outputs across its pipeline stages: (1) network generation writes fracture coordinates and properties to `radii.dat`, `normal_vectors.dat`, `translations.dat`, and `connectivity.dat` in the working directory; (2) the flow solver (PFLOTRAN or graph-based) writes pressure and velocity fields -- graph flow stores results in a NetworkX graph object with edge-level flow rates (m^3/s) and node-level pressures (Pa); (3) transport produces particle arrival times in `partime_file.dat` (one travel time per particle, in seconds) and fracture sequence files. Use `parse_dfnworks_output.py` to extract breakthrough curves (cumulative particle arrivals vs time), total flow rate through the network, and travel time statistics (median, mean, variance) to CSV.

---

## Diagnostic Triplets Summary

| ID | Severity | Domain | Summary |
|----|----------|--------|---------|
| dt_001 | silent | unit_conversion | Domain size in wrong units (km instead of m) |
| dt_002 | silent | unit_conversion | Hydraulic conductivity used as permeability |
| dt_003 | silent | unit_conversion | Pressure in MPa instead of Pa |
| dt_004 | fatal | parameter_format | h larger than min fracture radius |
| dt_005 | silent | unit_conversion | Aperture in μm instead of m |
| dt_006 | fatal | runtime | No connected path between boundary faces |
| dt_007 | degraded | parameter_format | Wrong boundaryFaces specification |
| dt_008 | silent | silent_error | kappa too low produces random network |
| dt_009 | fatal | dependency | DFNGen binary version mismatch |
| dt_010 | fatal | path_resolution | Missing ~/.dfnworksrc or wrong paths |
| dt_011 | degraded | runtime | p32 target unreachable for domain size |
| dt_012 | silent | unit_conversion | Diffusivity in cm²/s instead of m²/s |
| dt_013 | fatal | runtime | LaGriT meshing fails on degenerate triangles |
| dt_014 | silent | silent_error | Zero-aperture fractures in mesh |
| dt_015 | degraded | parameter_format | Inconsistent fracture family count |
| dt_016 | silent | silent_error | Flux-weighted particles miss low-flow paths |
| dt_017 | fatal | dependency | PFLOTRAN input file format mismatch |

**Silent errors**: 7/17 (41%) — model runs but produces wrong results

---

## File Structure

```
ki/
  SKILL.md                              # This file
  tools/
    convert_fracture_input.py           # Field data → fracture families
    convert_hydraulic_params.py         # K/T → permeability (m²)
    run_dfnworks.py                     # Execution wrapper
    parse_dfnworks_output.py            # Output → CSV
  docs/
    s0_configuration_skill.md           # Domain and family setup
    s1_network_generation_skill.md      # DFNGen fracture generation
    s2_meshing_skill.md                 # LaGriT mesh generation
    s3_flow_simulation_skill.md         # PFLOTRAN/FEHM/graph flow
    s4_transport_skill.md               # DFNTrans/graph transport
    s5_postprocessing_skill.md          # Analysis and visualization
  diagnostics/
    triplets.yaml                       # 17 symptom→diagnosis→remedy entries
```
