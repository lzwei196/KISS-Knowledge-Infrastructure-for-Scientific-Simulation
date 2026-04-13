# Aquifer & Layer Properties — Skill Document

> **Stage ID**: s3_layer_properties
> **Pipeline order**: 3 of 9
> **Depends on**: s2_grid_discretization

## Purpose

Define the hydraulic properties of the aquifer system: horizontal and vertical hydraulic conductivity, storage coefficients, and whether each layer behaves as confined or unconfined. These parameters control how fast groundwater flows, how much water the aquifer stores, and how the water table responds to recharge and pumping. Incorrect properties produce physically unrealistic heads and fluxes.

## Prerequisites

Before starting this stage, verify:

- [ ] DIS package exists with correct grid geometry (S2 complete)
- [ ] Aquifer type is known (unconfined, confined, or layered)
- [ ] Hydraulic conductivity data available (from HWSD, pump tests, literature, or VIC soil params)
- [ ] Storage parameters available if running transient simulation

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| k_values | config | geology/HWSD/VIC | Hydraulic conductivity (m/day) per layer |
| k33_values | config | geology | Vertical K (m/day), often K/10 |
| icelltype | config | aquifer type | 0=confined, 1=convertible for each layer |
| ss_values | config | geology | Specific storage (1/m) per layer |
| sy_values | config | geology | Specific yield (dimensionless) per layer |

## Procedure

### Step 1: Determine Aquifer Type

Set ICELLTYPE for each layer:
- **Top layer** (water table aquifer): ICELLTYPE = **1** (convertible). Saturated thickness varies with head.
- **Deep confined layers**: ICELLTYPE = **0** (confined). Saturated thickness equals full layer thickness.
- **Mixed**: If a layer can be either depending on head, use ICELLTYPE = 1.

**Newton formulation**: For models with water table conditions, always enable Newton-Raphson:
```python
gwf = flopy.mf6.ModflowGwf(sim, modelname="gwf", newtonoptions="NEWTON UNDER_RELAXATION")
```
This prevents oscillation when cells wet and dry repeatedly.

### Step 2: Assign Hydraulic Conductivity

**From HWSD/VIC soil data** (for shallow aquifers):
- VIC Ksat is in mm/day -> divide by 1000 for m/day
- Typical values: sand 1-100 m/day, silt 0.01-1 m/day, clay 0.0001-0.01 m/day

**From literature** (for deeper aquifers):

| Aquifer Material | K (m/day) | Ss (1/m) | Sy |
|-----------------|-----------|----------|-----|
| Gravel | 100-1000 | 1e-5 | 0.20-0.30 |
| Coarse sand | 10-100 | 1e-5 | 0.15-0.25 |
| Fine sand | 1-10 | 1e-5 | 0.10-0.20 |
| Silt | 0.01-1 | 1e-4 | 0.05-0.15 |
| Clay | 1e-4 to 0.01 | 1e-3 | 0.01-0.05 |
| Sandstone | 0.1-10 | 1e-5 | 0.05-0.15 |
| Limestone (karst) | 1-1000 | 1e-4 | 0.01-0.10 |
| Fractured granite | 0.001-1 | 1e-6 | 0.01-0.05 |

Vertical K (K33) is typically 1/10 of horizontal K for layered sediments.

### Step 3: Build NPF Package

```bash
python tools/s3/build_npf_package.py
```

Set variables:
- `K_VALUES`: per-layer K (scalar or 3D array)
- `K33_VALUES`: vertical K (optional, defaults to K)
- `ICELLTYPE`: per-layer cell type

**Expected result**: NPF package attached to model.

### Step 4: Build STO Package (Transient Only)

Skip this step for steady-state-only simulations.

```bash
python tools/s3/build_sto_package.py
```

Set variables:
- `SS_VALUES`: specific storage per layer
- `SY_VALUES`: specific yield per layer
- `STEADY_STATE`: list of booleans per stress period

**Expected result**: STO package attached to model.

**If this fails**: Check that SS > 0 and 0 < SY < 0.5. See dt_mf6_010.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| NPF package | `workspace/gwf.npf` | K values > 0 for all active cells |
| STO package | `workspace/gwf.sto` | Ss and Sy within physical ranges |

## Validation Checks

1. **K physically reasonable**: All K values > 0 and within 1e-7 to 1e4 m/day
   - Expected: No zero or negative K values
   - If unexpected: See dt_mf6_010

2. **ICELLTYPE set correctly**: Top layer is convertible (1) for unconfined simulation
   - Expected: ICELLTYPE[0] = 1
   - If unexpected: Heads may rise above cell top without physical basis

3. **K anisotropy ratio**: K33 / K should be 0.01 to 1.0 (not > 1.0 unless justified)
   - Expected: Vertical K <= horizontal K for layered deposits
   - If unexpected: Check if K and K33 were swapped

4. **Sy range**: 0.01 to 0.35 for natural materials
   - Expected: Within range
   - If unexpected: Sy > 0.5 is physically impossible (porosity limit)

## Common Pitfalls

> **PITFALL**: Using K from VIC soil params without unit conversion
> VIC Ksat is in mm/day. MODFLOW expects m/day. Using mm/day directly gives K values 1000x too high, causing unrealistically fast groundwater flow and convergence problems.
> **Do this instead**: Divide VIC Ksat by 1000: K_m_day = K_mm_day / 1000.
> See diagnostic triplet dt_mf6_010.

> **PITFALL**: All layers confined (ICELLTYPE=0) when water table is present
> If the water table fluctuates within a layer but ICELLTYPE=0, MODFLOW uses the full layer thickness for transmissivity regardless of actual saturation. This overestimates flow.
> **Do this instead**: Set ICELLTYPE=1 for any layer that may be partially saturated.

> **PITFALL**: Not enabling Newton formulation for unconfined problems
> The standard formulation can oscillate when cells wet and dry. This manifests as convergence failure after many outer iterations.
> **Do this instead**: Use `newtonoptions="NEWTON UNDER_RELAXATION"` when creating the GWF model.
> See diagnostic triplet dt_mf6_009.

---

*This skill document is part of the modflow6-knowledge-infrastructure package.*
*Stage 3 of 9 | Tools used: build_npf_package, build_sto_package | Related triplets: dt_mf6_009, dt_mf6_010*
