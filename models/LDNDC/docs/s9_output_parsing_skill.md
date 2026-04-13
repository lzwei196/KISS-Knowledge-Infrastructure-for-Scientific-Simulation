# Output Parsing and Analysis — Skill Document

> **Stage ID**: s9_output_parsing
> **Pipeline order**: 9 of 10
> **Depends on**: s8_execution

## Purpose

Parse LDNDC output CSV/TXT files to extract scientifically meaningful results: GHG emission timeseries (N2O, CO2, CH4), nutrient leaching rates (NO3, NH4, DON), water balance components (ET, drainage, runoff), and crop yield. Compute annual C and N budgets and verify mass balance closure.

## Prerequisites

- [ ] LDNDC execution complete with exit code 0 (S8 complete)
- [ ] Output files exist in `{project_dir}/output/`
- [ ] Python environment with pandas, numpy activated

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| output_dir | directory | S8 | LDNDC output directory |
| start_year | number | S1 | First simulation year |
| end_year | number | S1 | Last simulation year |

## Procedure

### Step 1: Parse soilchemistry output

```bash
python tools/s9_output_parsing/parse_soilchemistry_output.py
```

**Key output variables** (soilchemistry-daily.txt):

| Variable | Unit | Description |
|----------|------|-------------|
| dN_n2o_emis | kgN/ha | Daily N2O emission (as N mass) |
| dC_co2_hetero_emis | kgC/ha | Daily CO2 from heterotrophic respiration |
| dC_co2_auto_emis | kgC/ha | Daily CO2 from autotrophic respiration |
| dC_ch4_emis | kgC/ha | Daily CH4 emission (as C mass) |
| dN_no3_leach | kgN/ha | Daily NO3 leaching |
| dN_nh4_leach | kgN/ha | Daily NH4 leaching |
| dN_don_leach | kgN/ha | Daily dissolved organic N leaching |
| dN_no_emis | kgN/ha | Daily NO emission |
| dN_n2_emis | kgN/ha | Daily N2 emission |
| dN_nh3_volatil | kgN/ha | Daily NH3 volatilization |

### Step 2: Parse watercycle output

```bash
python tools/s9_output_parsing/parse_watercycle_output.py
```

**Key variables** (watercycle-daily.txt):

| Variable | Unit | Description |
|----------|------|-------------|
| evapotranspiration | mm | Daily ET |
| transpiration | mm | Daily plant transpiration |
| soil_evaporation | mm | Daily soil evaporation |
| drainage | mm | Daily deep drainage/percolation |
| surface_runoff | mm | Daily surface runoff |
| soil_water_content | mm | Total soil water storage |

### Step 3: Parse physiology output

```bash
python tools/s9_output_parsing/parse_physiology_output.py
```

**Key variables** (physiology-daily.txt):

| Variable | Unit | Description |
|----------|------|-------------|
| gpp | kgC/ha | Daily gross primary production |
| npp | kgC/ha | Daily net primary production |
| lai | m2/m2 | Leaf area index |
| yield | kgC/ha | Harvested yield (cumulative) |
| n_uptake | kgN/ha | Nitrogen uptake |

### Step 4: Compute annual budgets

```bash
python tools/s9_output_parsing/aggregate_annual_budget.py
```

**Budget closure check**:
- **C budget**: C_input (GPP + litter) - C_output (Rh + Ra + harvest + leach + CH4) = delta_C_pool. Residual < 5%.
- **N budget**: N_input (deposition + fertilizer + fixation) - N_output (harvest + leach + gas) = delta_N_pool. Residual < 5%.
- **Water budget**: P - ET - Runoff - Drainage = delta_storage. Residual < 5% of P.

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| GHG timeseries | in-memory/JSON | Covers simulation period, no NaN |
| Annual budgets | in-memory/JSON | C and N residuals < 5% |

## Validation Checks

1. **N2O emission range**: Croplands typically 0.5-5.0 kgN/ha/yr; values > 20 are suspicious
2. **Yield range**: Maize 4000-12000 kgDM/ha; wheat 2000-8000 kgDM/ha (convert kgC * 2.0)
3. **Water balance**: P - ET - Drainage - Runoff ~ 0 (within 5%)
4. **C budget closure**: Residual < 5% of total C input
5. **No negative pools**: Soil C and N pools should never be negative

## Common Pitfalls

> **PITFALL**: N2O unit confusion (kgN vs. kg N2O vs. g N2O)
> LDNDC outputs dN_n2o_emis in kgN/ha. To compare with literature in g N2O/ha: multiply by 1000 * (44/28).
> See diagnostic triplet dt_012.

> **PITFALL**: Incomplete N budget terms
> N fixation is in physiology output, not soilchemistry. NH3 volatilization and NO are separate from N2O. Missing any term produces a non-closing budget.
> See diagnostic triplet dt_013.

> **PITFALL**: Yield in kgC vs. kgDM
> LDNDC reports yield in kgC/ha. To convert to dry matter: multiply by ~2.0 (assuming 45-50% C content). Compare with DSSAT yield (in kg/ha DM) accordingly.

---

*This skill document is part of the ldndc-knowledge-infrastructure package.*
*Stage 9 of 10 | Tools used: parse_soilchemistry_output, parse_watercycle_output, parse_physiology_output, aggregate_annual_budget | Related triplets: dt_012, dt_013*
