# Output Analysis -- Skill Document

> **Stage ID**: s9_output_analysis
> **Pipeline order**: 9 of 10
> **Depends on**: s8_execution

## Purpose

Extract, validate, and analyze the four categories of AquaCrop output: seasonal summary statistics, daily water fluxes, daily crop growth variables, and daily soil water storage. These outputs feed into water productivity analysis (S10) and model evaluation.

## Prerequisites

- [ ] Model executed successfully (S8 complete)
- [ ] `model.run_model()` returned True

## Inputs

| Input | Type | Source | Description |
|-------|------|--------|-------------|
| model | AquaCropModel | S8 | Executed model with populated outputs |
| output_dir | directory | User | Directory for saving CSV files |

## Procedure

### Step 1: Extract seasonal summary

```python
final_stats = model.get_simulation_results()
```

**Columns**:
| Column | Unit | Description |
|--------|------|-------------|
| Season | int | Growing season counter |
| crop Type | string | Crop name |
| Harvest Date (YYYY/MM/DD) | string | Date of harvest |
| Harvest Date (Step) | int | Day step of harvest |
| Dry yield (tonne/ha) | float | Dry matter yield |
| Fresh yield (tonne/ha) | float | Fresh weight yield (adjusted for YldWC) |
| Yield potential (tonne/ha) | float | Potential yield without water stress |
| Seasonal irrigation (mm) | float | Total irrigation applied |

### Step 2: Extract daily water fluxes

```python
water_flux = model.get_water_flux()
```

**Columns**:
| Column | Unit | Description |
|--------|------|-------------|
| time_step_counter | int | Day index |
| season_counter | int | Season index |
| dap | int | Days after planting |
| Wr | mm | Total water in root zone |
| z_gw | m | Groundwater depth |
| surface_storage | mm | Surface water storage |
| IrrDay | mm | Irrigation applied this day |
| Infl | mm | Infiltration |
| Runoff | mm | Surface runoff |
| DeepPerc | mm | Deep percolation |
| CR | mm | Capillary rise |
| GwIn | mm | Groundwater inflow |
| Es | mm | Actual soil evaporation |
| EsPot | mm | Potential soil evaporation |
| Tr | mm | Actual crop transpiration |
| TrPot | mm | Potential crop transpiration |

### Step 3: Extract daily crop growth

```python
crop_growth = model.get_crop_growth()
```

**Columns**:
| Column | Unit | Description |
|--------|------|-------------|
| time_step_counter | int | Day index |
| season_counter | int | Season index |
| dap | int | Days after planting |
| gdd | deg C | GDD accumulated this day |
| gdd_cum | deg C | Cumulative GDD |
| z_root | m | Current root depth |
| canopy_cover | fraction | Green canopy cover (0-1) |
| canopy_cover_ns | fraction | Canopy cover without stress |
| biomass | tonne/ha | Above-ground biomass |
| biomass_ns | tonne/ha | Biomass without stress |
| harvest_index | fraction | Current harvest index |
| harvest_index_adj | fraction | Adjusted harvest index |
| DryYield | tonne/ha | Current dry yield |
| FreshYield | tonne/ha | Current fresh yield |
| YieldPot | tonne/ha | Current potential yield |

### Step 4: Extract soil water storage

```python
water_storage = model.get_water_storage()
```

**Columns**: `time_step_counter`, `growing_season`, `dap`, `th1`, `th2`, ..., `thN` (volumetric water content per compartment)

### Step 5: Save to CSV

```python
import os
os.makedirs(output_dir, exist_ok=True)
final_stats.to_csv(f'{output_dir}/final_stats.csv', index=False)
water_flux.to_csv(f'{output_dir}/water_flux.csv', index=False)
crop_growth.to_csv(f'{output_dir}/crop_growth.csv', index=False)
water_storage.to_csv(f'{output_dir}/water_storage.csv', index=False)
```

### Step 6: Validate outputs

Run tool `extract_results` which performs:
- Yield > 0 check (if crop should have matured)
- Canopy cover trajectory check (rise, plateau, decline)
- Water balance closure check

## Expected Outputs

| Output | Path | Verification |
|--------|------|--------------|
| final_stats.csv | outputs/{run}/aquacrop/ | Has rows, Dry yield > 0 |
| water_flux.csv | outputs/{run}/aquacrop/ | No negative Es or Tr |
| crop_growth.csv | outputs/{run}/aquacrop/ | Canopy cover shows growth pattern |

## Validation Checks

1. **Yield positive**: `Dry yield > 0` for completed seasons
   - If zero: See dt_014

2. **Water balance**: `Precipitation + Irrigation ~ ET + Runoff + DeepPerc + delta(Storage)`
   - Large imbalance suggests a bug or unit error

3. **Canopy trajectory**: canopy_cover should increase (CGC phase), plateau (CCx), then decrease (CDC phase)
   - If flat at zero: crop never germinated. See dt_004, dt_008

4. **Biomass monotonic**: biomass should increase until senescence, then plateau
   - If declining: possible model instability (very rare)

## Common Pitfalls

> **PITFALL**: Calling get_simulation_results() when model returned False
> If run_model() was not called till_termination and the model has not finished, get_simulation_results() returns False (not a DataFrame).
> **Do this instead**: Always check `model.get_additional_information()['has_model_finished']` first.

> **PITFALL**: Misinterpreting Tr vs TrPot
> Tr is actual transpiration (reduced by water stress). TrPot is potential (no stress). The ratio Tr/TrPot is the crop water stress coefficient.
> High TrPot but low Tr = severe water stress.

---

*This skill document is part of the aquacrop-ospy-knowledge infrastructure.*
*Stage 9 of 10 | Tools used: extract_results, compare_sim_obs | Related triplets: dt_006, dt_014*
