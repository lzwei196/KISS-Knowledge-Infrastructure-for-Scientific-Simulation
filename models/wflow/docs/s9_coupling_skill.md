# s9 — Cross-Model Coupling Skill Document

## Purpose

Connect wflow outputs with other HydroCraft models: CaMa-Flood (flood routing), VIC (model intercomparison), MODFLOW (groundwater recharge), SWAT+ (sediment-water quality). Each coupling has specific data format requirements and potential for silent errors from double-counting or unit mismatches.

## Prerequisites

- wflow_sbm run complete (output_grid.nc exists)
- Target model available and configured for the same basin

## Coupling Points

### c_w01: wflow -> CaMa-Flood (Flood Routing)

**When**: wflow's built-in routing is insufficient; need CaMa-Flood's global river network + floodplain dynamics.

**CRITICAL (dt_w025)**: Use UNROUTED runoff from wflow, NOT routed discharge (q_river). wflow already routes internally — sending q_river to CaMa-Flood double-counts routing.

```bash
python wflow_to_cama.py \
  --wflow_output output_grid.nc \
  --output_dir cama_input/ \
  --basin_name chaohe \
  --start_year 2000 --end_year 2010
```

Output: `<basin>_runoff_1d_YYYY.nc` files compatible with CaMa-Flood's setup_cama_basin.py.

### c_w02: wflow vs VIC (Model Intercomparison)

**When**: Scientific comparison of two hydrology models on the same basin.

```bash
python compare_with_vic.py \
  --wflow_csv discharge.csv \
  --vic_routing_file routing_output.day \
  --output comparison.json --plot comparison.png
```

**Expected**: 30-50% magnitude difference is NORMAL (dt_w020). Focus on timing/correlation.

### c_w03: wflow_sediment -> SWAT+ (Water Quality)

**When**: Sediment-bound nutrient transport. wflow provides spatially distributed erosion rates to SWAT+ channel sediment loading.

Convert: wflow sediment yield (t/ha/yr per cell) -> SWAT+ .sed input files.

### c_w04: wflow GW Recharge -> MODFLOW

**When**: Coupled surface-groundwater modeling.

```bash
python wflow_recharge_to_modflow.py \
  --wflow_output output_grid.nc \
  --output recharge_modflow.nc
```

**UNIT CONVERSION**: wflow recharge is mm/day, MODFLOW needs m/day. Tool divides by 1000.

### c_w05: wflow Local Inertial -> SWMM

**When**: wflow 2D flood extent provides boundary conditions for urban drainage models.

### c_w06: wflow + OGGM (Glaciers)

**When**: Detailed glacier dynamics needed. Use OGGM instead of wflow's built-in degree-day glacier.

**CRITICAL**: Same double-counting trap as VIC+OGGM. One model must "own" glacier melt.

## Expected Outputs

| Coupling | Output Format | Tool |
|----------|--------------|------|
| wflow->CaMa | runoff_1d_YYYY.nc | wflow_to_cama.py |
| wflow vs VIC | comparison.json + PNG | compare_with_vic.py |
| wflow->MODFLOW | recharge.nc (m/day) | wflow_recharge_to_modflow.py |

## Validation Checks

1. CaMa-Flood input uses runoff variable, NOT q_river (dt_w025)
2. Recharge units are m/day for MODFLOW (not mm/day)
3. Spatial grids align between coupled models
4. Time periods match exactly

## Common Pitfalls

- **dt_w025**: Double-counting routing (wflow + CaMa-Flood)
- **dt_w020**: wflow vs VIC magnitude difference is expected, not a bug
- **dt_w026**: Ksat unit mismatch between models (mm/day vs mm/s vs m/day)
- Glacier double-counting (wflow + OGGM both compute melt)
