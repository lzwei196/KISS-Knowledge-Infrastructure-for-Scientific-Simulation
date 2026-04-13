# s5 — Output Processing Skill Document

## Purpose

Extract discharge timeseries, spatial fields, and water balance components from wflow output NetCDF. Also compare wflow results with VIC output for the same basin.

## Prerequisites

- Stage s4 complete (output_grid.nc and/or output_scalar.nc exist)
- For VIC comparison: VIC routing output available

## Inputs

| Name | Type | Source | Description |
|------|------|--------|-------------|
| output_grid.nc | file | s4 | Gridded wflow output |
| output_scalar.nc | file | s4 | Scalar (gauge point) output |
| VIC discharge | file | VIC pipeline | For model intercomparison |

## Procedure

### Discharge Extraction

1. Run `extract_discharge.py --output_nc output_grid.nc --output discharge.csv`
2. Tool auto-detects outlet (cell with max mean Q) or use --lat/--lon
3. Skip warmup period (default: 365 days) to exclude spinup effects
4. Verify mean discharge is physically plausible

### Spatial Output Extraction

5. Run `extract_spatial_output.py --output_nc output_grid.nc --variables runoff,actevap,satwaterdepth`
6. Produces annual mean maps for visualization

### VIC Comparison

7. Run `compare_with_vic.py --wflow_csv discharge.csv --vic_routing_file /path/to/routing.day`
8. Compute correlation, NSE, PBIAS, KGE
9. **NOTE**: 30-50% difference in magnitude is EXPECTED between uncalibrated models (dt_w020)

### Water Balance Check

10. Verify: P = ET + Q + dS (precipitation = evapotranspiration + discharge + storage change)
11. Acceptable closure error: < 5% of total precipitation

## Expected Outputs

| Output | Path | Verification |
|--------|------|-------------|
| discharge.csv | outputs/<run>/wflow_output/discharge.csv | Has date and Q_m3s columns |
| spatial maps | outputs/<run>/wflow_output/spatial/ | NetCDF files per variable |
| comparison report | outputs/<run>/wflow_output/comparison.json | Metrics (corr, NSE, PBIAS) |
| comparison plot | outputs/<run>/wflow_output/comparison.png | Timeseries + scatter plot |

## Validation Checks

1. Mean discharge > 0 (not negative or NaN)
2. Peak discharge occurs in wet season (timing check)
3. Annual ET is 200-1500 mm (physically plausible range)
4. Water balance closes to < 5%
5. Warmup period skipped (first year may have unrealistic values)

## Common Pitfalls

- **dt_w015**: Discharge magnitude off by 2-3x (placeholder river geometry)
- **dt_w017**: Flat hydrograph with no peaks (f parameter too low)
- **dt_w020**: wflow vs VIC differ by 3-5x (expected, not a bug)
- Forgetting warmup: first year values are initialization artifacts
