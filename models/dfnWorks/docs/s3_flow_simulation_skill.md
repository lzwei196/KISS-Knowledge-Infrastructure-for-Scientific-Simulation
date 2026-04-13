# Stage 3: Flow Simulation (PFLOTRAN/FEHM/Graph)

## Purpose

Solve steady-state fluid flow through the discrete fracture network to obtain pressure and velocity fields. Three solvers are available:

1. **PFLOTRAN** (default full-physics): Finite volume method on DFN mesh
2. **FEHM**: Alternative finite element flow solver
3. **Graph-based** (no external deps): Pipe-network model on intersection graph

## Prerequisites

### Full-Physics Mode (PFLOTRAN/FEHM)
- Stage 2 completed: mesh generated successfully
- PFLOTRAN or FEHM installed, paths in `~/.dfnworksrc`
- PETSc installed (for PFLOTRAN)
- PFLOTRAN input file (`dfn_explicit.in`) or FEHM configuration

### Graph Mode
- Stage 1 completed: network generated (no mesh needed)
- No external dependencies

## Inputs

### Full-Physics Inputs

| Input | Source | Format | Description |
|-------|--------|--------|-------------|
| full_mesh.inp | Stage 2 | AVS/UCD | DFN mesh |
| full_mesh.uge | Stage 2 | UGE | Voronoi volumes (aperture-corrected) |
| perm.dat | Stage 1 | DAT | Permeability per fracture (m^2) |
| aperture.dat | Stage 1 | DAT | Aperture per fracture (m) |
| dfn_explicit.in | User | PFLOTRAN input | Flow solver configuration |
| Boundary zones | Stage 2 | ZONE | Pressure/flow boundary conditions |

### Graph Mode Inputs

| Input | Source | Format | Description |
|-------|--------|--------|-------------|
| Intersection graph | Stage 1 | Internal | NetworkX graph from DFN |
| pressure_in | User | Pa | Inlet boundary pressure |
| pressure_out | User | Pa | Outlet boundary pressure |
| fluid_viscosity | User (optional) | Pa.s | Default: 8.9e-4 (water 20C) |

## Outputs

### Full-Physics Outputs

| Output | Path | Format | Description |
|--------|------|--------|-------------|
| darcyvel.dat | `<jobname>/` | DAT | Darcy velocity vectors per cell |
| cellinfo.dat | `<jobname>/` | DAT | Cell center coordinates and volumes |
| PFLOTRAN VTK | `<jobname>/` | VTK | Pressure/velocity fields for visualization |

### Graph Mode Outputs

| Output | Path | Format | Description |
|--------|------|--------|-------------|
| graph_flow.hdf5 | `<jobname>/` | HDF5 | Edge properties: velocity, flux, area |
| NetworkX graph G | In memory | Python | Directed graph with flow attributes |

## Procedure

### Option A: PFLOTRAN Flow

```python
DFN.dfn_flow()
# Equivalent to:
# DFN.lagrit2pflotran()    # Convert mesh to PFLOTRAN format
# DFN.pflotran()           # Run PFLOTRAN
# DFN.parse_pflotran_vtk_python()  # Parse VTK output
# DFN.pflotran_cleanup()   # Clean temporary files
```

### Option B: FEHM Flow

```python
DFN.set_flow_solver("FEHM")
DFN.dfn_flow()
```

### Option C: Graph-Based Flow

```python
# Pressures in PASCALS (not MPa, not psi)
pressure_in = 2e6    # 2 MPa = 2,000,000 Pa
pressure_out = 1e6   # 1 MPa = 1,000,000 Pa

G = DFN.run_graph_flow("left", "right", pressure_in, pressure_out)
```

The graph solver:
1. Builds intersection graph from DFN
2. Assigns edge conductances: `C = k * A / (mu * L)`
3. Assembles and solves sparse linear system: `L * p = b`
4. Computes edge fluxes from pressure differences

## Verification

1. **Pressure field**: Monotonically decreasing from inlet to outlet
2. **Mass balance**: Total inflow flux = Total outflow flux (within numerical tolerance)
3. **Velocity range**: Darcy velocities should be physically reasonable (1e-12 to 1e-3 m/s for groundwater)
4. **Effective permeability**: Compare with cubic law estimate: `k_eff ~ (b^3 * n) / (12 * L)`

### Graph Mode Verification

```python
# Check flow statistics
DFN.compute_dQ(G)  # Computes flow channeling density

# Verify pressure gradient
import numpy as np
pressures = [G.nodes[n].get('pressure', 0) for n in G.nodes()]
print(f"Pressure range: {min(pressures):.0f} - {max(pressures):.0f} Pa")
```

## Traps

| Trap | Symptom | Fix | Triplet |
|------|---------|-----|---------|
| Pressure in MPa instead of Pa | Velocity 6 orders too low | Use Pa: 1 MPa = 1e6 Pa | dt_003 |
| Permeability in m/s (K) instead of m^2 (k) | Velocity 7 orders too high | Convert: k = K*mu/(rho*g) | dt_002 |
| No flow path between boundaries | Zero velocity everywhere | Check connectivity, increase p32 | dt_006 |
| PFLOTRAN input format mismatch | PFLOTRAN crashes | Match input file to dfnWorks version | dt_017 |
| Wrong inflow/outflow boundary names | Graph flow returns error | Use "left"/"right"/"top"/"bottom"/"front"/"back" | dt_007 |

## Example

```python
# Graph-based flow example
DFN = DFNWORKS(jobname, ncpu=4)
DFN.params['domainSize']['value'] = [100, 100, 100]
DFN.params['h']['value'] = 0.5
DFN.params['boundaryFaces']['value'] = [0, 0, 1, 1, 0, 0]

DFN.add_fracture_family(shape="ell", distribution="tpl",
    kappa=10, p32=0.5, aspect=1, theta=0, phi=0,
    alpha=2.0, min_radius=5, max_radius=50,
    hy_variable='permeability', hy_function='constant',
    hy_params={"mu": 1e-12})

DFN.make_working_directory(delete=True)
DFN.check_input()
DFN.create_network()

# Flow with 1 MPa pressure gradient (all in Pa!)
G = DFN.run_graph_flow("left", "right", 2e6, 1e6)
```
