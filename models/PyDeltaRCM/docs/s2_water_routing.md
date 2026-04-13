# Stage 2: Water Routing

## Purpose

Route water parcels through the domain using weighted random walks to compute the free water surface, flow velocities, and discharge field for the current timestep.

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| `eta` | Previous timestep | Current bed elevation |
| `stage` | Previous timestep | Current water surface |
| `depth` | Previous timestep | Current water depth |
| `cell_type` | Domain init | Cell classification |
| `Np_water` | Config | Number of water parcels (default 2000) |
| `itermax` | Config | Water iterations per timestep (default 3) |

## Outputs

| Output | Used By | Description |
|--------|---------|-------------|
| `stage` | Sediment routing (Stage 3) | Updated water surface elevation |
| `depth` | Sediment routing (Stage 3) | Updated water depth |
| `qx`, `qy`, `qw` | Sediment routing / output | Discharge components and magnitude |
| `ux`, `uy`, `uw` | Sediment routing / output | Velocity components and magnitude |

## Procedure

The water routing is called `itermax` times per timestep. Each iteration:

### 1. Initialize Water Iteration (`init_water_iteration`)

- Clear accumulated discharge arrays (`qxn`, `qyn`, `qwn`)
- Reset free surface tracking arrays
- Pad stage, depth, and cell_type arrays (1-cell border padding)
- Assign starting indices for parcels at inlet cells

### 2. Run Water Iteration (`run_water_iteration`)

For each of the `Np_water` parcels:
- Start at a randomly-weighted inlet cell
- Walk up to `stepmax` steps through the domain
- At each step, compute routing weights for 8 neighbor cells:

```
weight_i = max(0, exp(-gamma * (stage_neighbor - stage_current) / dx)) * depth_neighbor^theta_water
```

- Select next cell via weighted random choice (numba JIT-compiled)
- Accumulate discharge at each visited cell
- Stop when parcel reaches an edge/ocean boundary or exceeds stepmax

### 3. Compute Free Surface (`compute_free_surface`)

- For each cell visited by at least one parcel:
  - Average the stage values recorded during parcel visits
  - Blend with previous surface: `stage = Csmooth * stage_old + (1-Csmooth) * stage_new`
- For cells not visited: no update

### 4. Finalize Water Iteration (`finalize_water_iteration`)

- Apply smoothing (Laplacian-based, `Nsmooth` iterations)
- Recompute depth from updated stage: `depth = stage - eta`
- Enforce dry-depth threshold: cells with `depth < dry_depth` set to 0
- Update velocity: `u = q / depth` where depth > 0
- Apply flow limiter: cap velocity at `u_max = 2 * u0`
- Blend discharge with previous: `qx = omega * qxn + (1-omega) * qx_old`

## Verification

- [ ] No NaN values in stage or depth after routing
- [ ] Maximum velocity ≤ `u_max` (= 2 × u0)
- [ ] All depths ≥ 0
- [ ] Water parcels mostly reach boundaries (check `free_surf_flag`)
- [ ] Discharge is concentrated in channels (visual check)

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| gamma > 0.1 | Oscillating stage, NaN velocities | Reduce dx, S0, or increase u0 |
| Np_water too low | Noisy free surface, dry areas | Increase to 2000-5000 |
| itermax = 1 | Poor free surface convergence | Use itermax ≥ 3 |
| theta_water too high | Parcels stuck in deep cells | Keep theta_water ≈ 1.0 |
| stepmax too low | Parcels never reach boundary | Use default: 2*(L+W) |
| Csmooth = 1.0 | Stage never updates | Use 0.9 (default) |

## Example

```python
# Inspect water routing results after one timestep
delta.update()

import numpy as np
print(f"Max depth: {delta.depth.max():.2f} m")
print(f"Max velocity: {delta.uw.max():.3f} m/s (limit: {delta.u_max:.1f})")
print(f"Wet cells: {(delta.depth > delta.dry_depth).sum()}")
print(f"Max discharge: {delta.qw.max():.3f} m2/s")
```

## Key Equations

### Routing Weight
```
w(i,j→k) = exp(-γ · max(0, Δh/dx)) · d_k^θ · mod_water_weight_k
```

Where:
- γ = gamma (stability parameter)
- Δh = stage_neighbor − stage_current
- d_k = depth at neighbor cell
- θ = theta_water (depth weighting exponent)

### Free Surface Update
```
stage_new = ω_sfc · stage_old + (1 − ω_sfc) · stage_routed
```

### Discharge Blending
```
qx = ω_flow · qxn_new + (1 − ω_flow) · qx_old
```
