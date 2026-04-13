# VIC-CRHM Coupling -- Skill Document

> **Stage ID**: s6_vic_coupling
> **Pipeline order**: 6 of 6
> **Depends on**: s5_execution

## Purpose

Couple CRHM cold-regions process diagnostics with VIC distributed hydrological simulation. The coupling is motivated by the complementary strengths of the two models: VIC has robust grid-based energy/water balance and routing (Lohmann/CaMa-Flood), while CRHM has specialized cold regions modules (blowing snow transport, canopy sublimation, frozen soil infiltration) that VIC handles with simpler parameterizations. The coupling allows cold regions processes to be modeled at the landscape (HRU) scale by CRHM while maintaining VIC's distributed simulation and routing capabilities.

**CRITICAL COUPLING TRAP**: Both models compute snow accumulation, snowmelt, and soil moisture. If both are allowed to handle the same process, water is double-counted. You MUST define a process ownership table before coupling.

## Prerequisites

- [ ] VIC simulation complete (outputs in `outputs/{run}/vic_result/`)
- [ ] CRHM simulation complete (parsed results in `outputs/{run}/crhm/parsed/`)
- [ ] Process ownership table defined (see below)
- [ ] Spatial mapping between CRHM HRUs and VIC grid cells understood

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| crhm_csv | file | s5_execution | Parsed CRHM output CSV |
| vic_result_dir | directory | VIC pipeline | VIC flux output files |
| grid_nc | file | VIC grid generation | Basin grid for spatial reference |

## Procedure

### Step 1: Define process ownership table

**This is the most critical step.** Before any data merging, decide which model "owns" each hydrological process:

| Process | VIC | CRHM | Rationale |
|---------|-----|------|-----------|
| Snow accumulation | - | OWNER | CRHM handles blowing snow redistribution |
| Snowmelt | - | OWNER | CRHM energy balance includes wind effects |
| Sublimation (surface) | - | OWNER | CRHM has PBSM sublimation |
| Sublimation (canopy) | - | OWNER | CRHMCanopy interception model |
| Frozen soil infiltration | - | OWNER | PrairieInfil / GreenAmpt specific |
| Soil moisture (unfrozen) | OWNER | - | VIC multi-layer soil physics |
| Evapotranspiration | OWNER | - | VIC Penman-Monteith with LAI |
| Baseflow / drainage | OWNER | - | VIC ARNO curve baseflow |
| Routing to outlet | OWNER | - | Lohmann or CaMa-Flood |
| Flood inundation | OWNER | - | CaMa-Flood only |

**If you skip this step and merge all outputs, you get physically impossible water balances.** For example, if both models report 200mm of snowmelt, and you sum them, you get 400mm -- double the actual melt.

### Step 2: Convert VIC forcing to CRHM observations (if not done)

If the coupling starts from VIC forcing:
```bash
python tools/s2_observation_data/convert_vic_to_obs.py \
  --forcing_dir outputs/<run>/vic_temp/forcing/forcing_final \
  --grid_nc outputs/<run>/vic_temp/grid/basin_grid.nc \
  --output_path outputs/<run>/crhm/obs/basin.obs \
  --start_year <start> --end_year <end>
```

### Step 3: Run CRHM (if not done)

Run CRHM standalone using VIC forcing as observation input. This produces CRHM diagnostics for the same period and domain as the VIC simulation.

### Step 4: Spatial mapping

CRHM HRUs and VIC grid cells have different spatial representations:
- VIC: regular lat/lon grid (e.g., 0.25 degree cells)
- CRHM: irregular landscape units (HRUs)

For comparison, aggregate CRHM HRUs to VIC grid cells using area-weighted averaging:
```
VIC_cell_value = sum(HRU_value * HRU_area) / sum(HRU_area)
```
for all HRUs that fall within or overlap the VIC grid cell.

**Do NOT use bilinear interpolation for flux variables** (precip, runoff, ET). Bilinear interpolation conserves value at points but not mass across areas. Use area-weighted aggregation.

### Step 5: Merge results

