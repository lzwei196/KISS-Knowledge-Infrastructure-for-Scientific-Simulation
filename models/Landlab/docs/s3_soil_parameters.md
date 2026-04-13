# Skill: Soil and Weathering Parameter Setup (Stage 3)

## Purpose

Configure soil/regolith fields and weathering parameters on the Landlab grid.
This stage prepares data for components that track soil depth, bedrock erosion,
and soil production (ExponentialWeatherer, DepthDependentDiffuser, SPACE).
Soil depths from global databases are in centimeters; Landlab expects meters.

## Inputs

| Input | Format | Units | Source |
|-------|--------|-------|--------|
| Soil depth map | CSV, raster, or scalar | cm (HWSD) or m | HWSD, SoilGrids, field data |
| Bulk density | float | kg/dm³ (HWSD) | HWSD T_BULK_DENSITY column |
| Sand/clay/silt fractions | float | percent (0–100) | HWSD texture columns |
| Weathering rate parameters | float | m/yr | Literature / calibration |
| Erodibility (K) | float | depends on m,n | Literature / calibration |

## Outputs

| Output | Format | Location | Description |
|--------|--------|----------|-------------|
| `soil__depth` | float array | at_node | Soil/regolith thickness (m) |
| `bedrock__elevation` | float array | at_node | Bedrock surface = elevation − soil_depth |
| `soil_production__rate` | float array | at_node | Weathering rate (m/yr) |
| Parameter JSON | file | disk | K_sp, diffusivity, porosity, etc. |

## Procedure

### 1. Set soil depth

```python
# Uniform soil depth
soil_depth = 1.5  # meters
mg.add_field("soil__depth", np.full(mg.number_of_nodes, soil_depth), at="node")

# Compute bedrock elevation
z = mg.at_node["topographic__elevation"]
mg.add_field("bedrock__elevation", z - soil_depth, at="node")
```

CRITICAL: If using HWSD data, the `T_REF_DEPTH` column is in **centimeters**.
You MUST divide by 100 to get meters:

```python
depth_m = hwsd_depth_cm / 100.0  # cm → m
```

If you forget this conversion, soil will be 100× too thick and ExponentialWeatherer
will predict negligible soil production because exp(-100/0.5) ≈ 0 (dt_006).

### 2. Derive porosity from bulk density

```python
# HWSD bulk density is in kg/dm³ (= g/cm³)
# Mineral density ≈ 2650 kg/m³ = 2.65 kg/dm³
bd_kg_dm3 = 1.4  # from HWSD
porosity = 1.0 - (bd_kg_dm3 / 2.65)
# Result: 0.47 (fraction, 0–1) — this is what Landlab expects
```

TRAP: Some databases report bulk density in cg/cm³ (SoilGrids). Convert:
cg/cm³ → kg/m³ by multiplying by 10. Then porosity = 1 − (bd_kg_m3 / 2650).

### 3. Set weathering parameters

ExponentialWeatherer uses:
- `soil_production_maximum_rate` (P₀): typically 1e-5 to 1e-3 m/yr
- `soil_production_decay_depth` (H*): typically 0.2 to 2.0 m

```python
from landlab.components import ExponentialWeatherer

# Soil production: P = P0 * exp(-H / H*)
ew = ExponentialWeatherer(
    mg,
    soil_production_maximum_rate=1e-4,  # m/yr
    soil_production_decay_depth=0.5,     # m
)
```

### 4. Set erodibility

StreamPowerEroder K_sp units depend on exponents m and n:
- For E = K A^m S^n, K has units: [length^(1-2m) / time]
- m=0.5, n=1.0 → K has units 1/time (e.g., 1/yr)
- m=0.3, n=0.7 → K has different units — do NOT copy K values across exponent sets

Typical K_sp values (m=0.5, n=1.0):
- Hard bedrock: 1e-7 to 1e-6 /yr
- Moderate rock: 1e-6 to 1e-5 /yr
- Soft sediment: 1e-5 to 1e-4 /yr

### 5. Set diffusivity

LinearDiffuser `linear_diffusivity` D:
- Arid, bare rock: 0.001–0.01 m²/yr
- Temperate soil-mantled: 0.01–0.1 m²/yr
- Humid, bioturbated: 0.05–1.0 m²/yr

## Verification

- `soil__depth` is in meters (0–50 m typical, >100 m suspicious)
- `bedrock__elevation` = `topographic__elevation` − `soil__depth`
- Porosity is fraction 0–1 (not percent)
- K_sp is appropriate for the chosen m, n exponents
- All units consistent with the timestep unit

## Traps

| Trap | Symptom | Fix | Triplet |
|------|---------|-----|---------|
| HWSD depth in cm used as m | Soil 100× too thick, no weathering | Divide by 100 | dt_006 |
| K_sp copied with wrong m,n | Erosion rate orders of magnitude off | Recalculate for your m,n | dt_003 |
| Porosity as percent (45) not fraction (0.45) | Groundwater model crashes | Divide by 100 | dt_008 |
| Diffusivity m²/s instead of m²/yr | Hillslopes flatten in one step | Verify time unit | dt_002 |

## Example

```python
import numpy as np
from landlab import RasterModelGrid
from landlab.components import ExponentialWeatherer

mg = RasterModelGrid((50, 50), xy_spacing=100.0)
z = mg.add_zeros("topographic__elevation", at="node")
z += np.random.rand(mg.number_of_nodes) * 100 + 500

# Soil from HWSD: T_REF_DEPTH = 150 cm → 1.5 m
hwsd_depth_cm = 150.0
soil_depth_m = hwsd_depth_cm / 100.0  # CRITICAL conversion
mg.add_field("soil__depth", np.full(mg.number_of_nodes, soil_depth_m), at="node")
mg.add_field("bedrock__elevation", z - soil_depth_m, at="node")

# Weathering
ew = ExponentialWeatherer(mg,
    soil_production_maximum_rate=1e-4,
    soil_production_decay_depth=0.5)
ew.run_one_step(1.0)  # 1 year

print(f"Soil depth: {soil_depth_m} m")
print(f"Production rate range: "
      f"{mg.at_node['soil_production__rate'].min():.2e} – "
      f"{mg.at_node['soil_production__rate'].max():.2e} m/yr")
```
