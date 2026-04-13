# Stage 6: Upscaling and Continuum Coupling

## Purpose

Convert discrete fracture network (DFN) results to equivalent continuum representations for coupling with larger-scale models. Supports upscaled equivalent porous medium (ECPM) and unstructured DFM-to-continuum mapping for integration with basin-scale groundwater models.

## Prerequisites

- Stage 2 completed: mesh generated (required for upscaling)
- Stage 3 completed: flow solution available (required for effective properties)
- For ECPM: mapdfn module available in pydfnworks

## Inputs

| Input | Source | Format | Description |
|-------|--------|--------|-------------|
| DFN mesh | Stage 2 | INP/UGE | Fracture mesh with flow solution |
| Permeability field | Stage 1 | DAT | Per-fracture permeability |
| Aperture field | Stage 1 | DAT | Per-fracture aperture |
| Flow solution | Stage 3 | DAT/VTK | Pressure and velocity fields |
| Continuum grid | User | LaGriT mesh | Target upscaled grid |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Upscaled permeability tensor | DAT | 3x3 tensor per continuum cell |
| Upscaled porosity | DAT | Fracture porosity per cell |
| PFLOTRAN input (ECPM) | IN | Continuum PFLOTRAN simulation |
| DFN-to-continuum map | DAT | Mapping between DFN and continuum cells |

## Procedure

### Option A: UDFM (Unstructured DFN-to-Continuum Mapping)

```python
# Map DFN to a regular continuum grid
DFN.map_to_continuum(l=5.0, orl=1)
# l = cell size (m) for the continuum grid
# orl = oversampling ratio for better resolution

# Upscale properties
DFN.upscale(mat_perm=1e-18, mat_porosity=0.01)
# mat_perm = matrix background permeability (m^2)
# mat_porosity = matrix background porosity
```

### Option B: mapDFN ECPM

```python
# Create ECPM mesh
DFN.mapdfn_ecpm(cell_size=5.0)

# Tag cells that contain fractures
DFN.mapdfn_tag_cells()

# Compute upscaled permeability
DFN.mapdfn_upscale()

# Compute effective permeability tensor
DFN.mapdfn_effective_perm()
```

### Option C: DFM (Discrete Fracture-Matrix) Meshing

```python
# Create combined fracture + matrix mesh
DFN.mesh_dfm()
# Produces a mesh with both fracture and matrix elements
```

## Verification

1. **Mass balance**: Flow through upscaled model matches DFN model
2. **Effective permeability**: Upscaled k_eff matches direct DFN calculation
3. **Porosity range**: Fracture porosity should be small (0.001-0.01 typical)
4. **Tensor symmetry**: Upscaled permeability tensor should be symmetric positive definite
5. **Grid convergence**: Results should converge as continuum cell size decreases

## Traps

| Trap | Symptom | Fix | Triplet |
|------|---------|-----|---------|
| Cell size too large | Misses fracture detail | Reduce l parameter | — |
| Background permeability too high | Matrix dominates DFN flow | Use realistic mat_perm (1e-18 to 1e-15 m^2) | — |
| Wrong coordinate system | Offset between DFN and continuum | Ensure both centered at origin | — |
| Upscaling without flow solution | Zero/uniform permeability field | Run flow before upscaling | — |

## Coupling With Basin Models

The upscaled continuum can be coupled with:
- **PFLOTRAN** (regional groundwater): Direct ECPM input
- **MODFLOW**: Export upscaled K tensor to MODFLOW grid
- **CaMa-Flood**: Provide groundwater-surface water exchange fluxes

### Coupling Workflow

1. Generate DFN for fractured rock zone (this model)
2. Upscale to continuum representation
3. Embed upscaled properties in regional model grid cells
4. Run regional model with enhanced fracture-zone properties

## Example

```python
# Complete upscaling workflow
DFN.make_working_directory(delete=True)
DFN.check_input()
DFN.create_network()
DFN.mesh_network()
DFN.dfn_flow()

# Upscale to 5m continuum cells
DFN.map_to_continuum(l=5.0)
DFN.upscale(mat_perm=1e-18, mat_porosity=0.005)

# The upscaled model can now be used in a basin-scale simulation
print("Upscaling complete. Continuum model ready for coupling.")
```
