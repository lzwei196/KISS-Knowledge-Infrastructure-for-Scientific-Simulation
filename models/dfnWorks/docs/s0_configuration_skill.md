# Stage 0: Domain Configuration and Fracture Family Definition

## Purpose

Configure the 3D domain geometry, define fracture families with statistical distributions, set boundary conditions, and assign hydraulic properties. This stage produces the complete parameter set required by DFNGen (Stage 1). All subsequent stages depend on correct configuration.

## Prerequisites

- Field characterization data: fracture orientations (strike/dip), size distributions (trace length mapping), intensity (p10/p32), and hydraulic properties (packer tests, pumping tests)
- pydfnworks installed (`pip install .` from pydfnworks directory)
- Understanding of site geology: number of fracture sets, dominant orientations, layering

## Inputs

| Parameter | Type | Units | Description |
|-----------|------|-------|-------------|
| domainSize | [x, y, z] | meters | 3D domain dimensions, centered at origin |
| h | float | meters | Minimum feature size (FRAM mesh resolution) |
| boundaryFaces | [6 int] | binary | Which faces enforce connectivity: [top, bot, left, front, right, back] |
| stopCondition | int | — | 0 = stop at nPoly fractures, 1 = stop at p32 targets |
| nPoly | int | — | Total number of fractures (if stopCondition=0) |
| seed | int | — | Random seed (0 = clock-based, >0 = reproducible) |
| keepOnlyLargestCluster | bool | — | Remove disconnected fractures |
| Fracture families | dict | various | Shape, size distribution, orientation, hydraulic props |

## Outputs

- Configured `DFNWORKS` object with all parameters set
- Ready for `check_input()` validation and `create_network()` generation

## Procedure

### Step 1: Initialize DFNWORKS object

```python
from pydfnworks import *
import os

jobname = os.path.join(os.getcwd(), "output")
DFN = DFNWORKS(jobname, ncpu=4)
```

### Step 2: Set domain parameters

```python
# Domain size in METERS (not km, not ft)
DFN.params['domainSize']['value'] = [100, 100, 100]  # 100m cube
DFN.params['h']['value'] = 0.5  # 0.5m mesh resolution

# Boundary faces: flow from left to right
DFN.params['boundaryFaces']['value'] = [0, 0, 1, 1, 0, 0]
```

### Step 3: Define fracture families

```python
DFN.add_fracture_family(
    shape="ell",              # Elliptical fractures
    distribution="tpl",       # Truncated power-law size distribution
    kappa=15.0,               # Fisher concentration (moderate clustering)
    p32=0.5,                  # Fracture intensity: 0.5 m^2/m^3
    aspect=1.0,               # Circular (aspect ratio = 1)
    theta=0.0,                # Trend of pole (degrees)
    phi=45.0,                 # Plunge of pole (degrees)
    alpha=2.5,                # TPL exponent
    min_radius=1.0,           # Minimum radius: 1m
    max_radius=50.0,          # Maximum radius: 50m
    hy_variable='permeability',
    hy_function='semi-correlated',
    hy_params={"alpha": 1e-12, "beta": 0.8, "sigma": 0.5}
)
```

### Step 4: Validate and check input

```python
DFN.check_input()            # Validates all parameters
DFN.print_domain_parameters() # Print summary
```

## Verification

- `check_input()` completes without errors
- No warning about h being too large relative to min_radius
- `print_domain_parameters()` shows expected domain size and family count
- Boundary faces have at least one inflow and one outflow face set to 1

## Traps

| Trap | Symptom | Fix | Triplet |
|------|---------|-----|---------|
| Domain size in km instead of m | Network is 1000x too large | Multiply by 1000 | dt_001 |
| h > min_radius | Mesh generation fails | Ensure h < 0.5 * min_radius | dt_004 |
| No boundary faces set | No-flow solution | Set at least 2 faces to 1 | dt_007 |
| K (m/s) used as permeability (m^2) | Flow velocity 7 orders too high | Convert: k = K*mu/(rho*g) | dt_002 |
| Aperture in um instead of m | Permeability 12 orders too low | Multiply by 1e-6 | dt_005 |

## Example

```python
# Bengbu basin fractured limestone
DFN = DFNWORKS(jobname, ncpu=8)
DFN.params['domainSize']['value'] = [500, 500, 200]  # 500x500x200m block
DFN.params['h']['value'] = 1.0

# Family 1: Sub-horizontal bedding-parallel fractures
DFN.add_fracture_family(shape="rect", distribution="log_normal",
    kappa=50, p32=0.3, theta=0, phi=5,
    log_mean=1.5, log_std=0.5,
    min_radius=2.0, max_radius=100.0,
    hy_variable='permeability', hy_function='constant',
    hy_params={"mu": 5e-13})

# Family 2: Vertical joint set
DFN.add_fracture_family(shape="ell", distribution="tpl",
    kappa=20, p32=0.2, theta=90, phi=80,
    alpha=2.2, min_radius=1.0, max_radius=50.0,
    hy_variable='permeability', hy_function='semi-correlated',
    hy_params={"alpha": 1e-13, "beta": 0.9, "sigma": 1.0})
```
