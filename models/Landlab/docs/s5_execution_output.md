# Skill: Execution and Output Analysis (Stage 5)

## Purpose

Run the assembled Landlab simulation through its time loop and extract,
visualize, and validate the results. This stage covers the actual simulation
execution, saving intermediate snapshots, computing geomorphic metrics
(slope-area, hypsometry, relief), and comparing to analytical solutions
or published data.

## Inputs

| Input | Format | Units | Source |
|-------|--------|-------|--------|
| Configured grid + components | Python objects | — | Stage 4 |
| Timestep (dt) | float | yr (typical) | User choice |
| Number of steps | int | — | User choice |
| Uplift rate | float | m/yr | Literature / tectonic setting |

## Outputs

| Output | Format | Location | Description |
|--------|--------|----------|-------------|
| Final topography | NumPy array / NetCDF | disk | `topographic__elevation` at end |
| Time series snapshots | JSON / NPZ | disk | Field statistics at save intervals |
| Slope-area plot | PNG | disk | Log-log S vs A with regression |
| Metrics summary | JSON / CSV | disk | θ, ks, relief, HI, r² |
| Longitudinal profile | CSV | disk | Elevation vs distance along channel |

## Procedure

### 1. Running the Simulation

```python
import time
import numpy as np

dt = 500.0       # years
n_steps = 4000   # total steps → 2 Myr
uplift = 1e-3    # m/yr

core = mg.core_nodes
t0 = time.time()

for step in range(n_steps):
    z[core] += uplift * dt
    fa.run_one_step()
    sp.run_one_step(dt)
    ld.run_one_step(dt)

    # Save snapshot every 500 steps
    if (step + 1) % 500 == 0:
        print(f"Step {step+1}/{n_steps}, relief={z[core].max()-z[core].min():.1f}m")

print(f"Done in {time.time()-t0:.1f}s")
```

### 2. Saving Output

**NetCDF** (recommended for sharing):
```python
from landlab.io.netcdf import to_netcdf
to_netcdf(mg, "final_landscape.nc", format="NETCDF4")
```

**ESRI ASCII** (for GIS compatibility):
```python
from landlab.io.esri_ascii import dump
with open("elevation.asc", "w") as f:
    dump(mg, f, "topographic__elevation")
```

**NumPy** (for fast Python reload):
```python
np.savez("results.npz",
    topographic__elevation=mg.at_node["topographic__elevation"],
    drainage_area=mg.at_node["drainage_area"],
    x=mg.x_of_node, y=mg.y_of_node)
```

### 3. Visualization

```python
from landlab.plot import imshow_grid
import matplotlib.pyplot as plt

fig, axes = plt.subplots(1, 2, figsize=(14, 5))

imshow_grid(mg, "topographic__elevation", cmap="terrain", ax=axes[0])
axes[0].set_title("Elevation (m)")

imshow_grid(mg, "drainage_area", cmap="Blues", ax=axes[1])
axes[1].set_title("Drainage Area (m²)")

plt.tight_layout()
plt.savefig("landscape.png", dpi=150)
```

### 4. Slope-Area Analysis

The hallmark geomorphic diagnostic — tests whether the landscape obeys
the stream power law S = ks × A^(−θ):

```python
area = mg.at_node["drainage_area"]
slope = mg.at_node["topographic__steepest_slope"]

# Filter channel nodes (exclude hillslopes and boundary)
channel = (area > np.percentile(area[area > 0], 50)) & (slope > 1e-10)
channel &= mg.status_at_node == mg.BC_NODE_IS_CORE

log_a = np.log10(area[channel])
log_s = np.log10(slope[channel])

# Linear regression: log(S) = -θ·log(A) + log(ks)
coeffs = np.polyfit(log_a, log_s, 1)
theta = -coeffs[0]  # concavity index
ks = 10**coeffs[1]  # steepness index

# Correlation
predicted = np.polyval(coeffs, log_a)
ss_res = np.sum((log_s - predicted)**2)
ss_tot = np.sum((log_s - log_s.mean())**2)
r2 = 1 - ss_res/ss_tot

print(f"Concavity θ = {theta:.3f} (expected ~0.5 for m=0.5, n=1.0)")
print(f"Steepness ks = {ks:.4f}")
print(f"R² = {r2:.4f}")
```

