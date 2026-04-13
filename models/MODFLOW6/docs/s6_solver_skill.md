# Solver Configuration — Skill Document

> **Stage ID**: s6_solver
> **Pipeline order**: 6 of 9
> **Depends on**: s5_stress_periods

## Purpose

Configure the Iterative Model Solution (IMS) package that controls how MODFLOW 6 solves the system of equations. The solver determines whether the model converges to a solution, how quickly it converges, and how accurate that solution is. Poor solver settings are the most common cause of convergence failure, especially for nonlinear problems (unconfined flow, wetting/drying).

## Prerequisites

Before starting this stage, verify:

- [ ] All packages defined (DIS, NPF, STO, IC, BCs from S2-S5)
- [ ] Model type known: linear (all confined) vs nonlinear (any convertible layers)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| complexity | string | model type | SIMPLE, MODERATE, or COMPLEX |
| dvclose | number | model precision | Head change criterion (m), default 0.001 |
| rclose | number | model precision | Residual criterion (m3/day), default 0.1 |
| outer_maximum | number | convergence | Max outer iterations, default 100 |
| inner_maximum | number | convergence | Max inner iterations, default 50 |

## Procedure

### Step 1: Choose Solver Complexity

MODFLOW 6 IMS provides three complexity presets:

| Complexity | Use For | OUTER_DVCLOSE | OUTER_MAXIMUM | LINEAR_ACCELERATION | UNDER_RELAXATION |
|-----------|---------|---------------|---------------|---------------------|------------------|
| SIMPLE | All confined, steady state | 0.001 | 25 | CG | NONE |
| MODERATE | Convertible layers, mild nonlinearity | 0.001 | 100 | BICGSTAB | DBD |
| COMPLEX | Water table, wetting/drying, Newton | 0.001 | 500 | BICGSTAB | DBD + BACKTRACKING |

**Rules of thumb**:
- If all layers are confined (ICELLTYPE=0): use SIMPLE
- If top layer is convertible (ICELLTYPE=1): use MODERATE
- If cells go dry/rewet, or Newton formulation is used: use COMPLEX

### Step 2: Build IMS Package

```bash
python tools/s6/build_ims_package.py
```

Set variables:
- `COMPLEXITY`: "SIMPLE", "MODERATE", or "COMPLEX"
- `DVCLOSE`: head change convergence criterion (m)
- `RCLOSE`: residual convergence criterion (m3/day)

For custom settings beyond presets:
```python
ims = flopy.mf6.ModflowIms(
    sim,
    complexity="COMPLEX",
    outer_dvclose=1e-4,
    outer_maximum=500,
    inner_dvclose=1e-5,
    inner_maximum=100,
    linear_acceleration="BICGSTAB",
    under_relaxation="DBD",
    under_relaxation_theta=0.7,
    under_relaxation_kappa=0.1,
    under_relaxation_gamma=0.0,
    backtracking_number=5,
    backtracking_tolerance=1.1,
    backtracking_reduction_factor=0.3,
)
```

**Expected result**: IMS package attached to simulation and registered to GWF model.

### Step 3: Register IMS with Model

The IMS must be associated with the GWF model via the simulation:
```python
sim.register_ims_package(ims, [gwf.name])
```

FloPy usually handles this automatically when IMS is created after the GWF model.

### Step 4: Verify Solver Settings

```python
print(f"Complexity: {ims.complexity.data}")
print(f"DVCLOSE: {ims.outer_dvclose.data}")
print(f"RCLOSE: {ims.inner_rclose.data}")
print(f"Max outer: {ims.outer_maximum.data}")
```

**Expected result**: Settings appropriate for model complexity.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| IMS package | `workspace/gwf.ims` | File exists with convergence criteria |

## Validation Checks

1. **DVCLOSE appropriate**: Head change criterion matches model precision needs
   - Expected: 0.0001 to 0.01 m (0.001 is a good default)
   - If unexpected: Too tight (< 1e-6) wastes iterations; too loose (> 0.1) gives imprecise heads

2. **RCLOSE appropriate**: Residual criterion matches model scale
   - Expected: 0.01 to 1.0 m3/day for typical models
   - If unexpected: Scale with model size — larger models need larger RCLOSE

3. **Outer iterations sufficient**: OUTER_MAXIMUM > expected nonlinear iterations
   - Expected: 25 for confined, 100-500 for unconfined
   - If unexpected: See dt_mf6_001

4. **IMS registered to model**: Solver is associated with the GWF model
   - Expected: `sim.simulation_data.mfdata[sim.name, "SOLUTIONGROUP", ...]` contains model name
   - If unexpected: Model will have no solver and mf6 will abort

## Common Pitfalls

> **PITFALL**: Using SIMPLE complexity for unconfined problems
> SIMPLE uses CG solver with no under-relaxation. For nonlinear problems (water table, Newton), CG often diverges.
> **Do this instead**: Use MODERATE or COMPLEX for any model with ICELLTYPE=1 layers.
> See diagnostic triplet dt_mf6_009.

> **PITFALL**: DVCLOSE too tight for the problem
> Setting DVCLOSE=1e-8 may prevent convergence if the model has natural oscillation at that scale. The solver hits OUTER_MAXIMUM without converging.
> **Do this instead**: Start with DVCLOSE=0.001 and tighten only if needed.
> See diagnostic triplet dt_mf6_001.

> **PITFALL**: Forgetting to register IMS with the GWF model
> If the IMS is created but not registered, mf6 will abort with "No solution found for model".
> **Do this instead**: Verify registration after creating IMS.

---

*This skill document is part of the modflow6-knowledge-infrastructure package.*
*Stage 6 of 9 | Tools used: build_ims_package | Related triplets: dt_mf6_001, dt_mf6_009*
