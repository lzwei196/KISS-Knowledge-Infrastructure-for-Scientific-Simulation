# Module Chain Selection -- Skill Document

> **Stage ID**: s3_module_selection
> **Pipeline order**: 3 of 6
> **Depends on**: s1_basin_setup

## Purpose

Select and order the CRHM module chain for the target basin. CRHM's modular architecture is its key strength: modules are plugged together in a chain where each module's output feeds the next module's input. The chain determines which physical processes are simulated. For cold regions, the critical decisions are: (1) blowing snow or not, (2) energy-balance or temperature-index melt, (3) frozen soil infiltration type, and (4) forest canopy or not. Choosing the wrong module chain for the landscape type produces physically unrealistic results -- e.g., using PrairieInfil for a mountain forest basin.

## Prerequisites

- [ ] Basin landscape type determined (prairie, mountain, forest, arctic, mixed)
- [ ] HRU configuration complete (from s1_basin_setup)
- [ ] Understanding of dominant cold regions processes in the basin

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| basin_type | string | Expert assessment | Landscape: prairie, mountain, forest, arctic, mixed |
| hru_config | file | s1_basin_setup | HRU definitions with land cover |
| processes | string | User override (optional) | Specific processes to include |

## Procedure

### Step 1: Determine basin landscape type

| Landscape | Characteristics | Key cold process |
|-----------|----------------|------------------|
| **Prairie** | Flat, wind-exposed, cropland/grassland | Blowing snow transport (PBSM) |
| **Mountain** | Steep slopes, elevation gradient >500m | Radiation on slopes (Slope_Qsi) |
| **Forest** | >50% forest cover, canopy closure | Canopy interception/sublimation |
| **Arctic** | Permafrost, tundra, minimal vegetation | Frozen soil + blowing snow |
| **Mixed** | Forest clearings, variable terrain | Combined canopy + clearing |

### Step 2: Select module chain

```bash
python tools/s3_module_selection/select_modules.py \
  --basin_type <type> \
  --output_path outputs/<run>/crhm/modules.json
```

**Expected result**: JSON with ordered module chain and dependency validation.

**If this fails**: See dt_004 (module dependency error).

### Step 3: Review module chain

The chain MUST start with: `basin > global > obs`

These three modules are ALWAYS required -- they provide fundamental basin properties, radiation calculations, and observation data distribution.

After these three, the chain depends on landscape:

**Prairie chain**: `basin > global > obs > PBSM > PrairieInfil > Soil > Netroute`
- PBSM: Blowing snow transport, sublimation (requires fetch, Ht)
- PrairieInfil: Frozen soil infiltration (Gray's equation -- only valid for prairie soils with cracking clay)
- Rationale: Wind is the dominant control on snow redistribution in prairies

**Mountain chain**: `basin > global > obs > Slope_Qsi > SnobalCRHM > GreenAmpt > Soil > Netroute`
- Slope_Qsi: Corrects solar radiation for slope/aspect (critical in mountainous terrain)
- SnobalCRHM: Full energy-balance snowmelt (handles complex radiation on slopes)
- GreenAmpt: Standard infiltration (mountain soils rarely have prairie-type frozen cracking)

**Forest chain**: `basin > global > obs > CRHMCanopy > SnobalCRHM > GreenAmpt > Soil > Netroute`
- CRHMCanopy: Canopy interception, sublimation, throughfall, drip
- In boreal forests, 30-40% of snowfall sublimates from canopy -- ignoring this hugely overestimates SWE

**Arctic chain**: `basin > global > obs > PBSM > SnobalCRHM > PrairieInfil > Soil > REWroute`
- Combines blowing snow (exposed tundra) with energy-balance melt
- REWroute: Better for arctic wetland-dominated routing

### Step 4: Verify module dependencies

For each module in the chain, verify:
- All `declgetvar()` references are satisfied by earlier modules
- No circular dependencies exist

The tool validates this automatically. If it reports warnings, you must resolve them before proceeding.

### Step 5: Custom module additions

For specific processes, add modules to the chain:
- **Needle**: Add for needle-leaf forest sublimation (separate from canopy module)
- **Annan**: Add when no direct radiation observations available (estimates from temperature)
- **Grow_Crop**: Add for agricultural basins where crop height changes seasonally
- **FlowInSnow**: Add for glacierized basins where meltwater flows through snowpack

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| modules.json | `outputs/{run}/crhm/modules.json` | Chain starts with basin>global>obs, validation passes |

## Validation Checks

1. **Chain starts with required triple**: basin, global, obs
   - Command: Check first 3 entries in module_chain array
   - Expected: ["basin", "global", "obs", ...]
   - If wrong: Reorder. CRHM will crash if basin is not first.

2. **No unresolved dependencies**: chain_validation has no ERROR entries
   - Command: Check chain_validation in modules.json
   - Expected: "PASS: all dependencies satisfied"
   - If errors: A module requires a variable that no earlier module provides. See dt_004.

3. **Module matches landscape**: E.g., don't use PBSM for dense forest
   - A PBSM blowing snow module in a closed-canopy forest has no physical meaning
   - PrairieInfil is only valid for prairie soils that crack when freezing

## Common Pitfalls

> **PITFALL**: Using PBSM (Prairie Blowing Snow) in forested basins
> PBSM assumes wind-exposed terrain with uniform fetch. In dense forest, wind speed at the surface is too low for snow transport. Using PBSM in forest produces unrealistic sublimation and redistribution.
> **Do this instead**: Use CRHMCanopy for forest. PBSM is only for open prairie, tundra, or above-treeline alpine.
> See diagnostic triplet dt_016.

> **PITFALL**: Missing Slope_Qsi in mountain basins
> Without slope/aspect radiation correction, north-facing and south-facing HRUs receive identical radiation. In winter at 50N, the difference exceeds 50%. Snowmelt timing will be completely wrong.
> **Do this instead**: Always include Slope_Qsi for basins with mean slope > 10 degrees.
> See diagnostic triplet dt_016.

> **PITFALL**: PrairieInfil for non-prairie soils
> PrairieInfil implements Gray's frozen soil infiltration equation, which depends on soil cracking patterns specific to heavy clay prairie soils. Using it for mountain or sandy soils produces wrong infiltration estimates.
> **Do this instead**: Use GreenAmpt for non-prairie soils, even when frozen. GreenAmpt handles frozen conditions via reduced hydraulic conductivity.

> **PITFALL**: Module order matters -- putting infiltration before snowmelt
> If GreenAmpt appears before SnobalCRHM in the chain, it cannot access the snowmelt variable because SnobalCRHM hasn't run yet. CRHM will crash or use zero snowmelt.
> **Do this instead**: Always order: radiation > canopy > snow > infiltration > soil > routing.
> See diagnostic triplet dt_004.

---

*This skill document is part of the hydrocraft-crhm knowledge infrastructure.*
*Stage 3 of 6 | Tools used: select_modules | Related triplets: dt_004, dt_016*
