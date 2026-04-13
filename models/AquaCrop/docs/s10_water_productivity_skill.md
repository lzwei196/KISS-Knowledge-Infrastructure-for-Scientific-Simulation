# Water Productivity Analysis -- Skill Document

> **Stage ID**: s10_water_productivity
> **Pipeline order**: 10 of 10
> **Depends on**: s9_output_analysis

## Purpose

Compute crop water productivity (CWP), irrigation water use efficiency (IWUE), and water footprint metrics. Perform deficit irrigation optimization by comparing multiple irrigation scenarios. This is AquaCrop's **unique analytical capability** -- the reason to choose AquaCrop over DSSAT or WOFOST when the research question is about water management.

AquaCrop uses normalized water productivity (WP*) to convert transpiration into biomass, making it the most theoretically rigorous crop model for water productivity analysis. The WP* parameter is nearly constant across environments for a given crop, which enables meaningful cross-site comparison of water use efficiency.

## Prerequisites

- [ ] Model executed and outputs extracted (S8-S9 complete)
- [ ] For optimization: ability to run multiple scenarios (~30 seconds per scenario)

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| final_stats | DataFrame | S9 | Seasonal yield summary |
| water_flux | DataFrame | S9 | Daily water balance components |
| crop_growth | DataFrame | S9 | Daily biomass and yield |
| weather_df | DataFrame | S3 | For re-running scenarios |
| soil | Soil | S2 | For re-running scenarios |
| crop | Crop | S1 | For re-running scenarios |

## Procedure

### Step 1: Compute seasonal water balance components

```python
# Group daily fluxes by season
seasonal = water_flux.groupby('season_counter').agg({
    'Es': 'sum',           # Total soil evaporation (mm)
    'Tr': 'sum',           # Total crop transpiration (mm)
    'IrrDay': 'sum',       # Total irrigation (mm)
    'Runoff': 'sum',       # Total runoff (mm)
    'DeepPerc': 'sum',     # Total deep percolation (mm)
}).reset_index()

seasonal['ET'] = seasonal['Es'] + seasonal['Tr']        # Total ET
seasonal['Precip'] = water_flux.groupby('season_counter')['Infl'].sum() + \
                     water_flux.groupby('season_counter')['Runoff'].sum()  # Approx
```

### Step 2: Compute Crop Water Productivity (CWP)

```python
# CWP = Yield / ET (kg/m3)
# Note: 1 mm water over 1 m2 = 1 liter = 0.001 m3
# So: 1 mm = 1 L/m2, and yield in kg/ha = yield * 10000 m2/ha
# CWP (kg/m3) = (yield_kg_ha / 10000) / (ET_mm / 1000) = yield_kg / (ET_mm * 10)
# Simplified: CWP = yield_tonne_ha * 1000 / ET_mm

yield_kg = final_stats['Dry yield (tonne/ha)'].values * 1000  # kg/ha
et_mm = seasonal['ET'].values

cwp = yield_kg / (et_mm * 10)  # kg/m3
# Or equivalently:
cwp = final_stats['Dry yield (tonne/ha)'].values / (et_mm / 1000)  # tonne/1000m3 = kg/m3
```

### Step 3: Compute Irrigation Water Use Efficiency (IWUE)

```python
# IWUE = (Yield_irrigated - Yield_rainfed) / Irrigation
# Requires running both rainfed and irrigated scenarios

# Or simpler: IWUE = Yield / Irrigation
irr_mm = seasonal['IrrDay'].values
iwue = yield_kg / (irr_mm * 10)  # kg/m3 (only when irrigation > 0)
```

### Step 4: Compute Water Footprint

```python
# WF = ET / Yield (m3/tonne)
wf_green = seasonal['Tr'].values * 10 / (yield_kg / 1000)   # m3/tonne (from transpiration)
wf_blue = seasonal['IrrDay'].values * 10 / (yield_kg / 1000)  # m3/tonne (from irrigation)
wf_total = (seasonal['ET'].values * 10) / (yield_kg / 1000)  # m3/tonne total
```

### Step 5: Deficit irrigation optimization

