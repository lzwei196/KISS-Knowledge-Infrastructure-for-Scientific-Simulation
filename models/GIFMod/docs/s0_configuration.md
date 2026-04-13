# Stage 0: Configuration

## Purpose

Set up the GIFMod project: define simulation period, output paths, solver settings,
and establish the overall model structure before adding blocks and connectors.

## Inputs

| Input                | Source            | Format         | Required |
|----------------------|-------------------|----------------|----------|
| Simulation start     | User              | Date/day       | Yes      |
| Simulation end       | User              | Date/day       | Yes      |
| Output directory     | User              | Path           | Yes      |
| Solver settings      | Defaults/User     | Key-value      | No       |
| Block layout sketch  | User              | Conceptual     | Yes      |

## Outputs

| Output               | Format            | Location       |
|----------------------|-------------------|----------------|
| Project file         | .GIFMod           | Work directory |
| Solver config        | Embedded in file  | Project file   |

## Procedure

1. **Define simulation period**: Set start time (day 0), duration in days,
   and output write interval (default 0.0417 days = 1 hour).

2. **Configure solver**: Set adaptive timestep parameters:
   - `dt_initial`: 0.001 day (start conservative)
   - `dt_min`: 1e-8 day (allow very small steps for stiff problems)
   - `dt_max`: 0.1 day (prevent large jumps)
   - `tolerance`: 1e-6 (Newton-Raphson convergence)
   - `max_iterations`: 20 per timestep

3. **Define output variables**: Select which block/connector variables to save
   (Head, Flow, Concentration, Mass Balance).

4. **Set file paths**: Ensure output directory exists with write permissions.

## Verification

- [ ] Project file created and non-empty
- [ ] Simulation duration > 0
- [ ] dt_min < dt_initial < dt_max
- [ ] Output directory writable
- [ ] Write interval <= simulation duration

## Traps

| Trap                            | Consequence                     | Prevention             |
|---------------------------------|---------------------------------|------------------------|
| dt_max too large (> 1 day)      | Solver skips rapid events       | Keep dt_max <= 0.1 day |
| Write interval too small        | Massive output files            | Use >= 0.01 day        |
| Tolerance too loose (> 1e-3)    | Poor mass balance               | Use 1e-6 default       |
| Missing output directory        | Crash at write time             | Create dir at config   |

## Example

```python
# Minimal GIFMod configuration
config = {
    "simulation_duration": 365.0,  # days
    "dt_initial": 0.001,
    "dt_min": 1e-8,
    "dt_max": 0.1,
    "tolerance": 1e-6,
    "max_iterations": 20,
    "write_interval": 0.0417,  # ~1 hour
    "output_dir": "./output/",
}
```
