# Skill: Component Assembly and Coupling (Stage 4)

## Purpose

Instantiate Landlab process components and assemble them into a coupled
simulation. Component order in the time loop is critical: flow routing MUST
precede erosion, and some components create fields that others require.
Incorrect ordering produces zero fields and silent wrong answers.

## Inputs

| Input | Format | Units | Source |
|-------|--------|-------|--------|
| Configured `ModelGrid` | Python object | — | Stage 1–3 |
| Component parameters | dict/YAML | mixed | Stage 3 / calibration |
| Timestep | float | yr (typical) | User choice |

## Outputs

| Output | Format | Location | Description |
|--------|--------|----------|-------------|
| List of initialized components | Python objects | memory | Ready to call `run_one_step()` |
| All required fields populated | float arrays | at_node/at_link | Initialized to zero or input values |

## Procedure

### 1. Standard Landscape Evolution Model Assembly

The canonical component order for a stream-power + diffusion LEM:

```python
from landlab import RasterModelGrid
from landlab.components import (
    FlowAccumulator,
    StreamPowerEroder,
    LinearDiffuser,
)

mg = RasterModelGrid((50, 50), xy_spacing=100.0)
z = mg.add_zeros("topographic__elevation", at="node")

# CRITICAL ORDER: FlowAccumulator FIRST
fa = FlowAccumulator(mg, flow_director="FlowDirectorD8")
sp = StreamPowerEroder(mg, K_sp=1e-5, m_sp=0.5, n_sp=1.0)
ld = LinearDiffuser(mg, linear_diffusivity=0.01)
```

### 2. Component Dependency Graph

```
FlowAccumulator (produces: drainage_area, flow__receiver_node, ...)
    │
    ├── StreamPowerEroder (requires: drainage_area, flow routing fields)
    ├── ErosionDeposition (requires: drainage_area, discharge, slope)
    ├── Space (requires: drainage_area, discharge, slope, soil__depth)
    │
LinearDiffuser (requires: topographic__elevation — independent of flow)
    │
ExponentialWeatherer (requires: soil__depth)
```

### 3. Time Loop Structure

```python
dt = 500.0  # years — MUST match parameter units
n_steps = 4000
uplift_rate = 1e-3  # m/yr

core = mg.core_nodes  # exclude boundary nodes from uplift

for step in range(n_steps):
    # 1. Uplift (tectonic forcing)
    z[core] += uplift_rate * dt

    # 2. Flow routing (ALWAYS FIRST)
    fa.run_one_step()

    # 3. Fluvial erosion
    sp.run_one_step(dt)

    # 4. Hillslope diffusion
    ld.run_one_step(dt)
```

TRAP: Do NOT uplift boundary nodes. Only `mg.core_nodes` should be uplifted.
Uplifting fixed-value boundary nodes changes the base level and defeats
the purpose of having an outlet (dt_011).

### 4. Adding Depression Routing

For real DEMs with pits, add a depression handler:

```python
from landlab.components import DepressionFinderAndRouter

fa = FlowAccumulator(
    mg,
    flow_director="FlowDirectorD8",
    depression_finder="DepressionFinderAndRouter",
)
```

Or use the priority-flood router (faster for large grids):

```python
from landlab.components import PriorityFloodFlowRouter
pfr = PriorityFloodFlowRouter(mg, flow_metric="D8", suppress_out=True)
```

TRAP: Without depression routing on real DEMs, pits trap flow and produce
zero drainage area downstream. The landscape develops artificial plateaus
where erosion stops (dt_012).

### 5. Multi-Component Coupling: SPACE Model

For bedrock-alluvium erosion:

```python
from landlab.components import (
    FlowAccumulator,
    Space,
    ExponentialWeatherer,
    DepthDependentDiffuser,
)

mg.add_field("soil__depth", np.ones(mg.number_of_nodes) * 1.0, at="node")
mg.add_field("bedrock__elevation",
             mg.at_node["topographic__elevation"] - 1.0, at="node")

fa = FlowAccumulator(mg)
sp = Space(mg, K_sed=1e-5, K_br=1e-6, v_s=1.0, H_star=0.5)
ew = ExponentialWeatherer(mg, soil_production_maximum_rate=1e-4,
                          soil_production_decay_depth=0.5)
dd = DepthDependentDiffuser(mg, linear_diffusivity=0.01,
                            soil_transport_decay_depth=0.5)
```

### 6. Checking Field Dependencies

Before running, verify all required fields exist:

```python
for comp in [fa, sp, ld]:
    for var_name in comp.input_var_names:
        loc = comp._info[var_name]["mapping"]
        if var_name not in getattr(mg, f"at_{loc}"):
            if not comp._info[var_name].get("optional", False):
                print(f"MISSING: {var_name} at {loc} (required by {comp.name})")
```

## Verification

- FlowAccumulator is listed before any erosion component
- All required input fields exist on the grid
- No optional fields are missing that you intended to use
- Timestep `dt` units match parameter units (years, seconds, etc.)
- Boundary conditions allow flow to exit the grid

## Traps

| Trap | Symptom | Fix | Triplet |
|------|---------|-----|---------|
| Erosion before FlowAccumulator | drainage_area = 0, no erosion | Reorder components | dt_014 |
| No depression routing on real DEM | Artificial plateaus, blocked flow | Add DepressionFinder | dt_012 |
| Uplifting boundary nodes | Base level rises, no incision | Use `mg.core_nodes` only | dt_011 |
| dt in seconds, K in 1/yr | Erosion 31M× too fast | Ensure unit consistency | dt_005 |
| Field at wrong location | Component crashes or reads zeros | Check `_info["mapping"]` | dt_015 |

## Example

```python
import numpy as np
from landlab import RasterModelGrid
from landlab.components import FlowAccumulator, StreamPowerEroder, LinearDiffuser

# Setup
mg = RasterModelGrid((30, 30), xy_spacing=200.0)
z = mg.add_zeros("topographic__elevation", at="node")
z += np.random.rand(mg.number_of_nodes) * 0.5
mg.set_closed_boundaries_at_grid_edges(True, False, True, True)

# Components (correct order)
fa = FlowAccumulator(mg, flow_director="FlowDirectorD8")
sp = StreamPowerEroder(mg, K_sp=1e-5, m_sp=0.5, n_sp=1.0)
ld = LinearDiffuser(mg, linear_diffusivity=0.01)

# Verify
fa.run_one_step()
print(f"Max drainage area: {mg.at_node['drainage_area'].max():.0f} m²")
assert mg.at_node["drainage_area"].max() > 0, "Flow routing failed!"
```
