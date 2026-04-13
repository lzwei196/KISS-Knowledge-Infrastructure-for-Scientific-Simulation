# Stage 5: Output Parsing

## Purpose

Extract simulation results from CISM NetCDF output into human-readable
CSV files and summary statistics. Supports time series extraction,
spatial snapshots, and comparison to analytical solutions.

## Inputs

| Input | Source | Required |
|-------|--------|---------|
| output.nc | s4 (CISM run) | Yes |
| Config file | s3 (for grid metadata) | No |

## Outputs

| Output | Format | Used by |
|--------|--------|---------|
| results_timeseries.csv | CSV (time, vol, area, vel, temp) | s6 (plots), s7 (validation) |
| results_snapshot.csv | CSV (j, i, x, y, thk, vel, ...) | s6 (spatial plots) |
| dome_comparison.csv | CSV (metrics vs analytical) | s7 (for dome test) |

## Procedure

1. **Validate input**: Check NetCDF has time dimension, required grid dims.

2. **Extract time series**:
   - Ice volume (km^3): sum(thk * cell_area) / 1e9
   - Ice area (km^2): count(thk > 0) * cell_area / 1e6
   - Max thickness (m)
   - Mean ice thickness (m, over ice-covered cells only)
   - Max velocity (m/yr, from velnorm or sqrt(uvel^2 + vvel^2))
   - Mean velocity (m/yr, over moving ice)
   - Basal temperature range (deg C)

3. **Extract spatial snapshot** at selected timestep:
   - Flatten to CSV: (j, i, x_m, y_m, thk, usurf, topg, ...)
   - All scalar variables on (y1, x1) grid
   - 3D variables: extract surface or basal level

4. **Dome analytical check** (for benchmark):
   - Compare max thickness to analytical dome profile
   - Report center thickness, ice volume, ice area
   - Evaluate radial thickness profile

5. **Print summary** of NetCDF contents (dimensions, variables, ranges).

## Verification

- [ ] CSV output has correct number of rows (n_times for timeseries)
- [ ] Ice volume is positive and reasonable for domain
- [ ] Velocities are in m/yr (not m/s -- dt_013)
- [ ] No NaN values in extracted data

## Traps

| ID | Trap | Prevention |
|----|------|-----------|
| dt_009 | Empty output (frequency too large) | Check time dimension length |
| dt_013 | Velocity units: m/s vs m/yr in output | NetCDF output already in m/yr (factor=scyr applied) |
| dt_020 | Dimension mismatch when reading | Verify x1, y1 dimensions match grid |

## Example

```bash
# Full extraction
python tools/parse_cism_output.py --input dome.out.nc --output dome_results.csv

# Time series only
python tools/parse_cism_output.py --input output.nc --mode timeseries \
    --output ice_volume.csv

# Dome benchmark comparison
python tools/parse_cism_output.py --input dome.out.nc --mode dome_check \
    --output dome_check.csv
```
