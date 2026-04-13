# S4: Execution — Running SimFire Simulations

## Purpose

Execute a SimFire wildfire simulation using a prepared YAML configuration, either
interactively with PyGame rendering or in headless mode for batch processing and
reinforcement learning training.

## Inputs

| Input | Source | Format | Notes |
|-------|--------|--------|-------|
| YAML config file | S1 output | `.yml` | All parameters defined |
| Terrain data (operational) | S2 output / LandFire | GeoTIFF / cached | Auto-downloaded if operational mode |
| Wind data (external) | S3 output | NPY arrays | Only if using pre-computed wind |

## Outputs

| Output | Format | Location | Notes |
|--------|--------|----------|-------|
| Fire map array | NPY/H5 | `sf_home` directory | if `save_data: true` |
| GIF animation | `.gif` | `sf_home` directory | if `record: true` |
| Spread graph | `.png` | `sf_home` directory | if `draw_spread_graph: true` |
| Fire map (in-memory) | numpy array | `sim.fire_map` | Always available via API |

## Procedure

### Method 1: Python API (Recommended)

```python
from simfire.sim.simulation import FireSimulation
from simfire.utils.config import Config

# Load configuration
config = Config("configs/operational_config.yml")

# Override for headless server
config.simulation.headless = True

# Create simulation
sim = FireSimulation(config)

# Run for specified duration
sim.run("2h")          # 2 hours of simulated time
# or
sim.run("30m")         # 30 minutes
# or
sim.run(100)           # 100 update steps (= 100 × update_rate minutes)

# Access results
fire_map = sim.fire_map     # numpy array, shape (H, W)
# Values: 0=UNBURNED, 1=BURNING, 2=BURNED, 3-5=control lines

# Continue simulation
sim.run("1h")           # Runs 1 more hour from current state

# Reset to initial conditions
sim.reset()

# Save outputs
sim.save_gif()
sim.save_spread_graph()
```

### Method 2: Script Wrapper

```bash
python ki/tools/run_simfire.py \
    --config configs/functional_config.yml \
    --runtime "2h" \
    --headless \
    --output-dir ./output/
```

### Method 3: Quick Test

```bash
python ki/tools/run_simfire.py --quick-test --output-dir ./test_output/
```

### Mitigation (Control Lines)

During simulation, add control lines to slow or stop fire:

```python
# Place fireline points
fireline_points = [(10, 20), (10, 21), (10, 22)]
sim.update_mitigation(fireline_points)

# Run to see effect
sim.run("30m")
```

Control line types and RoS attenuation:
| Type | BurnStatus | Attenuation (ft/min) |
|------|-----------|---------------------|
| Fireline | 3 | 980 |
| Scratchline | 4 | 490 |
| Wetline | 5 | 245 |

With `ros_attenuation: true`, fire RoS is reduced by the attenuation value.
With `ros_attenuation: false`, fire RoS is set to zero at control lines (hard stop).

### RL Agent Integration

```python
# Agent-based simulation loop
sim = FireSimulation(config)

for step in range(1000):
    # Get observation space
    obs = sim.get_attribute_data()
    bounds = sim.get_attribute_bounds()

    # Agent decides action
    action = agent.act(obs)

    # Apply mitigation
    sim.update_mitigation(action)

    # Step simulation
    sim.run(1)  # 1 update step

    # Check fire map
    if np.all(sim.fire_map != 1):  # No burning pixels
        break
```

## Verification

1. Check simulation actually ran:
   ```python
   assert np.any(sim.fire_map == 2), "No burned pixels — fire didn't spread"
   ```

2. Check for reasonable burn area:
   ```python
   burned_frac = np.mean(sim.fire_map >= 1)
   print(f"Burned fraction: {burned_frac:.2%}")
   ```

3. Check wall-clock time is reasonable:
   - 100×100 grid, 1h sim: should take < 30s
   - 225×450 grid, 15h sim: may take 5-15 min

## Traps

| Trap | Symptom | Severity | Fix |
|------|---------|----------|-----|
| `headless: false` on server | `pygame.error: No available video device` | **Fatal** | Set `headless: true` |
| `record: true` without display memory | Memory error or crash | **Fatal** | Set `record: false` for batch |
| Very large grid (>500×500) | Extremely slow or OOM | Degraded | Reduce grid or use headless |
| `max_fire_duration` too low (1-2) | Fire appears, immediately burns out | **Silent** | Set to 4-5 minimum |
| `update_rate` very high (>10) | Coarse time resolution, fire jumps | Degraded | Use 1 min/step |
| `diagonal_spread: false` | Fire spreads in cross pattern (4-connected) | Expected | Set `true` for realistic spread |
| No `sf_home` directory | Cache/save errors | Fatal | Create directory or set in config |

## Example

Full headless operational simulation:
```python
from simfire.sim.simulation import FireSimulation
from simfire.utils.config import Config
import numpy as np

config = Config("configs/operational_config.yml")
config.simulation.headless = True
config.simulation.record = False

sim = FireSimulation(config)
sim.run("6h")

fire_map = sim.fire_map
burned = np.sum((fire_map == 1) | (fire_map == 2))
total = fire_map.size
print(f"Burned: {burned}/{total} pixels ({burned/total:.1%})")
np.save("fire_map_6h.npy", fire_map)
```
