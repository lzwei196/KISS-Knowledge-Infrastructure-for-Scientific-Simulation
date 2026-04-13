# S2: Forcing Data and Boundary Conditions

## Purpose

Configure boundary conditions (Dirichlet, Neumann, Robin) and time-varying forcing
data for PorePy simulations. This stage converts external data sources into the
internal format expected by PorePy model mixins.

## Inputs

| Input               | Type                  | Unit      | Description                         |
|---------------------|-----------------------|-----------|-------------------------------------|
| Pressure BC values  | `np.ndarray`          | Pa        | Prescribed pressure on boundaries   |
| Flux BC values      | `np.ndarray`          | m³/s      | Prescribed flow rate on boundaries  |
| Temperature BC      | `np.ndarray`          | K         | Prescribed temperature              |
| Displacement BC     | `np.ndarray`          | m         | Prescribed displacement             |
| Traction BC         | `np.ndarray`          | Pa        | Prescribed stress/traction          |
| Recharge rate       | `float`               | m/s       | Volumetric recharge rate            |
| Time schedule       | `List[float]`         | s         | Time points for transient BCs       |

## Outputs

| Output                  | Type                        | Description                        |
|-------------------------|-----------------------------|------------------------------------|
| BC type array           | `pp.BoundaryCondition`      | Face-wise Dirichlet/Neumann flags  |
| BC value arrays         | `np.ndarray`                | Values at boundary faces           |
| TimeManager             | `pp.TimeManager`            | Time stepping schedule             |

## Procedure

### Step 1: Define boundary condition types

PorePy identifies boundary faces via `domain_boundary_sides()`:

```python
class MyBCs(pp.SinglePhaseFlow):
    def bc_type_darcy_flux(self, sd):
        sides = self.domain_boundary_sides(sd)
        bc = pp.BoundaryCondition(sd)
        # Dirichlet on north/south, Neumann elsewhere
        bc.is_dir[sides.north] = True
        bc.is_dir[sides.south] = True
        return bc
```

### Step 2: Set boundary condition values

```python
    def bc_values_pressure(self, bg):
        values = np.zeros(bg.num_cells)
        sides = self.domain_boundary_sides(bg)
        # High pressure on north (inflow)
        values[sides.north] = 1e6  # 1 MPa in Pa
        # Low pressure on south (outflow)
        values[sides.south] = 0.0
        return values
```

### Step 3: Configure time stepping

```python
# 1-year simulation with daily time steps
time_manager = pp.TimeManager(
    schedule=[0, 3.15576e7],   # 0 to 1 year in seconds
    dt_init=86400,             # 1 day in seconds
    constant_dt=True,
)
model_params["time_manager"] = time_manager
```

### Step 4: Convert external forcing data

Use the `convert_forcing_data.py` tool to convert from common formats:

```bash
python ki/tools/convert_forcing_data.py \
    --input recharge_data.csv \
    --output porepy_forcing.json \
    --pressure-unit MPa \
    --time-unit days \
    --recharge-unit mm/day
```

## Verification

- Verify BC types: `np.sum(bc.is_dir)` should match expected Dirichlet face count
- Pressure values should be physically reasonable (0–100 MPa for subsurface)
- At least one Dirichlet BC required for pressure (otherwise singular system)
- Time schedule must be monotonically increasing
- dt_init must be > 0 and ≤ (schedule[-1] - schedule[0])

## Traps

| ID     | Trap                                        | Consequence                              |
|--------|---------------------------------------------|------------------------------------------|
| dt_002 | Pressure in MPa instead of Pa               | All pressures 1e6× too small             |
| dt_007 | Time step in hours instead of seconds       | Simulation timescale wrong               |
| dt_011 | Units(s≠1) in pp.Units                      | NotImplementedError at runtime           |
| dt_017 | Pure Neumann BCs for pressure               | Singular matrix, solver failure          |

## Example

```python
import numpy as np
import porepy as pp

class PressureDrivenFlow(pp.SinglePhaseFlow):
    def set_domain(self):
        self._domain = pp.Domain({"xmin": 0, "xmax": 100, "ymin": 0, "ymax": 100})

    def set_fractures(self):
        self._fractures = []

    def bc_type_darcy_flux(self, sd):
        sides = self.domain_boundary_sides(sd)
        bc = pp.BoundaryCondition(sd)
        bc.is_dir[sides.west] = True
        bc.is_dir[sides.east] = True
        return bc

    def bc_values_pressure(self, bg):
        values = np.zeros(bg.num_cells)
        sides = self.domain_boundary_sides(bg)
        values[sides.west] = 1e6   # 1 MPa inflow
        values[sides.east] = 0.0   # 0 Pa outflow
        return values

params = {
    "grid_type": "cartesian",
    "meshing_arguments": {"cell_size": 10.0},
    "folder_name": "pressure_flow",
}
model = PressureDrivenFlow(params)
pp.run_stationary_model(model, {})
```
