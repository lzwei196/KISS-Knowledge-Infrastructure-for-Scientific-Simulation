# S5: Model Coupling

## Purpose

Couple two or more BMI-wrapped models by exchanging variables between them at each time step. This is the primary use case for BMI — enabling models written in different languages by different groups to communicate through a standardized interface.

## Inputs

| Input                | Type     | Description                                        |
|----------------------|----------|----------------------------------------------------|
| BMI instances        | [object] | Two or more initialized BMI model instances        |
| Coupling map         | dict     | {source_var: target_var} mappings between models   |
| Coupling interval    | float    | Time interval for exchanging data                  |
| Unit conversion map  | dict     | {var_name: scale_factor} for unit mismatches       |

## Outputs

| Output            | Format | Description                                     |
|-------------------|--------|-------------------------------------------------|
| Coupled time series| dict  | Combined outputs from all models                |
| Coupling log      | file   | Record of data exchanges                        |

## Procedure

1. **Initialize all models**: Call `initialize()` on each BMI instance
2. **Discover coupling points**: For each model, get input/output var names
3. **Match variables**: Map output vars of Model A to input vars of Model B
   - Preferably match by CSDMS Standard Names
   - Check units via `get_var_units()` — apply conversion if mismatched
   - Check grid compatibility via `get_grid_size()` — regrid if needed
4. **Coupled time loop**:
   ```
   while any model has time remaining:
     for each model:
       model.update()
     for each coupling link:
       src_values = model_A.get_value(output_var, dest)
       [apply unit conversion if needed]
       [regrid if grid sizes differ]
       model_B.set_value(input_var, src_values)
   ```
5. **Finalize all models**: Call `finalize()` on each

## Verification

- [ ] All coupling variable pairs have compatible data types
- [ ] Units are consistent or conversion factors applied
- [ ] Grid sizes match between coupled variables (or regridding active)
- [ ] Time steps are compatible (use LCM or interpolation)
- [ ] Data flows in correct direction (output → input)

## One-Way vs Two-Way Coupling

### One-Way Coupling
Model A outputs feed Model B inputs. No feedback.

```
Model A: update() → get_value("discharge") → [convert units] → Model B: set_value("inflow")
```

### Two-Way Coupling
Models exchange data bidirectionally. Creates feedback loops.

```
Step 1: Model A: update()
Step 2: A.get_value("sediment_flux") → B.set_value("bed_load")
Step 3: Model B: update()
Step 4: B.get_value("bed_elevation") → A.set_value("bottom_z")
```

## Traps

| Trap | Description | Detection | Fix |
|------|-------------|-----------|-----|
| **Unit mismatch** | Model A outputs m/s, Model B expects mm/day | Values off by orders of magnitude | Check `get_var_units()` on both sides, apply conversion |
| **Grid mismatch** | Model A has 100 nodes, Model B has 200 | `set_value` fails or silent truncation | Implement spatial interpolation between grids |
| **Time step mismatch** | Model A dt=3600s, Model B dt=60s | Models desynchronize | Run faster model multiple steps per slow model step |
| **Variable name mismatch** | Output name ≠ input name across models | No automatic matching | Use CSDMS Standard Names or explicit mapping |
| **Circular dependency** | A needs B's output, B needs A's output simultaneously | Deadlock or stale data | Use lagged coupling (previous time step values) |
| **Missing conversion** | Forgetting to convert between K and degC | Offset errors in temperature | Temperature conversions need additive offset, not just scaling |

## CSDMS Standard Names for Coupling

CSDMS Standard Names provide unambiguous variable identifiers for automatic matching:

```
# Examples
"atmosphere_water__precipitation_leq-volume_flux"    # rainfall (m/s)
"land_surface_water__runoff_volume_flux"              # runoff (m/s)
"channel_water__discharge"                            # discharge (m^3/s)
"land_surface__temperature"                           # surface temp (K)
"atmosphere_bottom_air__temperature"                  # air temp (K)
"land_surface_water__potential_evaporation_volume_flux"  # PET (m/s)
```

Standard Names eliminate ambiguity: "temperature" could be air, surface, water, or soil — the Standard Name specifies exactly which.

## Example: Coupling a Hydrology Model with a Sediment Model

```python
from hydro_model import BmiHydro
from sediment_model import BmiSediment
import numpy as np

# Initialize both models
hydro = BmiHydro()
hydro.initialize("hydro_config.yaml")

sediment = BmiSediment()
sediment.initialize("sediment_config.yaml")

# Check units compatibility
q_units = hydro.get_var_units("channel_water__discharge")  # "m3 s-1"
inflow_units = sediment.get_var_units("water__volume_flux")  # "m3 s-1"
assert q_units == inflow_units, f"Unit mismatch: {q_units} vs {inflow_units}"

# Get grid sizes
q_size = hydro.get_grid_size(hydro.get_var_grid("channel_water__discharge"))
inflow_size = sediment.get_grid_size(sediment.get_var_grid("water__volume_flux"))

# Coupled loop
end_time = min(hydro.get_end_time(), sediment.get_end_time())
while hydro.get_current_time() < end_time:
    # Advance hydro model
    hydro.update()

    # Transfer discharge from hydro to sediment
    discharge = np.empty(q_size, dtype=float)
    hydro.get_value("channel_water__discharge", discharge)

    # Regrid if needed
    if q_size != inflow_size:
        discharge = np.interp(
            np.linspace(0, 1, inflow_size),
            np.linspace(0, 1, q_size),
            discharge
        )

    sediment.set_value("water__volume_flux", discharge)

    # Advance sediment model
    sediment.update()

# Cleanup
hydro.finalize()
sediment.finalize()
```
