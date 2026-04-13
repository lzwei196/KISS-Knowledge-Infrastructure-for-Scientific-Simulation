# Stage 3: Sediment Routing

## Purpose

Route sediment parcels (both sand/bedload and mud/suspended load) through the domain, computing deposition and erosion to update bed elevation (eta) and sand fraction fields.

## Inputs

| Input | Source | Description |
|-------|--------|-------------|
| `stage`, `depth` | Stage 2 (water routing) | Current water surface and depth |
| `ux`, `uy`, `uw` | Stage 2 | Flow velocity field |
| `eta` | Previous timestep | Current bed elevation |
| `sand_frac` | Previous timestep | Current sand fraction |
| `Np_sed` | Config | Number of sediment parcels (default 2000) |
| `f_bedload` | Config | Fraction of sediment as bedload (default 0.5) |
| `C0_percent` | Config | Inlet sediment concentration |

## Outputs

| Output | Used By | Description |
|--------|---------|-------------|
| `eta` (updated) | Next timestep | Updated bed elevation |
| `sand_frac` (updated) | Next timestep / output | Updated sand fraction |
| `Vp_dep_sand`, `Vp_dep_mud` | Diagnostics | Deposition volumes per cell |
| `qs` | Output | Sediment flux magnitude |

## Procedure

### 1. Initialize Sediment Iteration (`init_sediment_iteration`)

- Pad depth array
- Clear sediment flux (`qs`) and deposition volume arrays

### 2. Route Sand Parcels (`route_all_sand_parcels`)

Number of sand parcels: `Np_sed * f_bedload`

For each sand parcel:
- Start at weighted inlet cell
- Walk through domain using velocity-weighted routing:
  ```
  weight = velocity_component · depth^theta_sand
  ```
- At each step, check deposition condition:
  - If `|velocity| < U_ero_sand * u0`: deposit sand
  - Deposition volume = `Vp_sed` (volume per parcel)
- Update `eta` locally: `eta += Vp_dep / dx²`
- Update `sand_frac` using active layer mixing

### 3. Topographic Diffusion (`topo_diffusion`)

After sand routing, apply cross-stream topographic diffusion:
- Prevents unrealistic steep gradients between adjacent cells
- Repeated `N_crossdiff` times
- Uses kernel-based Laplacian diffusion on `eta`
- Diffusion coefficient: `alpha * dt / (2 * dx²)`

### 4. Route Mud Parcels (`route_all_mud_parcels`)

Number of mud parcels: `Np_sed * (1 - f_bedload)`

For each mud parcel:
- Walk similar to sand but with `theta_mud` weighting
- Deposition when `|velocity| < U_dep_mud * u0`
- Erosion when `|velocity| > U_ero_mud * u0`
- Mud deposition does not update sand_frac (sets to 0 = pure mud)

## Verification

- [ ] `eta` increased in delta region (deposition occurring)
- [ ] `sand_frac` between 0 and 1 everywhere
- [ ] No excessive spikes in eta (> 1 m change per timestep)
- [ ] Total deposited volume ≈ `dVs` per timestep
- [ ] Sand deposited primarily near inlet, mud further out

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| `C0_percent` as fraction (0.001) not percent (0.1) | No visible delta growth | Use percentage: 0.1 = 0.1% |
| `f_bedload > 1` | ValueError at startup | Must be 0-1 fraction |
| `Np_sed` too low | Noisy deposition, spotty delta | Increase to 2000+ |
| `coeff_U_dep_mud` too high | Mud deposits too close to inlet | Reduce to 0.2-0.3 |
| `coeff_U_ero_sand` too low | Sand erodes everywhere | Keep near default 1.05 |
| `alpha` too high | Excessive diffusion, flat delta | Reduce to 0.05-0.1 |

## Example

```python
import numpy as np

# Track sediment deposition over time
initial_eta = delta.eta.copy()

for t in range(10):
    delta.update()

# Total deposition
total_dep = delta.eta - initial_eta
print(f"Max deposition: {total_dep.max():.3f} m")
print(f"Mean deposition (wet cells): {total_dep[total_dep > 0].mean():.4f} m")
print(f"Erosion cells: {(total_dep < 0).sum()}")
print(f"Sand fraction range: [{delta.sand_frac.min():.2f}, {delta.sand_frac.max():.2f}]")
```

## Key Equations

### Sand Deposition Rule
```
if |u| < U_ero_sand:
    deposit Vp_sed at current cell
    eta += Vp_sed / dx²
```

### Mud Deposition/Erosion
```
if |u| < U_dep_mud:  deposit mud
if |u| > U_ero_mud:  erode mud
```

### Topographic Diffusion
```
eta_new = eta + multiplier * Laplacian(eta)
multiplier = dt / N_crossdiff * alpha * 0.5 / dx²
```

### Sediment Volume Budget
```
dVs = 0.1 * N0² * V0           # total volume added per timestep
Vp_sed = dVs / Np_sed           # volume per parcel
dt = dVs / Qs0                  # timestep size
```
