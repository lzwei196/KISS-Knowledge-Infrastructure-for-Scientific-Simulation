# s10: Cross-Model Coupling

## Purpose

Compare Raven output with VIC output for the same basin, and optionally couple Raven with CaMa-Flood for routing. The primary use case is quantifying **structural uncertainty** by comparing independent model results.

## Raven vs VIC Comparison

### Expected Differences
VIC and Raven (HBV/GR4J/etc.) are fundamentally different models:
- **VIC**: Physically-based energy/water balance on a regular grid
- **Raven**: Conceptual rainfall-runoff on irregular HRUs

Expected uncalibrated differences:
- Mean discharge: 20-50% different
- Correlation: r > 0.5 (timing agreement)
- Peak timing: 0-3 days offset
- Volume ratio: 0.5-2.0

### Comparison Tool
```bash
python raven_vic_comparison.py \
    --raven_hydro <Hydrographs.csv> \
    --vic_discharge <routing_output.day> \
    --output_dir <path> --basin_name <name>
```

### Interpreting Results
| Metric | Good | Acceptable | Problem |
|--------|------|-----------|---------|
| Correlation r | > 0.7 | 0.5-0.7 | < 0.3 |
| Volume ratio | 0.8-1.2 | 0.5-2.0 | < 0.3 or > 3.0 |
| Peak timing | 0-1 day | 1-3 days | > 5 days |

## Raven to CaMa-Flood Coupling (Future)

Raven discharge can be routed through CaMa-Flood for flood inundation:
1. Extract subbasin runoff from Raven WatershedStorage.csv
2. Convert point runoff to gridded mm/d over subbasin area
3. Feed to CaMa-Flood as alternative to VIC runoff

**Not yet implemented** — use VIC -> CaMa-Flood pipeline for now.

## Coupling with DSSAT / RZWQM2

Raven soil moisture output (from WatershedStorage.csv) can provide soil water
conditions for crop/water quality models. Extract SOIL[0] and SOIL[1] time series.

## Common Pitfalls

- **dt_019**: Raven-VIC disagreement is expected, not an error
- **dt_020**: Different peak timing comes from different routing, not data errors
- Double-counting: if Raven has internal routing AND you run CaMa-Flood, discharge is routed twice