```python
# Sweep SMT thresholds from 0 (rainfed) to 100 (full irrigation)
import pandas as pd
from aquacrop import AquaCropModel, IrrigationManagement

results = []
for smt in range(0, 101, 5):  # 21 scenarios
    irr = IrrigationManagement(irrigation_method=1, SMT=[smt]*4)
    model = AquaCropModel(
        sim_start_time, sim_end_time, weather_df,
        soil, crop, iwc, irrigation_management=irr
    )
    model.run_model(till_termination=True)
    stats = model.get_simulation_results()
    flux = model.get_water_flux()

    et = flux['Es'].sum() + flux['Tr'].sum()
    irr_total = flux['IrrDay'].sum()
    yld = stats['Dry yield (tonne/ha)'].iloc[0]

    results.append({
        'SMT': smt,
        'Yield_tha': yld,
        'ET_mm': et,
        'Irrigation_mm': irr_total,
        'CWP_kg_m3': yld * 1000 / (et * 10) if et > 0 else 0,
        'IWUE_kg_m3': (yld * 1000) / (irr_total * 10) if irr_total > 0 else float('inf'),
    })

df_opt = pd.DataFrame(results)
```

### Step 6: Identify optimal strategy

The optimal deficit irrigation strategy maximizes CWP or IWUE while meeting a minimum yield target:

```python
# Find SMT that maximizes CWP:
optimal_cwp = df_opt.loc[df_opt['CWP_kg_m3'].idxmax()]

# Find SMT that achieves 90% of full-irrigation yield with minimum water:
full_yield = df_opt.loc[df_opt['SMT'] == 100, 'Yield_tha'].values[0]
target = 0.90 * full_yield
viable = df_opt[df_opt['Yield_tha'] >= target]
optimal_deficit = viable.loc[viable['Irrigation_mm'].idxmin()]
```

### Step 7: Generate comparison report

Run tool `compare_irrigation_scenarios` which produces:
- Table of scenarios (yield, ET, irrigation, CWP, IWUE)
- Yield vs irrigation curve
- Water productivity frontier plot

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| WP metrics | stdout JSON / CSV | CWP > 0 for all seasons with yield > 0 |
| Optimization results | outputs/{run}/aquacrop/deficit_optimization.csv | Contains all tested SMT scenarios |
| Scenario comparison | outputs/{run}/aquacrop/scenario_comparison.csv | Rainfed + full + deficit scenarios |

## Validation Checks

1. **CWP range**: Typical values 0.5-3.0 kg/m3 for grain crops
   - Maize: 1.5-2.5, Wheat: 0.8-1.5, Rice: 0.6-1.1, Soybean: 0.5-0.8
   - If outside range: check yield and ET computations

2. **Diminishing returns**: Yield should increase with SMT but with diminishing marginal return
   - If yield decreases with more irrigation: possible waterlogging. See dt_008.

3. **Water footprint**: Typical 500-2000 m3/tonne for grain crops
   - If very high: low yield or high evaporation environment

## Common Pitfalls

> **PITFALL**: Wrong unit conversion for CWP
> CWP = kg yield per m3 water. Common error: forgetting to convert mm to m3/m2 (1 mm = 0.001 m3/m2 = 1 L/m2) and tonne/ha to kg/m2 (1 tonne/ha = 0.1 kg/m2).
> **Do this instead**: CWP (kg/m3) = yield(tonne/ha) * 1000 / (ET(mm) * 10)

> **PITFALL**: Comparing CWP across sites without normalization
> Raw CWP varies with climate (higher ET0 = lower CWP even for same crop). AquaCrop's WP* is already normalized for ET0 and CO2, making cross-site comparison valid at the model level. But computed CWP from outputs is NOT normalized.
> **Do this instead**: Report both raw CWP and the model's internal WP* parameter.

> **PITFALL**: Ignoring evaporation in water productivity
> Es (soil evaporation) is a loss that does not contribute to yield. True crop water productivity should use only Tr (transpiration), not total ET.
> **Do this instead**: Report both ET-based CWP and Tr-based CWP separately.

---

*This skill document is part of the aquacrop-ospy-knowledge infrastructure.*
*Stage 10 of 10 | Tools used: compute_water_productivity, optimize_deficit_irrigation, compare_irrigation_scenarios | Related triplets: dt_008*
