# S3 — Forward Modeling

## Purpose

Compute synthetic geophysical data from a known Earth model using SimPEG's
forward simulation engine.  Forward modeling is used to: (1) generate synthetic
data for testing inversion workflows, (2) validate survey design, and
(3) check that the simulation setup produces physically reasonable responses.

## Inputs

| Input          | Format            | Units                    | Required |
|----------------|-------------------|--------------------------|----------|
| Mesh           | discretize object | meters                   | Yes      |
| Survey         | SimPEG Survey     | method-specific          | Yes      |
| Model vector   | numpy array (n,)  | model space              | Yes      |
| Model map      | SimPEG Map        | —                        | Yes      |
| Active cells   | bool array        | —                        | Yes      |

## Outputs

| Output         | Format            | Units                    |
|----------------|-------------------|--------------------------|
| Predicted data | numpy array (nD,) | method-specific          |
| Fields         | SimPEG Fields     | mesh-based field values  |

## Procedure

1. **Create simulation** with the appropriate method module:
   ```python
   # Gravity
   from simpeg.potential_fields import gravity
   sim = gravity.simulation.Simulation3DIntegral(
       mesh, survey=survey, rhoMap=model_map,
       active_cells=active, store_sensitivities="forward_only"
   )

   # DC Resistivity
   from simpeg.electromagnetics.static import resistivity as dc
   sim = dc.simulation.Simulation3DNodal(
       mesh, survey=survey, sigmaMap=model_map
   )
   ```

2. **Run forward simulation**:
   ```python
   dpred = sim.dpred(m)       # predicted data vector
   fields = sim.fields(m)     # full field solution (optional)
   ```

3. **Add synthetic noise** for testing:
   ```python
   from simpeg.data import SyntheticData
   data = sim.make_synthetic_data(
       m, relative_error=0.05, noise_floor=0.001, add_noise=True
   )
   dobs = data.dobs
   ```

4. **Inspect data for sanity**:
   - Gravity: typical range 0.01 – 100 mGal for near-surface targets
   - Magnetics: typical range 1 – 500 nT for susceptibility anomalies
   - DC: apparent resistivity should be in reasonable range for geology

## Verification

- [ ] dpred has no NaN or Inf values
- [ ] Data magnitude is physically reasonable for the method
- [ ] Anomaly is centered over the model target (not shifted)
- [ ] Changing the model changes the data (sensitivity check)
- [ ] For EM: real and imaginary parts have correct sign/phase

## Traps

| Trap | Description | Consequence |
|------|-------------|-------------|
| **dt_006** | Receiver component mismatch (Bz vs Hx vs tmi) | Data is for wrong field component — silent |
| **dt_007** | Magnetic data in Tesla instead of nanoTesla | Values are 10^9 too small, misfit huge |
| **dt_004** | FDEM: frequency in rad/s instead of Hz | Phase/amplitude completely wrong |
| **dt_011** | store_sensitivities="ram" on large mesh | OOM when computing full J matrix |
| Zero model | m0 = 0 everywhere | dpred = 0 for linear problems — not useful |

## Example

```python
import numpy as np
from discretize import TensorMesh
from simpeg.potential_fields import gravity
from simpeg import maps
from simpeg.utils import model_builder

# Create mesh
hx = np.ones(40) * 25.0
hy = np.ones(40) * 25.0
hz = np.ones(20) * 25.0
mesh = TensorMesh([hx, hy, hz], origin=[-500, -500, -500])

# All cells active
active = np.ones(mesh.n_cells, dtype=bool)
model_map = maps.IdentityMap(nP=mesh.n_cells)

# Create density model with anomalous block
model = np.zeros(mesh.n_cells)
block_ind = model_builder.get_indices_block(
    np.array([-100, -100, -200]),
    np.array([100, 100, -50]),
    mesh.cell_centers
)
model[block_ind] = 0.5  # 500 kg/m^3 density contrast

# Survey: 21x21 grid at surface
rx_locs = np.column_stack([
    np.tile(np.linspace(-400, 400, 21), 21),
    np.repeat(np.linspace(-400, 400, 21), 21),
    np.zeros(441)
])
rx = gravity.receivers.Point(rx_locs, components="gz")
src = gravity.sources.SourceField([rx])
survey = gravity.survey.Survey([src])

# Simulation and forward
sim = gravity.simulation.Simulation3DIntegral(
    mesh, survey=survey, rhoMap=model_map,
    active_cells=active, store_sensitivities="forward_only"
)
dpred = sim.dpred(model)
print(f"Gravity: min={dpred.min():.4f}, max={dpred.max():.4f} mGal")
```
