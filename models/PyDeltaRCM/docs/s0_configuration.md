# Stage 0: Configuration

## Purpose

Define the simulation domain geometry, inlet boundary conditions, sediment properties, and output settings via a YAML configuration file or Python keyword arguments.

## Inputs

| Input | Format | Source |
|-------|--------|--------|
| Field measurements | Channel width, depth, velocity, slope | Literature / field survey |
| Sediment data | Concentration (mg/L), bedload fraction | Literature / measurements |
| Sea level rise rate | mm/yr (real-world time) | IPCC / regional projections |
| Intermittency factor | Dimensionless (0-1) | Hydrological analysis |

## Outputs

| Output | Format | Used By |
|--------|--------|---------|
| YAML config file | `.yml` | Stage 1 (Initialization) |
| Or Python kwargs | `dict` | `DeltaModel(**kwargs)` |

## Procedure

1. **Gather physical parameters**: Collect channel width (m), depth (m), flow velocity (m/s), topset slope (dimensionless), and sediment concentration from literature or field data.

2. **Convert units to model format**:
   - Channel width → `N0_meters` (meters, directly)
   - Channel depth → `h0` (meters, directly)
   - Flow velocity → `u0` (m/s, directly)
   - Sediment concentration: mg/L → `C0_percent` via: `C0_percent = (conc_mgL / (rho_sed * 1000)) * 100`
   - SLR: mm/yr → `SLR` (m/s model time) via: `SLR = mmyr / 1000 / (365.25*86400) * If`

3. **Choose domain size**: Typically Width = 40× channel width, Length = 20× channel width. Grid spacing `dx` should give at least 5 cells across the inlet channel.

4. **Check gamma stability**: `gamma = g * S0 * dx / u0²`. Must be < 0.1. If too high, reduce `dx` or `S0`, or increase `u0`.

5. **Set output flags**: Enable `save_eta_grids: true` at minimum. Set `save_dt` in seconds of model time (default 86400 = 1 model day).

6. **Write YAML file** using `tools/generate_yaml_config.py` or manually.

## Verification

- [ ] All lengths in meters (not km, not cm)
- [ ] `C0_percent` is a percentage (0.01–1.0 typical), not a fraction
- [ ] `gamma < 0.1` (print gamma after init or compute manually)
- [ ] `N0_meters / dx >= 3` (at least 3 cells across inlet)
- [ ] `SLR` is in m/s of model time, not mm/yr
- [ ] `save_dt` is in seconds, not days

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| `C0_percent` given as fraction 0.001 | Almost no sediment deposited | Use percentage: 0.1 means 0.1% |
| `SLR` in mm/yr instead of m/s | Extreme flooding or no effect | Convert: mm/yr ÷ (365.25×86400×If) |
| `dx` too large relative to channel | < 3 cells across inlet, crash | Reduce dx |
| gamma > 0.1 | Numerical instability, oscillations | Reduce dx, S0, or increase u0 |
| `save_dt` in days instead of seconds | Output never saved or saved every second | Multiply by 86400 |

## Example

```yaml
# Mississippi-like delta
out_dir: 'mississippi_test'
Length: 20000        # 20 km domain
Width: 40000         # 40 km domain
dx: 100              # 100 m cells
N0_meters: 1000      # 1 km inlet channel
h0: 15.0             # 15 m depth
u0: 1.5              # 1.5 m/s velocity
S0: 0.00005          # very low slope
C0_percent: 0.05     # low sediment concentration
f_bedload: 0.3       # 30% bedload (fine-grained system)
Np_water: 3000
Np_sed: 3000
save_eta_grids: true
save_depth_grids: true
save_dt: 86400       # save every model day
seed: 42             # reproducible
```