```bash
python tools/s6_vic_coupling/merge_crhm_vic.py \
  --crhm_csv outputs/<run>/crhm/parsed/crhm_results.csv \
  --vic_result_dir outputs/<run>/vic_result \
  --grid_nc outputs/<run>/vic_temp/grid/basin_grid.nc \
  --output_dir outputs/<run>/coupled/merged
```

**Expected result**: Merged CSV and comparison plots.

### Step 6: Validate coupling

Check that the combined water balance is physically consistent:
1. Total P (from forcing) = Total ET + Total Q + delta_storage
2. CRHM SWE should track VIC SWE in magnitude (but differ in timing/redistribution)
3. CRHM sublimation should be larger than VIC (CRHM has explicit blowing snow sublimation)
4. Spring melt timing may differ -- CRHM energy balance is more detailed

### Step 7: Use CRHM diagnostics to improve VIC

The real value of coupling is using CRHM to diagnose where VIC's simpler snow/frozen-soil physics fall short:

- **Blowing snow**: CRHM shows where snow is being transported. If VIC overestimates SWE in wind-exposed HRUs, consider reducing VIC snow accumulation there.
- **Canopy sublimation**: CRHM quantifies canopy loss. VIC's canopy model may underestimate this in boreal forests.
- **Frozen soil**: CRHM PrairieInfil shows how much melt infiltrates frozen soil. If VIC's spring runoff is too high, the frozen soil fraction may need adjustment.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| Merged CSV | `outputs/{run}/coupled/merged/crhm_vic_comparison.csv` | Contains both CRHM and VIC variables |
| Comparison plot | `outputs/{run}/coupled/merged/crhm_vic_comparison.png` | Side-by-side panels |

## Validation Checks

1. **Process ownership enforced**: No variable counted twice
   - Command: Review process ownership table
   - Expected: Every hydrological process assigned to exactly one model
   - If violated: See dt_010 (double-counting).

2. **Temporal alignment**: CRHM and VIC on same daily timestep
   - Command: Check datetime index of merged CSV
   - Expected: No gaps in combined timeline
   - If misaligned: Resample both to daily before merging. See dt_015.

3. **SWE magnitude check**: CRHM and VIC SWE within 50% of each other
   - If wildly different: Unit conversion error or process misconfiguration. See dt_009.

4. **Mass balance closure**: P - ET - Q - dS within 5% of P
   - If not: Double-counting or missing flux. See dt_010.

## Common Pitfalls

> **PITFALL**: Double-counting snow processes (SILENT ERROR)
> If both VIC and CRHM compute snowmelt and you add them, total melt is double the actual value. Similarly for sublimation. The combined water balance will show impossibly large totals.
> **Do this instead**: Define the process ownership table (Step 1) BEFORE merging. Use only one model's value for each process.
> See diagnostic triplet dt_010.

> **PITFALL**: Temporal mismatch between VIC and CRHM
> VIC may output daily or 3-hourly. CRHM outputs at the timestep of the .obs file (hourly or daily). Merging mismatched timesteps produces NaN-filled columns.
> **Do this instead**: Resample both to daily before merging. Use sum for fluxes (precip, runoff, ET) and mean for state variables (SWE, soil moisture, temperature).
> See diagnostic triplet dt_015.

> **PITFALL**: Using bilinear interpolation for flux aggregation
> Bilinear interpolation of fluxes (mm/d) between HRUs/grid cells does not conserve mass. A 10mm runoff value gets "spread" to neighboring cells, creating artificial non-zero runoff where there should be none.
> **Do this instead**: Use area-weighted aggregation (sum of flux*area / total_area).
> See diagnostic triplet dt_009.

> **PITFALL**: VIC specific humidity fed to CRHM as relative humidity
> This is the coupling-specific manifestation of dt_001. When converting VIC forcing to CRHM .obs, specific humidity must be converted to relative humidity. If skipped, CRHM sees the atmosphere as 0.001-0.02% RH (bone dry), eliminating all sublimation.
> **Do this instead**: Use convert_vic_to_obs.py which handles this conversion. Verify RH values are 0-100%.
> See diagnostic triplet dt_001.

---

*This skill document is part of the hydrocraft-crhm knowledge infrastructure.*
*Stage 6 of 6 | Tools used: convert_vic_to_obs, merge_crhm_vic | Related triplets: dt_001, dt_009, dt_010, dt_015*
