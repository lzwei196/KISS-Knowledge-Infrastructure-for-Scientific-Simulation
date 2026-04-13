# Stage 0: Configuration

## Purpose

Define the simulation domain, time period, dynamical core, grid resolution,
and physics options for a CISM ice sheet simulation. This stage produces
the parameter set that drives all subsequent stages.

## Inputs

| Input | Source | Required |
|-------|--------|----------|
| Domain selection | User (Greenland, Antarctica, synthetic) | Yes |
| Grid resolution | User (dew, dns in meters) | Yes |
| Time period | User (tstart, tend in years) | Yes |
| Dynamical core | User (Glide=SIA or Glissade=HO) | Yes |
| Physics options | User (temperature, flow law, etc.) | Yes |

## Outputs

| Output | Format | Used by |
|--------|--------|---------|
| Parameter dictionary | Python dict or JSON | s1, s2, s3 |
| Domain extent | (ewn, nsn, dew, dns) | s1 (input generation) |
| Physics choices | (dycore, flow_law, evolution, etc.) | s3 (config generation) |

## Procedure

1. **Select domain type**:
   - **Synthetic** (dome, slab, shelf, stream): Use built-in test presets
   - **Real-world** (Greenland, Antarctica): Specify grid from published datasets
   - **Regional**: Define custom extent and resolution

2. **Choose dynamical core**:
   - `dycore = 0` (Glide): Shallow Ice Approximation. Serial only. Fast.
     Good for: continental-scale, long timescale runs, benchmarks.
   - `dycore = 2` (Glissade): Higher-order dynamics. Parallel capable.
     Good for: ice streams, ice shelves, marine ice sheets.

3. **Set grid parameters**:
   - `ewn`, `nsn`: Grid points (minimum 3 each)
   - `dew`, `dns`: Spacing in **meters** (NOT km -- dt_006 trap)
   - `upn`: Vertical sigma levels (typically 5-21, more = slower but better thermal resolution)

4. **Set time parameters**:
   - `dt`: Timestep in **years** (0.01-10, smaller for higher resolution)
   - CFL stability: dt < dew^2 / (2 * D_max) where D_max is max diffusivity
   - `ntem`: Thermal subcycles per dynamic step (typically 1)

5. **Select physics options**:
   - `temperature`: 0=surface only, 1=prognostic (recommended), 2=hold initial
   - `flow_law`: 0=constant flwa, 2=Paterson-Budd (temperature-dependent)
   - `evolution`: 0=pseudo-diffusion (Glide only), 3=incremental remapping, 4=upwind
   - `marine_margin`: 0=none, 3=threshold calving

## Verification

- [ ] dew and dns are in meters, not kilometers
- [ ] dt is appropriate for grid spacing (CFL check)
- [ ] dycore=2 uses evolution=3 or 4 (not 0)
- [ ] which_ho_sparse=3 (unless Trilinos is available)
- [ ] upn >= 5 for thermodynamic simulations

## Traps

| ID | Trap | Prevention |
|----|------|-----------|
| dt_004 | dt too large causes temperature blow-up | Check CFL condition |
| dt_006 | dew/dns in km instead of m | Verify values > 100 |
| dt_007 | Glissade with evolution=0 | Auto-correct to evolution=3 |
| dt_005 | which_ho_sparse=4 without Trilinos | Default to 3 |

## Example

```python
params = {
    "ewn": 31, "nsn": 31, "upn": 11,
    "dew": 2000.0, "dns": 2000.0,
    "tstart": 0.0, "tend": 200000.0, "dt": 10.0,
    "dycore": 0,
    "temperature": 1,
    "flow_law": 0,
    "evolution": 0,
    "default_flwa": 1.0e-16,
    "geothermal": -42.0e-3,
    "title": "Dome benchmark test",
}
```