For steady-state with m=0.5, n=1.0: θ should equal m/n = 0.5.
Deviation > 10% from expected value indicates non-steady-state or
parameter issues (dt_003).

### 5. Hypsometric Analysis

```python
z_core = z[core]
z_norm = (z_core - z_core.min()) / (z_core.max() - z_core.min())
HI = np.mean(z_norm)
print(f"Hypsometric integral: {HI:.3f}")
# HI > 0.6: young/convex landscape
# HI ≈ 0.5: mature/S-shaped
# HI < 0.4: old/concave landscape
```

### 6. Performance Considerations

| Grid Size | Steps | Typical Wall Time | Memory |
|-----------|-------|-------------------|--------|
| 50×50 | 4000 | ~2 s | <100 MB |
| 200×200 | 10000 | ~2 min | ~500 MB |
| 500×500 | 10000 | ~20 min | ~2 GB |
| 1000×1000 | 10000 | ~2 hr | ~8 GB |

Use PriorityFloodFlowRouter instead of FlowAccumulator+DepressionFinder
for grids > 200×200 for significant speedup.

## Verification

- Relief stabilizes (steady state) if run long enough
- Slope-area plot shows clear power-law trend
- Concavity θ matches expected m/n ratio
- No NaN values in final elevation field
- Output files are readable and have expected dimensions

## Traps

| Trap | Symptom | Fix | Triplet |
|------|---------|-----|---------|
| Not running long enough | θ deviates from m/n | Increase n_steps | — |
| Zero slope nodes in log | -inf in regression | Filter slope > 1e-10 | — |
| Saving at_link instead of at_node | Wrong array shape | Check field mapping | dt_015 |
| Large grid, no sub-stepping | Memory/time explosion | Use adaptive dt, coarser grid | dt_013 |
| Uplift applied to boundaries | Base level rises with landscape | Use core_nodes only | dt_011 |

## Example: Complete Workflow

```python
import numpy as np
import matplotlib.pyplot as plt
from landlab import RasterModelGrid
from landlab.components import FlowAccumulator, StreamPowerEroder, LinearDiffuser
from landlab.plot import imshow_grid

# Setup
mg = RasterModelGrid((50, 50), xy_spacing=100.0)
z = mg.add_zeros("topographic__elevation", at="node")
z += np.random.rand(mg.number_of_nodes) * 1.0
mg.set_closed_boundaries_at_grid_edges(True, False, True, True)

fa = FlowAccumulator(mg, flow_director="FlowDirectorD8")
sp = StreamPowerEroder(mg, K_sp=1e-5, m_sp=0.5, n_sp=1.0)
ld = LinearDiffuser(mg, linear_diffusivity=0.01)

# Run
dt, n_steps, U = 500.0, 4000, 1e-3
core = mg.core_nodes
for i in range(n_steps):
    z[core] += U * dt
    fa.run_one_step()
    sp.run_one_step(dt)
    ld.run_one_step(dt)

# Analyze
area = mg.at_node["drainage_area"]
slope = mg.at_node["topographic__steepest_slope"]
ch = (area > 5e4) & (slope > 1e-8) & (mg.status_at_node == 0)
theta = -np.polyfit(np.log10(area[ch]), np.log10(slope[ch]), 1)[0]

# Plot
fig, ax = plt.subplots(1, 1, figsize=(6, 5))
imshow_grid(mg, "topographic__elevation", cmap="terrain", ax=ax)
ax.set_title(f"Final Landscape (θ={theta:.2f})")
plt.savefig("final_landscape.png", dpi=150)
print(f"Concavity θ = {theta:.3f}")
```
