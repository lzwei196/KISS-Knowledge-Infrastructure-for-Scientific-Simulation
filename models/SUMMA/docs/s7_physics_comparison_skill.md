# Multi-Physics Comparison -- Skill Document

> **Stage ID**: s7_physics_comparison
> **Pipeline order**: 7 of 7
> **Depends on**: s6_execution

## Purpose

SUMMA's unique strength is the ability to run the same basin with different physics options and compare results. This stage systematically evaluates model structural uncertainty by varying decisions (snow layering, stomatal resistance, soil hydraulics, etc.) and quantifying how each choice affects runoff, ET, SWE, and other outputs. This provides evidence for which physics are most appropriate for a given basin, rather than relying on tradition or convenience.

## Prerequisites

- [ ] At least one successful SUMMA run (Stage 6 complete)
- [ ] Decision variations identified (which decisions to test, which options to compare)
- [ ] Sufficient disk space for multiple output files

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| base_file_manager | file | Stage 6 | Working fileManager.txt from successful run |
| summa_exe | file | installation | Path to summa.exe |
| decision_variations | config | user | Dict of decision -> [option1, option2, ...] |

## Recommended Comparison Experiments

### Experiment 1: Snow Physics (for snow-dominated basins)

```json
{
    "snowLayers": ["jrdn1991", "CLM_2010"],
    "compaction": ["consettl", "anderson"],
    "thCondSnow": ["tyen1965", "smnv2000"]
}
```
Total: 2 x 2 x 2 = 8 variants. Compare SWE, snowmelt timing.

### Experiment 2: Stomatal Resistance (for vegetated basins)

```json
{
    "stomResist": ["BallBerry", "Jarvis", "simpleResistance"],
    "soilStress": ["NoahType", "CLM_Type"]
}
```
Total: 3 x 2 = 6 variants. Compare ET partitioning.

### Experiment 3: Runoff Generation

```json
{
    "f_Richards": ["moisture", "mixdform"],
    "groundwatr": ["qTopmodl", "bigBuckt", "noXplict"]
}
```
Total: 2 x 3 = 6 variants. Compare runoff timing, baseflow.

### Experiment 4: Radiation Transfer (for forested basins)

```json
{
    "canopySrad": ["noah_mp", "CLM_2stream", "BeersLaw"]
}
```
Total: 3 variants. Compare net radiation, snow under canopy.

## Procedure

### Step 1: Define comparison experiment

Choose which decisions to vary. Start with 2-3 decisions (< 20 combinations). Full factorial designs with many decisions produce too many runs to be practical.

### Step 2: Run comparison

```bash
python tools/s7_physics_comparison/compare_physics.py \
  --file_manager outputs/<run>/fileManager.txt \
  --summa_exe model/summa/bin/summa.exe \
  --variations '{"snowLayers": ["jrdn1991", "CLM_2010"], "stomResist": ["BallBerry", "Jarvis"]}' \
  --output_dir outputs/<run>/comparison/ \
  --variables scalarTotalRunoff scalarSWE scalarTotalET
```

**Expected runtime**: N variants x single-run time.

### Step 3: Plot results

```bash
# Time series comparison
python tools/s7_physics_comparison/plot_summa_results.py \
  --output_nc "outputs/<run>/summa_output/run1.nc,outputs/<run>/summa_output/run2.nc" \
  --plot_type comparison \
  --labels "Jordan1991,CLM2010" \
  --output_png outputs/<run>/comparison/physics_comparison.png \
  --title "Snow Layer Comparison - <Basin>"
```

### Step 4: Analyze results

From `physics_comparison.csv`:
- Which decision has the largest effect on runoff? (highest std across variants)
- Which combination best matches observations (if available)?
- Are any combinations clearly unrealistic? (negative runoff, >100% ET)

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Comparison CSV | `outputs/<run>/comparison/physics_comparison.csv` | Has rows for each variant |
| Comparison plot | `outputs/<run>/comparison/physics_comparison.png` | Multi-panel figure |

## Validation Checks

1. **All variants completed**: Check status column in CSV -- all should be "success".
2. **Results differ**: If all variants produce identical output, the decisions file was not actually changed. See dt_017.
3. **No unrealistic values**: Check for NaN, negative runoff, or extreme values in any variant.

## Common Pitfalls

> **PITFALL**: All variants produce identical results.
> The modified fileManager was not pointing to the modified decisions file. See dt_017.

> **PITFALL**: Too many combinations (> 50 variants).
> Each run takes 1-20 minutes. 50 variants = hours. Start with one-at-a-time sensitivity testing, then do 2-way interactions for the most sensitive decisions.

> **PITFALL**: Comparing results without accounting for spinup.
> Each variant needs its own spinup period. If you change physics options that affect soil moisture equilibrium, the first year is not comparable. Discard spinup from all variants equally.

---

*This skill document is part of the hydrocraft-summa knowledge infrastructure.*
*Stage 7 of 7 | Tools used: compare_physics, plot_summa_results | Related triplets: dt_017*
