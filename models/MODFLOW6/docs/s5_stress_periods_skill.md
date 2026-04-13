# Stress Periods & Temporal Discretization — Skill Document

> **Stage ID**: s5_stress_periods
> **Pipeline order**: 5 of 9
> **Depends on**: s3_layer_properties, s4_boundary_conditions

## Purpose

Define the temporal structure of the simulation: how long it runs, how time is divided into stress periods (intervals where boundary conditions are constant), and how each stress period is subdivided into timesteps. Also set initial head conditions. Incorrect temporal discretization produces unstable solutions or misrepresents transient dynamics.

## Prerequisites

Before starting this stage, verify:

- [ ] NPF and STO packages exist (S3 complete)
- [ ] At least one boundary condition package exists (S4 complete)
- [ ] Simulation time period is defined (start/end date)
- [ ] Time-varying data (recharge, pumping) are prepared per stress period

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| nper | number | simulation design | Number of stress periods |
| period_data | config | simulation design | [(perlen, nstp, tsmult), ...] per period |
| time_units | string | model convention | "days" (recommended for coupling with VIC) |
| strt | config | estimate/prior run | Starting head for IC package |
| transient_stress | config | VIC/user | Time-varying RCH, WEL, RIV data per period |

## Procedure

### Step 1: Design Stress Period Structure

Common approaches:

| Use Case | Stress Period Design | Notes |
|----------|---------------------|-------|
| Steady state | 1 period, perlen=1, nstp=1 | For initial head estimation |
| Annual steady state | 1 period, perlen=365.25 | Long-term average conditions |
| Monthly transient | 12 periods/year, perlen=28-31 | Standard for coupling with VIC |
| Daily transient | 365 periods/year, perlen=1 | High temporal resolution |
| Warmup + transient | 1 steady + N transient | Recommended: equilibrate first |

**Recommended approach for HydroCraft coupling**:
1. Run a **steady-state period first** (perlen=1, nstp=1) with average recharge
2. Follow with **monthly transient periods** matching VIC output

### Step 2: Build TDIS Package

```bash
python tools/s5/build_tdis_package.py
```

Set variables:
- `NPER`: number of stress periods
- `PERIOD_DATA`: list of (perlen, nstp, tsmult) tuples
- `TIME_UNITS`: "days"

The TDIS file looks like:
```
BEGIN OPTIONS
  TIME_UNITS  days
END OPTIONS

BEGIN DIMENSIONS
  NPER  13
END DIMENSIONS

BEGIN PERIODDATA
  1.0  1  1.0
  31.0  31  1.0
  28.0  28  1.0
  ...
END PERIODDATA
```

**Expected result**: TDIS package attached to simulation.

### Step 3: Set Initial Conditions (IC Package)

Good initial conditions are critical for convergence, especially in unconfined simulations.

**Options for starting head (STRT)**:

| Method | When to Use | How |
|--------|------------|-----|
| Uniform value | Simple models | Use average land surface elevation minus 5-10 m |
| Per-layer values | Layered aquifers | Set head at ~90% of layer top for each layer |
| From prior run | Warmup approach | Read heads from a steady-state run |
| Interpolated surface | Known water table data | Interpolate from observed well data |

```bash
python tools/s5/build_ic_package.py
```

**Critical**: Starting head must be **above layer bottom** for all active cells. If STRT < BOTM, the cell starts dry and may never rewet.

**Expected result**: IC package attached to model.

**If this fails**: Check that STRT > BOTM for all layers. See dt_mf6_011.

### Step 4: Assign Transient Stress Data

For transient simulations, update boundary condition data per stress period:

```bash
python tools/s5/assign_transient_stress.py
```

For VIC coupling: map monthly VIC baseflow to MODFLOW stress periods.

Example stress period data for RCH:
```python
rch_spd = {}
for iper, monthly_rch in enumerate(vic_monthly_baseflow):
    rch_spd[iper] = monthly_rch / 1000.0  # mm/day -> m/day
```

**Expected result**: Stress period data updated for target package.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| TDIS package | `workspace/gwf.tdis` | Sum of PERLEN equals total simulation time |
| IC package | `workspace/gwf.ic` | STRT values within model domain |

## Validation Checks

1. **Total simulation time**: Sum of all PERLEN equals expected total time
   - Command: `sum(perlen) == expected_days`
   - Expected: Exact match
   - If unexpected: Missing or extra stress periods

2. **Starting head >= layer bottom**: For all active cells, STRT >= BOTM
   - Expected: No cells where STRT < BOTM
   - If unexpected: See dt_mf6_011

3. **Starting head <= TOP**: For unconfined layers, STRT should be <= TOP
   - Expected: STRT within [BOTM, TOP] for layer 0
   - If unexpected: Starting head above land surface — physically unreasonable

4. **Stress period consistency**: Number of stress period entries in RCH/WEL/RIV matches NPER
   - Expected: Data defined for each period (or inherited from previous)
   - If unexpected: See dt_mf6_011

## Common Pitfalls

> **PITFALL**: Starting head below layer bottom
> If STRT < BOTM for an active cell, the cell starts dry. In the standard formulation, dry cells cannot rewet. Even with Newton, rewetting can cause convergence issues.
> **Do this instead**: Set STRT = TOP - 5.0 (water table 5 m below surface) as a safe default.
> See diagnostic triplet dt_mf6_011.

> **PITFALL**: Stress period lengths do not match VIC output periods
> If VIC produces monthly output but MODFLOW uses daily stress periods, recharge must be correctly mapped. Using the wrong recharge for the wrong period silently corrupts results.
> **Do this instead**: Use monthly stress periods that match VIC output exactly.
> See diagnostic triplet dt_mf6_013.

> **PITFALL**: Too few timesteps in transient periods
> Using NSTP=1 for a 30-day period means the entire period is solved in one step. Large head changes within a single step can cause convergence failure.
> **Do this instead**: Use NSTP = PERLEN (one timestep per day) or NSTP=10 with TSMULT=1.5.

---

*This skill document is part of the modflow6-knowledge-infrastructure package.*
*Stage 5 of 9 | Tools used: build_tdis_package, build_ic_package, assign_transient_stress | Related triplets: dt_mf6_011, dt_mf6_013*
