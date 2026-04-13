# Simulation Execution — Skill Document

> **Stage ID**: s6_execution
> **Pipeline order**: 6 of 8
> **Depends on**: s5_engine_config

## Purpose

Run the WOFOST crop growth simulation by advancing the engine through daily time steps. The engine iterates through the crop growth cycle: phenological development (DVS 0→1→2), daily assimilation, respiration, biomass partitioning, leaf dynamics, root growth, and optionally the soil water balance. The simulation terminates when the crop reaches maturity (DVS=2), the maximum duration is reached, or the crop end date is reached. This stage is where most runtime errors and silent failures manifest.

## Prerequisites

- [ ] PCSE engine instantiated successfully (Stage 5)
- [ ] Engine type matches intended simulation (PP vs WLP)
- [ ] Weather data covers the entire expected growing season

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| engine | Wofost72_* | Stage 5 | Configured PCSE engine object |

## Procedure

### Step 1: Run the simulation

```python
# Option A: Run to natural termination (maturity, max_duration, or end_date)
engine.run_till_terminate()

# Option B: Step-by-step (for debugging or monitoring)
for i in range(365):
    engine.run(days=1)
    dvs = engine.get_variable('DVS')
    lai = engine.get_variable('LAI')
    print(f"Day {i+1}: DVS={dvs:.3f}, LAI={lai:.2f}")
    if dvs >= 2.0:
        print("Crop reached maturity!")
        break
```

**Expected result**: Simulation completes without exception. For run_till_terminate(), the method returns when the engine's internal termination conditions are met.

**If this fails**:
- `WeatherDataProviderError` → Weather data gap. See dt_011.
- Runtime exception → Check if parameters are in valid ranges. See dt_007.

### Step 2: Check DVS at termination

```python
final_dvs = engine.get_variable('DVS')
print(f"Final DVS: {final_dvs:.2f}")

if final_dvs < 2.0:
    print("WARNING: Crop did NOT reach maturity!")
    if final_dvs < 1.0:
        print("  DVS < 1.0: Crop never flowered. Check:")
        print("  - TSUM1 too high for this climate?")
        print("  - Vernalization stuck? (winter crops)")
        print("  - max_duration too short?")
    elif final_dvs < 2.0:
        print("  DVS 1-2: Flowered but did not mature. Check:")
        print("  - TSUM2 too high for this climate?")
        print("  - max_duration too short?")
elif final_dvs >= 2.0:
    print("Crop reached full maturity (DVS=2.0). Simulation successful.")
```

**If DVS is stuck**: See diagnostic triplets dt_005 (vernalization), dt_006 (DVS stuck), dt_014 (max_duration).

### Step 3: Check for zero yield

```python
twso = engine.get_variable('TWSO')
tagp = engine.get_variable('TAGP')
lai_max = max(engine.get_variable('LAI'))

print(f"Yield (TWSO): {twso:.0f} kg/ha")
print(f"Total biomass (TAGP): {tagp:.0f} kg/ha")

if twso <= 0:
    print("CRITICAL: Zero yield!")
    print("Possible causes:")
    print("  1. DVS never reached partitioning-to-storage phase")
    print("  2. Severe water stress killed the crop")
    print("  3. Temperature too low for growth (all assimilation zero)")
    print("  4. IRRAD in wrong units (MJ instead of kJ)")
```

**If yield is zero**: See diagnostic triplet dt_007 (zero yield silent death).

### Step 4: Check for abnormally high yield (PP mode trap)

```python
if twso > 15000:
    print(f"WARNING: Yield {twso:.0f} kg/ha seems very high.")
    print("If using Wofost72_PP, this is potential (no water stress) — expected.")
    print("If using Wofost72_WLP_FD, check soil parameters and weather data.")
```

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Completed engine | in-memory | DVS >= 2.0; TWSO > 0 |
| Daily output | retrievable via get_output() | Non-empty list of daily state dicts |
| Summary | retrievable via get_summary_output() | Contains yield, phenology dates |

## Validation Checks

1. **DVS reached 2.0**: `engine.get_variable('DVS') >= 2.0`
   - If not: Check TSUM1/TSUM2, vernalization, max_duration
   - See diagnostic triplets dt_005, dt_006, dt_014

2. **TWSO > 0**: Yield must be positive
   - If zero: See diagnostic triplet dt_007
   - Common cause: IRRAD in wrong units (dt_003)

3. **LAI peak reasonable**: Max LAI typically 2-8 m2/m2
   - If LAI stays at 0: crop never established (emergence failed)
   - If LAI > 15: parameter error in SLATB or leaf growth

4. **TAGP > TWSO**: Total biomass must exceed grain yield
   - If TAGP = TWSO: all biomass went to storage organs — check partitioning tables

## Common Pitfalls

> **PITFALL**: DVS stuck at 0.3-0.4 for winter wheat (vernalization)
> Winter wheat requires a vernalization period (cold days accumulating). If the winter is too mild (e.g., tropical location + winter wheat variety), VERNSAT is never satisfied and DVS gets stuck. The simulation terminates at max_duration with incomplete growth.
> **Do this instead**: Check that VERNSAT is appropriate for the climate. Use VERNDVS as safety cutoff. Switch to spring variety if location has no cold winter.
> See diagnostic triplet dt_005.

> **PITFALL**: Simulation completes but yield is unreasonably low
> Near-zero yield with no error message is almost always a unit problem in weather data: IRRAD in MJ instead of kJ, or RAIN in mm instead of cm.
> **Do this instead**: Before running, verify IRRAD is in kJ/m2/day (values 5000-35000) and RAIN is in cm/day (values 0-10).
> See diagnostic triplets dt_003, dt_004.

> **PITFALL**: Simulation runtime
> WOFOST via PCSE is very fast — a single grid cell runs in < 1 second. If it takes longer, there is likely an I/O bottleneck (reading weather data from a slow source). For batch runs over many grid cells, pre-load all weather data.

---

*This skill document is part of the wofost-pcse-knowledge infrastructure.*
*Stage 6 of 8 | Tools: run_wofost_simulation, check_simulation_status | Related triplets: dt_003, dt_004, dt_005, dt_006, dt_007, dt_014*
